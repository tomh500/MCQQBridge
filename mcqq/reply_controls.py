"""QQ reply wording, five-line previews, and short-lived expansion storage."""
import asyncio
from contextlib import closing
import json
import logging
import re
import secrets
import sqlite3
import time

log = logging.getLogger(__name__)
LEXICON = (
    ("内存", "记忆体"), ("服务器", "伺服器"), ("账号", "帐号"),
    ("消息", "讯息"), ("信息", "资讯"), ("获取", "取得"),
    ("配置", "设定"), ("设置", "设定"), ("文件", "档案"),
    ("登录", "登入"), ("网络", "网路"), ("重试", "再试"),
    ("运行", "运作"), ("软件", "软体"), ("支持", "支援"),
    ("默认", "预设"), ("用户", "使用者"), ("视频", "影片"),
)


def localize(text):
    # Keep slash-command spellings and URLs as actionable literal text.
    parts = re.split(r"(/[^\s，。；：()（）]+)", text)
    for i in range(0, len(parts), 2):
        for original, taiwan_usage in LEXICON:
            parts[i] = parts[i].replace(original, taiwan_usage)
    return "".join(parts)


def preview(text):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if len(lines) <= 5:
        return text, False
    result = "\n".join(lines[:5])
    if len(result) > 1700:
        result = result[:1700] + "…"
    return result + f"\n…另有 {len(lines)-5} 行；仅 Bot 主人或管理可展开。", True


def chunks(text, limit=1700):
    while text:
        if len(text) <= limit:
            yield text
            return
        boundary = text.rfind("\n", 0, limit)
        if boundary < limit // 2:
            boundary = limit
        yield text[:boundary]
        text = text[boundary:]


class ExpandedStore:
    TTL = 1800

    def __init__(self, database, redis_url=None):
        self.database = database
        self.redis = None
        if redis_url:
            import redis.asyncio as redis_async
            self.redis = redis_async.Redis.from_url(redis_url, decode_responses=True,
                                                    socket_connect_timeout=2, socket_timeout=2)

    def _sqlite_save(self, token, data):
        with closing(sqlite3.connect(self.database, timeout=5)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS expanded_replies (token TEXT PRIMARY KEY, payload TEXT NOT NULL, expires REAL NOT NULL)")
            db.execute("DELETE FROM expanded_replies WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO expanded_replies VALUES (?,?,?)", (token, data, time.time()+self.TTL))

    def _sqlite_load(self, token):
        with closing(sqlite3.connect(self.database, timeout=5)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS expanded_replies (token TEXT PRIMARY KEY, payload TEXT NOT NULL, expires REAL NOT NULL)")
            row = db.execute("SELECT payload FROM expanded_replies WHERE token=? AND expires>?", (token, time.time())).fetchone()
            return row[0] if row else None

    async def save(self, group, text):
        token = secrets.token_urlsafe(12)
        data = json.dumps({"group": group, "text": text}, ensure_ascii=False)
        if self.redis:
            try:
                await self.redis.setex("mcqq:expand:" + token, self.TTL, data)
                return token
            except Exception as exc:
                log.warning("Reply cache unavailable (%s); using SQLite fallback", type(exc).__name__)
        await asyncio.to_thread(self._sqlite_save, token, data)
        return token

    async def load(self, group, token):
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", token):
            return None
        data = None
        if self.redis:
            try:
                data = await self.redis.get("mcqq:expand:" + token)
            except Exception as exc:
                log.warning("Reply cache unavailable (%s); checking SQLite fallback", type(exc).__name__)
        if data is None:
            data = await asyncio.to_thread(self._sqlite_load, token)
        if data is None:
            return None
        value = json.loads(data)
        return value["text"] if value.get("group") == group else None

    async def close(self):
        if self.redis:
            await self.redis.aclose()

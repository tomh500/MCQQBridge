"""Bounded group history and opt-in OpenAI-compatible group conversation."""
import asyncio
from contextlib import contextmanager, closing
import hashlib
import json
import math
import re
import regex
import secrets
import sqlite3
import time
from pathlib import Path

import aiohttp
import yaml

from . import media
from .feature_policy import FeaturePolicy

MAX_IMAGE_BYTES = 200 * 1024 * 1024


def vector(text):
    """Persist a compact lexical vector when the provider has no embedding endpoint."""
    words = re.findall(r"[\u3400-\u9fff]|[a-zA-Z0-9_]+", text.lower())
    counts = {}
    for word in words:
        slot = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=2).digest(), "big") % 512
        counts[slot] = counts.get(slot, 0) + 1
    norm = math.sqrt(sum(value * value for value in counts.values())) or 1
    return {str(key): value / norm for key, value in counts.items()}


def similarity(left, right):
    return sum(value * right.get(key, 0) for key, value in left.items())


class History:
    def __init__(self, database, image_dir):
        self.database = database
        self.image_dir = Path(image_dir)
        self.image_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS group_ai_history(
                    id INTEGER PRIMARY KEY, event_id TEXT UNIQUE, group_id TEXT NOT NULL,
                    member_id TEXT NOT NULL, text TEXT NOT NULL, image_path TEXT,
                    display_name TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS group_ai_history_group ON group_ai_history(group_id,id);
                CREATE TABLE IF NOT EXISTS group_ai_memory(
                    id INTEGER PRIMARY KEY, group_id TEXT NOT NULL, summary TEXT NOT NULL,
                    member_id TEXT NOT NULL DEFAULT '', embedding TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS group_ai_profiles(
                    group_id TEXT NOT NULL, member_id TEXT NOT NULL, display_name TEXT NOT NULL,
                    updated REAL NOT NULL, PRIMARY KEY(group_id,member_id));
            """)
            if "display_name" not in {row[1] for row in db.execute("PRAGMA table_info(group_ai_history)")}:
                db.execute("ALTER TABLE group_ai_history ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
            if "member_id" not in {row[1] for row in db.execute("PRAGMA table_info(group_ai_memory)")}:
                db.execute("ALTER TABLE group_ai_memory ADD COLUMN member_id TEXT NOT NULL DEFAULT ''")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_sender_log'").fetchone():
                db.execute("""UPDATE group_ai_history SET display_name=COALESCE(
                    (SELECT nickname FROM chat_sender_log s WHERE s.event=group_ai_history.event_id
                     AND s.group_id=group_ai_history.group_id AND s.member_openid=group_ai_history.member_id), '')
                    WHERE display_name=''""")
            db.execute("""INSERT INTO group_ai_profiles(group_id,member_id,display_name,updated)
                SELECT group_id,member_id,display_name,created FROM group_ai_history
                WHERE display_name<>'' AND member_id<>'__bot__' ORDER BY created
                ON CONFLICT(group_id,member_id) DO UPDATE SET display_name=excluded.display_name,updated=excluded.updated
                WHERE excluded.updated>group_ai_profiles.updated""")

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.database, timeout=10)) as db, db:
            yield db

    def add(self, event_id, group, member, text, image_path=None, display_name=""):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO group_ai_history(event_id,group_id,member_id,text,image_path,display_name,created) VALUES (?,?,?,?,?,?,?)",
                       (event_id, group, member, text[:2000], image_path, display_name[:80], time.time()))
            if display_name and member != "__bot__":
                db.execute("""INSERT INTO group_ai_profiles(group_id,member_id,display_name,updated) VALUES (?,?,?,?)
                    ON CONFLICT(group_id,member_id) DO UPDATE SET display_name=excluded.display_name,updated=excluded.updated""",
                    (group, member, display_name[:80], time.time()))
            old = db.execute("SELECT id,image_path FROM group_ai_history WHERE group_id=? ORDER BY id DESC LIMIT -1 OFFSET 300", (group,)).fetchall()
            db.executemany("DELETE FROM group_ai_history WHERE id=?", [(row[0],) for row in old])
        for _, path in old:
            if path:
                (self.image_dir / path).unlink(missing_ok=True)

    def recent(self, group, limit=30):
        with self.connect() as db:
            rows = db.execute("SELECT member_id,text,image_path,display_name FROM group_ai_history WHERE group_id=? ORDER BY id DESC LIMIT ?", (group, limit)).fetchall()
        return list(reversed(rows))

    def all_recent(self, group):
        return self.recent(group, 300)

    def remember(self, group, summary, embedding, member=""):
        with self.connect() as db:
            db.execute("INSERT INTO group_ai_memory(group_id,summary,member_id,embedding,created) VALUES (?,?,?,?,?)",
                       (group, summary[:4000], member, json.dumps(embedding), time.time()))
            db.execute("DELETE FROM group_ai_memory WHERE group_id=? AND id NOT IN (SELECT id FROM group_ai_memory WHERE group_id=? ORDER BY id DESC LIMIT 100)", (group, group))

    def recall(self, group, query, speaker=None, limit=3):
        q = vector(query)
        with self.connect() as db:
            names = db.execute("SELECT member_id,display_name FROM group_ai_profiles WHERE group_id=?", (group,)).fetchall()
            memories = db.execute("SELECT member_id,summary,embedding FROM group_ai_memory WHERE group_id=? ORDER BY id DESC LIMIT 100", (group,)).fetchall()
        by_name = {}
        for member, name in names:
            by_name.setdefault(name, set()).add(member)
        mentioned = {next(iter(ids)) for name, ids in by_name.items()
                     if len(name) >= 2 and name in query and len(ids) == 1}
        mentioned.update(member for member, _, _ in memories if member and member in query)
        targets = mentioned | ({speaker} if speaker else set())
        ranked = sorted(((similarity(q, json.loads(embedding)) + (2 if member in mentioned else 1 if member == speaker else 0), summary)
                         for member, summary, embedding in memories if not member or member in targets), reverse=True)
        return [summary for score, summary in ranked[:limit] if score > 0]

    def save_image(self, event_id, image):
        if len(image) > media.MAX_BYTES:
            return None
        name = hashlib.sha256(event_id.encode()).hexdigest() + ".img"
        files = list(self.image_dir.glob("*.img"))
        if sum(path.stat().st_size for path in files) + len(image) > MAX_IMAGE_BYTES:
            for path in files:
                path.unlink(missing_ok=True)
        (self.image_dir / name).write_bytes(image)
        return name


class GroupAI:
    def __init__(self, settings):
        path = Path(settings["group_ai_config"])
        self.config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {"enabled": False}
        self.config = self.config or {}
        self.history = History(settings["database"], Path(settings["database"]).parent / "group-ai-images")
        self.locks = {}
        self.unavailable_until = 0
        self.feature_policy = FeaturePolicy(settings)
        self.filter = self._load_filter(settings)

    @staticmethod
    def _load_filter(settings):
        source = Path(settings.get("group_ai_word_filter", ""))
        if not source.is_file():
            return None
        cfg = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        rules = cfg.get("word-filter", {})
        if not rules.get("enabled"):
            return None
        root = source.parent
        red, yellow = list(rules.get("red", [])), list(rules.get("yellow", []))
        for filename in ("G79SensitiveWords.json", "X19SensitiveWords.json"):
            data = json.loads((root / filename).read_text(encoding="utf-8"))["regex"]
            red.extend(data["intercept"].values())
            yellow.extend(data["replace"].values())
            for code, expression in data["shield"].items():
                (red if filename.startswith("G79") and 1 <= int(code) <= 449 else yellow).append(expression)
        return ([regex.compile(item) for item in red], [regex.compile(item) for item in yellow])

    def check(self, text):
        if self.filter is None:
            return text
        red, yellow = self.filter
        text = text[:2000]
        try:
            if any(rule.search(text, timeout=0.02) for rule in red):
                return None
            for rule in yellow:
                text = rule.sub("*", text, timeout=0.02)
            return text
        except TimeoutError:
            return None

    async def capture(self, message, group, member, text):
        image_path = None
        source = media.extract(getattr(message, "raw_data", None) or {}).get("media", [])
        if source:
            try:
                async with aiohttp.ClientSession() as client:
                    _, _, _, data = await media.fetch(client, source[0]["url"], full=True)
                image_path = await asyncio.to_thread(self.history.save_image, str(message.id), data)
            except (ValueError, aiohttp.ClientError, asyncio.TimeoutError):
                pass
        author = getattr(message, "author", None)
        name = str(getattr(author, "nickname", "") or getattr(author, "username", "") or "")
        if not name:
            with self.history.connect() as db:
                row = db.execute("SELECT display_name FROM group_ai_profiles WHERE group_id=? AND member_id=?", (group, member)).fetchone()
            name = row[0] if row else ""
        await asyncio.to_thread(self.history.add, str(message.id), group, member, text, image_path, name)

    def configured(self):
        return bool(self.config.get("enabled") and self.config.get("api_key") and self.config.get("base_url") and self.config.get("model"))

    async def complete(self, messages, *, max_tokens=500):
        cfg = self.config
        body = {"model": cfg["model"], "messages": messages, "stream": False,
                "max_tokens": max_tokens, "temperature": cfg.get("temperature", 0.7)}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as client:
            async with client.post(cfg["base_url"].rstrip("/") + "/v1/chat/completions",
                                   headers={"Authorization": "Bearer " + cfg["api_key"]}, json=body) as response:
                response.raise_for_status()
                result = await response.json()
        return result["choices"][0]["message"]["content"].strip()

    async def reply(self, group, prompt, speaker=None):
        if not self.configured():
            return "群对话尚未设定模型服务。"
        if time.monotonic() < self.unavailable_until:
            return "对话服务暂时无法回应，请稍后再试。"
        lock = self.locks.setdefault(group, asyncio.Lock())
        async with lock:
            past = await asyncio.to_thread(self.history.recent, group, 12)
            recalled = await asyncio.to_thread(self.history.recall, group, prompt, speaker)
            messages = [{"role": "system", "content": self.config.get("system_prompt", "你是群聊助手，用简体中文自然回答。")[:8000]}]
            for example in self.config.get("examples", [])[:8]:
                if isinstance(example, dict) and example.get("role") in ("user", "assistant"):
                    messages.append({"role": example["role"], "content": str(example.get("content", ""))[:1000]})
            if recalled:
                messages.append({"role": "system", "content": "过往群聊摘要（仅供参考）：\n" + "\n".join(recalled)})
            messages.extend({"role": "assistant" if member == "__bot__" else "user",
                             "content": ("" if member == "__bot__" else (name or "群友" + hashlib.sha256(member.encode()).hexdigest()[:6]) + "：") + text[:300] + (" [附有图片]" if image else "")}
                            for member, text, image, name in past if text or image)
            if not self.feature_policy.check(group, 'llm', consume=False)['allowed']:
                return '维护中暂不可用。'
            try:
                answer = await self.complete(messages, max_tokens=int(self.config.get("max_tokens", 500)))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, IndexError):
                self.unavailable_until = time.monotonic() + 60
                return "对话服务暂时无法回应，请稍后再试。"
            answer = self.check(answer)
            if not answer:
                return "回应包含限制词，已停止发送。"
            await asyncio.to_thread(self.history.add, "bot:" + secrets.token_hex(16), group, "__bot__", answer)
            return answer

    async def summarize(self, group):
        if not self.configured():
            return "群对话尚未设定模型服务。"
        if time.monotonic() < self.unavailable_until:
            return "对话服务暂时无法回应，请稍后再试。"
        lock = self.locks.setdefault(group, asyncio.Lock())
        async with lock:
            rows = await asyncio.to_thread(self.history.all_recent, group)
            if not rows:
                return "目前没有可整理的群聊讯息。"
            counts = {}
            for member, _, _, _ in rows:
                if member != "__bot__":
                    counts[member] = counts.get(member, 0) + 1
            selected = sorted(counts, key=lambda member: counts[member], reverse=True)[:30]
            labels = {member: "u" + str(index + 1) for index, member in enumerate(selected)}
            display = {}
            for member, _, _, name in rows:
                if member in labels and name:
                    display[member] = name
            content = "\n".join(
                ("Bot" if member == "__bot__" else labels.get(member, "其他群友") + "(" + display.get(member, "群友") + ")")
                + "：" + text[:350] for member, text, _, _ in rows)[-18000:]
            if not self.feature_policy.check(group, 'llm', consume=False)['allowed']:
                return '维护中暂不可用。'
            try:
                summary = await self.complete([
                    {"role": "system", "content": self.config.get("system_prompt", "")[:8000]},
                    {"role": "user", "content": "请压缩下列群聊，输出严格 JSON，格式为 {\"group\":\"群级关键事实\",\"users\":{\"u1\":\"此人的事实与偏好\"}}。只给有可靠依据的群友写摘要，不猜测，不保存敏感资料，不把不同人混为一谈。\n" + content},
                ], max_tokens=1800)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, IndexError):
                self.unavailable_until = time.monotonic() + 60
                return "历史讯息整理失败，请稍后再试。"
            summary = self.check(summary)
            if not summary:
                return "摘要包含限制词，未储存。"
            try:
                parsed = json.loads(summary[summary.index("{"):summary.rindex("}") + 1])
            except (ValueError, TypeError):
                return "模型未回传可核对的群友摘要，本次未储存。"
            group_summary = parsed.get("group") if isinstance(parsed, dict) else None
            users = parsed.get("users", {}) if isinstance(parsed, dict) else {}
            if not isinstance(group_summary, str) or not isinstance(users, dict):
                return "模型摘要格式无效，本次未储存。"
            group_summary = self.check(group_summary[:4000])
            if group_summary:
                await asyncio.to_thread(self.history.remember, group, group_summary, vector(group_summary))
            saved = 0
            for member, label in labels.items():
                personal = users.get(label)
                if not isinstance(personal, str) or not personal.strip():
                    continue
                personal = self.check(personal[:1500])
                if personal:
                    name = display.get(member, "群友")
                    memory = name + "：" + personal
                    await asyncio.to_thread(self.history.remember, group, memory, vector(memory), member)
                    saved += 1
            return f"已整理本群摘要及 {saved} 位群友的记忆。"

"""One daily SFW anime portrait and at most one atomic exchange per member."""
import asyncio
import json
import logging
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from aiohttp import web

log = logging.getLogger(__name__)
CATALOG_PATH = Path(__file__).with_name("waifu_catalog.json")


def valid_entry(entry):
    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not 1 <= len(entry["name"]) <= 100:
        return False
    url = entry.get("image_url", "")
    source = entry.get("source_url", "")
    return (isinstance(url, str) and urlparse(url).scheme == "https" and
            urlparse(url).hostname == "s4.anilist.co" and
            urlparse(url).path.startswith("/file/anilistcdn/character/large/") and
            isinstance(source, str) and source.startswith("https://anilist.co/character/"))


class DailyWaifuStorage:
    def __init__(self, settings):
        import pymysql
        import pymongo
        import redis
        self.mysql = dict(settings["mysql"])
        self.mysql.update(charset="utf8mb4", autocommit=True, connect_timeout=3, read_timeout=3, write_timeout=3)
        self.pymysql = pymysql
        self.mongo = pymongo.MongoClient(settings["mongo_uri"], serverSelectionTimeoutMS=3000)
        self.catalog = self.mongo[settings.get("mongo_database", "mcqq_daily")]["waifu_catalog"]
        self.redis = redis.Redis.from_url(settings["redis_url"], socket_connect_timeout=2, socket_timeout=2,
                                          decode_responses=True)
        self.fallback = [item for item in json.loads(CATALOG_PATH.read_text(encoding="utf-8")) if valid_entry(item)]
        if not self.fallback:
            raise ValueError("empty waifu catalog")

    def close(self):
        self.mongo.close()
        self.redis.close()

    def choose(self, exclude_url=None):
        try:
            match = {"enabled": True}
            if exclude_url:
                match["image_url"] = {"$ne": exclude_url}
            sample = next(self.catalog.aggregate([{"$match": match}, {"$sample": {"size": 1}}],
                                                maxTimeMS=2000), None)
            if sample and valid_entry(sample):
                return sample
        except Exception as exc:
            log.warning("Waifu catalog unavailable (%s); using bundled catalog", type(exc).__name__)
        import secrets
        entries = [item for item in self.fallback if item["image_url"] != exclude_url]
        if not entries:
            raise ValueError("no alternate portrait")
        return entries[secrets.randbelow(len(entries))]

    @staticmethod
    def result(row, *, new=False, exchanged=False):
        return {"name": row[0], "image_url": row[1], "source_url": row[2],
                "swapped": bool(row[3]), "draw_token": row[4],
                "new": new, "exchanged": exchanged}

    def get_or_create(self, subject, day):
        # Read MySQL every time: an owner reset or exchange must never return a stale cache value.
        with self.pymysql.connect(**self.mysql) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT name,image_url,source_url,swapped,draw_token FROM daily_waifu_draws WHERE subject=%s AND day=%s",
                               (subject, day))
                row = cursor.fetchone()
                fresh = False
                if row is None:
                    entry = self.choose()
                    cursor.execute("INSERT IGNORE INTO daily_waifu_draws(subject,day,name,image_url,source_url,draw_token) VALUES (%s,%s,%s,%s,%s,%s)",
                                   (subject, day, entry["name"], entry["image_url"], entry["source_url"], secrets.token_hex(16)))
                    fresh = cursor.rowcount == 1
                    cursor.execute("SELECT name,image_url,source_url,swapped,draw_token FROM daily_waifu_draws WHERE subject=%s AND day=%s",
                                   (subject, day))
                    row = cursor.fetchone()
        result = self.result(row, new=fresh)
        if not valid_entry(result):
            raise ValueError("invalid stored waifu")
        return result

    def swap_once(self, subject, day, expected_token=None):
        with self.pymysql.connect(**self.mysql) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT name,image_url,source_url,swapped,draw_token FROM daily_waifu_draws WHERE subject=%s AND day=%s",
                               (subject, day))
                previous = cursor.fetchone()
                if previous is None:
                    return {"error": "请先发送 /今日老婆 抽取今天的角色。"}
                if expected_token is not None and expected_token != previous[4]:
                    return {"error": "这张换取按钮已失效，请重新发送 /今日老婆。"}
                exchanged = False
                if not previous[3]:
                    entry = self.choose(exclude_url=previous[1])
                    cursor.execute("""UPDATE daily_waifu_draws SET name=%s,image_url=%s,source_url=%s,swapped=1
                        WHERE subject=%s AND day=%s AND swapped=0 AND image_url=%s AND draw_token=%s""",
                        (entry["name"], entry["image_url"], entry["source_url"], subject, day, previous[1], previous[4]))
                    exchanged = cursor.rowcount == 1
                cursor.execute("SELECT name,image_url,source_url,swapped,draw_token FROM daily_waifu_draws WHERE subject=%s AND day=%s",
                               (subject, day))
                row = cursor.fetchone()
        result = self.result(row, exchanged=exchanged)
        if not valid_entry(result):
            raise ValueError("invalid stored waifu")
        return result

    def reset_all(self, day, event):
        with self.pymysql.connect(**self.mysql) as connection:
            connection.begin()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("INSERT IGNORE INTO daily_waifu_resets(event,day) VALUES (%s,%s)", (event, day))
                    if cursor.rowcount == 0:
                        connection.commit()
                        return {"reset": False, "count": 0}
                    cursor.execute("DELETE FROM daily_waifu_draws WHERE day=%s", (day,))
                    count = cursor.rowcount
                connection.commit()
                return {"reset": True, "count": count}
            except Exception:
                connection.rollback()
                raise


def register(app, cfg, identity, storage=None):
    enabled = cfg.get("daily_waifu", {}).get("enabled", False)
    if enabled and storage is None:
        storage = DailyWaifuStorage(cfg["daily_waifu"])
    if storage is not None and hasattr(storage, "close"):
        async def cleanup(app):
            yield
            await asyncio.to_thread(storage.close)
        app.cleanup_ctx.append(cleanup)

    async def today(request):
        data = await request.json()
        subject = identity(data)
        if not enabled or storage is None:
            return web.json_response({"error": "今日老婆功能尚未启用。"}, status=503)
        day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        try:
            result = await asyncio.to_thread(storage.get_or_create, subject, day)
        except Exception as exc:
            log.error("Daily waifu storage unavailable: %s", type(exc).__name__)
            return web.json_response({"error": "今日老婆暂时无法取得，请稍后再试。"}, status=503)
        return web.json_response(dict(result, day=day))

    async def swap(request):
        data = await request.json()
        subject = identity(data)
        if not enabled or storage is None:
            return web.json_response({"error": "今日老婆功能尚未启用。"}, status=503)
        day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        try:
            token = data.get("draw_token")
            if token is not None and (not isinstance(token, str) or len(token) > 64):
                raise ValueError("draw_token")
            result = await asyncio.to_thread(storage.swap_once, subject, day, token)
        except Exception as exc:
            log.error("Daily waifu exchange unavailable: %s", type(exc).__name__)
            return web.json_response({"error": "换老婆暂时无法使用，请稍后再试。"}, status=503)
        return web.json_response(dict(result, day=day))

    async def reset(request):
        data = await request.json()
        identity(data)
        owners = cfg.get("bot_roles", {}).get("owners", [])
        if data["member_openid"] not in owners:
            return web.json_response({"error": "只有 Bot 主人可以重置今日老婆。"}, status=403)
        event = data.get("event_id")
        if not isinstance(event, str) or not 1 <= len(event) <= 256:
            raise ValueError("event_id")
        if not enabled or storage is None:
            return web.json_response({"error": "今日老婆功能尚未启用。"}, status=503)
        day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        try:
            result = await asyncio.to_thread(storage.reset_all, day, event)
        except Exception as exc:
            log.error("Daily waifu reset unavailable: %s", type(exc).__name__)
            return web.json_response({"error": "重置暂时无法使用，请稍后再试。"}, status=503)
        return web.json_response(dict(result, day=day))

    app.router.add_post("/v1/waifu/today", today)
    app.router.add_post("/v1/waifu/swap", swap)
    app.router.add_post("/v1/waifu/reset", reset)

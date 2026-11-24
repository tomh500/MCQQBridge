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
from .waifu_economy import WaifuEconomy

log = logging.getLogger(__name__)
CATALOG_PATH = Path(__file__).with_name("waifu_catalog.json")


def valid_entry(entry):
    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not 1 <= len(entry["name"]) <= 100:
        return False
    url = entry.get("image_url", "")
    source = entry.get("source_url", "")
    return (isinstance(url, str) and urlparse(url).scheme == "https" and
            urlparse(url).hostname == "lain.bgm.tv" and
            urlparse(url).path.startswith("/pic/crt/l/") and
            isinstance(source, str) and source.startswith("https://bgm.tv/character/"))


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
        self.works = {item["source_url"]: item.get("work", "未知作品") for item in self.fallback}
        if not self.fallback:
            raise ValueError("empty waifu catalog")

    def close(self):
        self.mongo.close()
        self.redis.close()

    def choose(self, exclude_url=None):
        try:
            match = {"enabled": True, "source_url": {"$in": list(self.works)}}
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

    def entries(self):
        # MongoDB controls enablement; source metadata stays in the versioned catalog.
        by_url = {e['source_url']: e for e in self.fallback}
        try:
            enabled = list(self.catalog.find({'enabled': True, 'source_url': {'$in': list(by_url)}}, {'source_url': 1}).max_time_ms(2000))
            found = [by_url[e['source_url']] for e in enabled if e.get('source_url') in by_url]
            if found:
                return found
        except Exception as exc:
            log.warning('Waifu catalog unavailable (%s); using bundled catalog', type(exc).__name__)
        return list(self.fallback)

    def result(self, row, *, new=False, exchanged=False):
        return {"name": row[0], "image_url": row[1], "source_url": row[2],
                "work": self.works.get(row[2], "未知作品"),
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
                    cursor.execute("""UPDATE daily_waifu_draws SET name=%s,image_url=%s,source_url=%s,swapped=1,draw_token=%s
                        WHERE subject=%s AND day=%s AND swapped=0 AND image_url=%s AND draw_token=%s""",
                        (entry["name"], entry["image_url"], entry["source_url"], secrets.token_hex(16), subject, day, previous[1], previous[4]))
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

    def accept(self, subject, day, token):
        with self.pymysql.connect(**self.mysql) as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE daily_waifu_draws SET swapped=1 WHERE subject=%s AND day=%s AND draw_token=%s", (subject, day, token))
                if cursor.rowcount == 0:
                    cursor.execute("SELECT 1 FROM daily_waifu_draws WHERE subject=%s AND day=%s AND draw_token=%s", (subject, day, token))
                    if not cursor.fetchone():
                        return {"error": "按钮已失效。"}
        return {"accepted": True}


def register(app, cfg, identity, storage=None, role_store=None, economy=None):
    enabled = cfg.get("daily_waifu", {}).get("enabled", False)
    if enabled and storage is None:
        storage = DailyWaifuStorage(cfg["daily_waifu"])
    economy = economy or (WaifuEconomy(storage) if isinstance(storage, DailyWaifuStorage) else None)
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
            result = await asyncio.to_thread(economy.today if economy else storage.get_or_create, subject, day)
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
            result = await asyncio.to_thread(economy.swap if economy else storage.swap_once, subject, day, token)
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

    async def accept(request):
        data = await request.json()
        subject = identity(data)
        token = data.get("draw_token")
        if not enabled or storage is None or not isinstance(token, str) or len(token) != 32:
            return web.json_response({"error": "按钮已失效。"}, status=400)
        day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        try:
            event = data.get('event_id')
            if economy and (not isinstance(event, str) or not 1 <= len(event) <= 256):
                raise ValueError('event')
            result = await asyncio.to_thread(economy.accept, subject, day, token, event) if economy else await asyncio.to_thread(storage.accept, subject, day, token)
        except Exception:
            log.exception("Daily waifu acceptance unavailable")
            return web.json_response({"error": "暂时无法确认。"}, status=503)
        return web.json_response(result)

    async def privileged(data):
        member = data['member_openid']
        roles = cfg.get('bot_roles', {})
        if member in roles.get('owners', []):
            return True
        if role_store is None:
            return False
        with role_store.connect() as db:
            row = db.execute('SELECT active FROM bot_role_admins WHERE member_openid=?', (member,)).fetchone()
            return bool(row['active']) if row else member in roles.get('admins', [])

    async def points(request):
        data = await request.json()
        subject = identity(data)
        target, action = data.get('target_member_openid'), data.get('action')
        if action not in ('query', 'add', 'set') or not economy:
            raise ValueError('action')
        if target is not None or action != 'query':
            if not await privileged(data):
                return web.json_response({'error': '没有权限。'}, status=403)
            if not isinstance(target, str) or not 1 <= len(target) <= 128:
                raise ValueError('target')
            target_data = dict(data, member_openid=target)
            subject = identity(target_data)
        amount = data.get('amount', 0)
        event = data.get('event_id')
        if not isinstance(amount, int) or isinstance(amount, bool) or abs(amount) > 2147483647 or (action == 'set' and amount < 0) or not isinstance(event, str) or not 1 <= len(event) <= 256:
            raise ValueError('amount/event')
        try:
            return web.json_response(await asyncio.to_thread(economy.points, subject, action, amount, event))
        except Exception:
            log.exception('Waifu point operation failed')
            return web.json_response({'error': '积分查询暂时不可用。'}, status=503)

    async def wish(request):
        data = await request.json()
        subject = identity(data)
        keyword, event = data.get('keyword'), data.get('event_id')
        if not economy or not isinstance(keyword, str) or not 1 <= len(keyword.strip()) <= 100 or not isinstance(event, str) or not 1 <= len(event) <= 256:
            raise ValueError('keyword/event')
        day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        try:
            result = await asyncio.to_thread(economy.wish, subject, day, keyword, event)
            return web.json_response(dict(result, day=day))
        except Exception:
            log.exception('Waifu wish failed')
            return web.json_response({'error': '许愿暂时不可用。'}, status=503)

    app.router.add_post('/v1/waifu/points', points)
    app.router.add_post('/v1/waifu/wish', wish)
    app.router.add_post("/v1/waifu/today", today)
    app.router.add_post("/v1/waifu/swap", swap)
    app.router.add_post("/v1/waifu/accept", accept)
    app.router.add_post("/v1/waifu/reset", reset)

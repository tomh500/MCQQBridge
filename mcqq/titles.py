"""Self-service group titles, authorized by official event identity and role."""
import json
import re
import time
import unicodedata
import asyncio
import logging
from pathlib import Path
from aiohttp import web
from .store import BindingError


MYSQL_SCHEMA = """CREATE TABLE IF NOT EXISTS mcqq_chat_titles (
    subject VARCHAR(260) NOT NULL, group_openid VARCHAR(128) NOT NULL,
    title VARCHAR(64) NOT NULL, member_role VARCHAR(16) NOT NULL,
    changed DOUBLE NOT NULL, PRIMARY KEY(subject,group_openid)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;"""


def mirror_sql(row):
    def string(value):
        return "CONVERT(X'" + value.encode("utf-8").hex() + "' USING utf8mb4)"
    values = ",".join([string(row["subject"]), string(row["group_id"]), string(row["title"]), string(row["role"]), repr(row["changed"])])
    return ("INSERT INTO mcqq_chat_titles(subject,group_openid,title,member_role,changed) VALUES(" + values + ") "
            "ON DUPLICATE KEY UPDATE title=IF(VALUES(changed)>=changed,VALUES(title),title),"
            "member_role=IF(VALUES(changed)>=changed,VALUES(member_role),member_role),changed=GREATEST(changed,VALUES(changed));")


async def mysql_run(defaults, sql):
    process = await asyncio.create_subprocess_exec("mysql", "--defaults-extra-file=" + str(defaults),
        "--batch", "--connect-timeout=3", stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _, error = await asyncio.wait_for(process.communicate(sql.encode("utf-8")), 8)
        if process.returncode:
            raise RuntimeError("MySQL mirror command failed")
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise


def register(app, cfg, store, identity):
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS chat_titles (
                subject TEXT NOT NULL, group_id TEXT NOT NULL, title TEXT NOT NULL,
                PRIMARY KEY(subject,group_id)
            );
            CREATE TABLE IF NOT EXISTS chat_title_cooldowns (
                subject TEXT PRIMARY KEY, changed REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_title_events (
                event TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, reply TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_title_outbox (
                id INTEGER PRIMARY KEY, subject TEXT NOT NULL, group_id TEXT NOT NULL,
                title TEXT NOT NULL, role TEXT NOT NULL, changed REAL NOT NULL, synced INTEGER NOT NULL DEFAULT 0
            );
        """)

    async def change(request):
        data = await request.json()
        subject = identity(data)
        role = data.get("role", "member")
        action = data.get("action")
        event = data.get("event_id")
        if role not in ("member", "admin", "owner") or action not in ("set", "clear"):
            raise ValueError("role/action")
        if not isinstance(event, str) or not 1 <= len(event) <= 256:
            raise ValueError("event")
        title = data.get("title", "") if action == "set" else ""
        if not isinstance(title, str):
            raise ValueError("title")
        title = title.strip()
        if action == "set":
            if not 1 <= len(title) <= 10:
                raise BindingError("头衔限 1–10 个字符，中文、英文、数字及空格均计入长度。")
            if any(unicodedata.category(c) in ("Cc", "Cf", "Cs") or c in "[]§" for c in title) or re.search(r"(?i)&[0-9a-fk-orx]", title):
                raise BindingError("头衔不能包含换行、控制字符、方括号或颜色代码。")
        group = data["group_openid"]
        key = data["app_id"] + ":" + group + ":" + event
        fingerprint = json.dumps([subject, group, action, title], ensure_ascii=False)
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT fingerprint,reply FROM chat_title_events WHERE event=?", (key,)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise BindingError("重复消息的身份或内容不一致。")
                return web.json_response(json.loads(previous["reply"]))
            interval = 30 if role in ("admin", "owner") else 3600
            last = db.execute("SELECT changed FROM chat_title_cooldowns WHERE subject=?", (subject,)).fetchone()
            now = time.time()
            remaining = max(0, int(last[0] + interval - now + 0.999)) if last else 0
            if remaining:
                raise BindingError("头衔修改冷却中，还需等待 " + str(remaining) + " 秒。普通群员每小时一次，群主和管理员每30秒一次；设置与清除共用冷却。")
            db.execute("INSERT OR REPLACE INTO chat_titles VALUES(?,?,?)", (subject, group, title))
            db.execute("INSERT OR REPLACE INTO chat_title_cooldowns VALUES(?,?)", (subject, now))
            db.execute("INSERT INTO chat_title_outbox(subject,group_id,title,role,changed) VALUES(?,?,?,?,?)", (subject, group, title, role, now))
            reply = {"title": title, "cooldown_seconds": interval}
            db.execute("INSERT INTO chat_title_events VALUES(?,?,?)", (key, fingerprint, json.dumps(reply)))
        return web.json_response(reply)

    app.router.add_post("/v1/chat/title", change)

    async def mirror_context(app):
        defaults = cfg.get("title_mysql_defaults")
        if not defaults:
            yield
            return
        async def worker():
            initialized = False
            while True:
                try:
                    if not initialized:
                        await mysql_run(Path(defaults), MYSQL_SCHEMA)
                        initialized = True
                    with store.connect() as db:
                        rows = [dict(r) for r in db.execute("SELECT * FROM chat_title_outbox WHERE synced=0 ORDER BY id LIMIT 50")]
                    if rows:
                        await mysql_run(Path(defaults), "\n".join(mirror_sql(r) for r in rows))
                        with store.connect() as db:
                            db.executemany("UPDATE chat_title_outbox SET synced=1 WHERE id=?", [(r["id"],) for r in rows])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logging.getLogger(__name__).warning("Title MySQL mirror pending (%s)", type(exc).__name__)
                    await asyncio.sleep(15)
                await asyncio.sleep(1)
        task = asyncio.create_task(worker())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    app.cleanup_ctx.append(mirror_context)

"""Authenticated, audited QQ commands routed to specific Minecraft processes."""
import time
import re

from aiohttp import web


def register(app, cfg, store, identity):
    bridge = cfg.get("chat_bridge", {})
    targets = bridge.get("command_targets", [])
    if not isinstance(targets, list) or any(
        not isinstance(target, str) or target not in [*bridge.get("servers", []), "proxy"] for target in targets
    ) or len(targets) != len(set(targets)):
        raise ValueError("command_targets must name configured backends or proxy")
    roles = cfg.get("bot_roles", {})
    owners, admins = roles.get("owners", []), roles.get("admins", [])
    if not isinstance(owners, list) or not isinstance(admins, list) or any(
        not isinstance(member, str) or not member for member in [*owners, *admins]
    ) or set(owners) & set(admins):
        raise ValueError("bot_roles owners/admins must be distinct member_openid lists")
    with store.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS remote_command_jobs (
            event TEXT NOT NULL, server TEXT NOT NULL, subject TEXT NOT NULL,
            mode TEXT NOT NULL, game_uuid TEXT NOT NULL, game_name TEXT NOT NULL,
            command TEXT NOT NULL, created REAL NOT NULL, state TEXT NOT NULL,
            result TEXT NOT NULL DEFAULT '', PRIMARY KEY(event,server))""")
        db.execute("""CREATE TABLE IF NOT EXISTS remote_command_audit (
            event TEXT NOT NULL, server TEXT NOT NULL, subject TEXT NOT NULL,
            mode TEXT NOT NULL, command TEXT NOT NULL, submitted REAL NOT NULL,
            PRIMARY KEY(event,server))""")
        db.execute("""CREATE TABLE IF NOT EXISTS bot_role_admins (
            member_openid TEXT PRIMARY KEY, active INTEGER NOT NULL,
            changed_by TEXT NOT NULL, changed REAL NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS bot_role_events (
            event TEXT PRIMARY KEY, owner TEXT NOT NULL, target TEXT NOT NULL,
            action TEXT NOT NULL, changed REAL NOT NULL)""")

    def is_admin(db, member):
        row = db.execute("SELECT active FROM bot_role_admins WHERE member_openid=?", (member,)).fetchone()
        return bool(row["active"]) if row else member in admins

    async def result_for(subject, event):
        with store.connect() as db:
            rows = db.execute("SELECT server,state,result FROM remote_command_jobs WHERE event=? AND subject=? ORDER BY server",
                              (event, subject)).fetchall()
        if not rows:
            return web.json_response({"state": "missing"})
        return web.json_response({"state": "done" if all(row["state"] == "done" for row in rows) else "running",
                                  "results": [dict(row) for row in rows]})

    async def submit(request):
        data = await request.json()
        subject = identity(data)
        event, command, target, mode = (data.get(key) for key in ("event_id", "command", "target", "mode"))
        if not isinstance(event, str) or not 1 <= len(event) <= 256:
            raise ValueError("event")
        if not isinstance(command, str) or not 1 <= len(command) <= 2000 or not command.startswith("/") or any(
            char in command for char in "\r\n\0"
        ):
            raise ValueError("command")
        if mode not in ("player", "console") or target not in [*targets, "ALL"]:
            raise ValueError("target/mode")
        member = data["member_openid"]
        selected = targets if target == "ALL" else [target]
        with store.connect() as db:
            if mode == "console" and member not in owners and not is_admin(db, member):
                return web.json_response({"error": "只有 Bot 主人或管理可使用 /大发命令。"}, status=403)
            if mode == "console" and member not in owners and target in ("proxy", "ALL"):
                return web.json_response({"error": "Bot 管理只能指定单个子服；proxy 和 ALL 仅限主人。"}, status=403)
            binding = db.execute("SELECT game_uuid,game_name FROM bindings WHERE subject=?", (subject,)).fetchone() if mode == "player" else None
            if mode == "player" and not binding:
                return web.json_response({"error": "请先绑定游戏账号。"}, status=409)
            game_uuid, game_name = (binding["game_uuid"], binding["game_name"]) if binding else ("", "")
            db.execute("DELETE FROM remote_command_jobs WHERE created<?", (time.time() - 86400,))
            for server in selected:
                row = db.execute("SELECT subject,mode,game_uuid,command FROM remote_command_jobs WHERE event=? AND server=?", (event, server)).fetchone()
                if row and (row["subject"], row["mode"], row["game_uuid"], row["command"]) != (subject, mode, game_uuid, command):
                    raise web.HTTPConflict()
                if not row:
                    db.execute("INSERT INTO remote_command_jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (event, server, subject, mode, game_uuid, game_name, command, time.time(), "pending", ""))
                    db.execute("INSERT INTO remote_command_audit VALUES (?,?,?,?,?,?)",
                               (event, server, subject, mode, command, time.time()))
        return await result_for(subject, event)

    async def poll(request):
        server = (await request.json()).get("server")
        if server not in targets:
            raise web.HTTPForbidden()
        with store.connect() as db:
            rows = db.execute("SELECT event,game_uuid,game_name,command,mode FROM remote_command_jobs WHERE server=? AND state='pending' AND created>? ORDER BY created LIMIT 10",
                              (server, time.time()-120)).fetchall()
            db.executemany("UPDATE remote_command_jobs SET state='running' WHERE event=? AND server=? AND state='pending'",
                           [(row["event"], server) for row in rows])
        return web.json_response({"commands": [dict(row) for row in rows]})

    async def complete(request):
        data = await request.json()
        if data.get("server") not in targets or not isinstance(data.get("event"), str) or not isinstance(data.get("result"), str) or len(data["result"]) > 2000:
            raise ValueError("result")
        with store.connect() as db:
            db.execute("UPDATE remote_command_jobs SET state='done',result=? WHERE event=? AND server=? AND state='running'",
                       (data["result"], data["event"], data["server"]))
        return web.json_response({"ok": True})

    async def result(request):
        data = await request.json()
        return await result_for(identity(data), data["event_id"])

    async def admin(request):
        data = await request.json()
        subject = identity(data)
        owner = data["member_openid"]
        if owner not in owners:
            return web.json_response({"error": "只有 Bot 主人可设置或取缔管理。"}, status=403)
        target, action, event = (data.get(key) for key in ("target_member_openid", "action", "event_id"))
        if not isinstance(target, str) or not re.fullmatch(r"[A-Fa-f0-9]{32}", target) or target in owners:
            raise ValueError("target_member_openid")
        if action not in ("add", "remove") or not isinstance(event, str) or not 1 <= len(event) <= 256:
            raise ValueError("action/event")
        with store.connect() as db:
            previous = db.execute("SELECT owner,target,action FROM bot_role_events WHERE event=?", (event,)).fetchone()
            if previous and tuple(previous) != (subject, target, action):
                raise web.HTTPConflict()
            if not previous:
                db.execute("INSERT INTO bot_role_events VALUES (?,?,?,?,?)", (event, subject, target, action, time.time()))
                db.execute("""INSERT INTO bot_role_admins VALUES (?,?,?,?)
                    ON CONFLICT(member_openid) DO UPDATE SET active=excluded.active,
                    changed_by=excluded.changed_by,changed=excluded.changed""",
                    (target, int(action == "add"), subject, time.time()))
        return web.json_response({"ok": True, "action": action})

    async def role(request):
        data = await request.json()
        identity(data)
        member = data["member_openid"]
        with store.connect() as db:
            current = "owner" if member in owners else "admin" if is_admin(db, member) else "member"
        return web.json_response({"role": current})

    app.router.add_post("/v1/command/submit", submit)
    app.router.add_post("/v1/command/poll", poll)
    app.router.add_post("/v1/command/complete", complete)
    app.router.add_post("/v1/command/result", result)
    app.router.add_post("/v1/command/admin", admin)
    app.router.add_post("/v1/command/role", role)

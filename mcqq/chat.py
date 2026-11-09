"""Authenticated, bounded store-and-forward queues for the single local proxy."""
import json
import time
import uuid

from aiohttp import web


def register(app, cfg, store, identity, resolve_media):
    allowed = cfg.get("allowed_groups", [])
    outbound = cfg.get("chat_bridge", {}).get("outbound_groups", allowed)
    if not isinstance(outbound, list) or any(g not in allowed for g in outbound):
        raise ValueError("outbound_groups must be a subset of allowed_groups")
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS chat_queue (
                id INTEGER PRIMARY KEY, direction TEXT NOT NULL, event TEXT UNIQUE NOT NULL,
                payload TEXT NOT NULL, created REAL NOT NULL, ack INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS chat_names (
                subject TEXT NOT NULL, group_id TEXT NOT NULL, nickname TEXT NOT NULL,
                PRIMARY KEY(subject, group_id)
            );
            CREATE TABLE IF NOT EXISTS chat_sender_log (
                event TEXT PRIMARY KEY, group_id TEXT NOT NULL, member_openid TEXT NOT NULL,
                nickname TEXT NOT NULL, received REAL NOT NULL
            );
        """)

    def groups():
        return cfg.get("allowed_groups", [])

    def inbound_groups():
        return cfg.get("chat_bridge", {}).get("inbound_groups", groups())

    def outbound_groups():
        return cfg.get("chat_bridge", {}).get("outbound_groups", groups())

    def servers():
        return cfg.get("chat_bridge", {}).get("servers", [])

    def enqueue(db, direction, event, payload):
        db.execute("DELETE FROM chat_queue WHERE created<?", (time.time() - 86400,))
        if db.execute("SELECT count(*) FROM chat_queue WHERE ack=0 AND created>?", (time.time()-120,)).fetchone()[0] >= 2048:
            raise web.HTTPServiceUnavailable()
        db.execute("INSERT OR IGNORE INTO chat_queue(direction,event,payload,created) VALUES(?,?,?,?)",
                   (direction, direction + ":" + event, json.dumps(payload), time.time()))

    async def status(request):
        return web.json_response({"servers": servers(), "mode": "said-only", "groups": len(groups())})

    async def send(request):
        data = await request.json()
        text = data["text"]
        event = data["event_id"]
        raw_media = data.get("media", []) if request.path == "/v1/chat/from-qq" else []
        if not isinstance(text, str) or (not text.strip() and not raw_media) or len(text) > 2000:
            raise ValueError("text")
        if not isinstance(event, str) or not 1 <= len(event) <= 256:
            raise ValueError("event")
        # Preserve spaces and symbols; reject line/control injection into game chat.
        if any(ord(c) < 32 and c != "\t" for c in text):
            raise ValueError("control characters")
        attachments = []
        if request.path == "/v1/chat/from-qq":
            identity(data)
            if data["group_openid"] not in inbound_groups():
                raise web.HTTPForbidden()
            attachments = await resolve_media(raw_media)
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if request.path == "/v1/chat/from-qq":
                subject = identity(data)
                nickname = data.get("nickname", "")
                role = data.get("role", "member")
                if role not in ("member", "admin", "owner"):
                    raise ValueError("role")
                if not isinstance(nickname, str) or len(nickname) > 128:
                    raise ValueError("nickname")
                if nickname:
                    db.execute("INSERT OR REPLACE INTO chat_names VALUES(?,?,?)", (subject, data["group_openid"], nickname))
                cached_name = db.execute("SELECT nickname FROM chat_names WHERE subject=? AND group_id=?", (subject, data["group_openid"])).fetchone()
                db.execute("INSERT OR IGNORE INTO chat_sender_log VALUES(?,?,?,?,?)", (data["app_id"]+":"+data["group_openid"]+":"+event, data["group_openid"], data["member_openid"], nickname, time.time()))
                binding = db.execute("SELECT * FROM bindings WHERE subject=?", (subject,)).fetchone()
                custom_title = db.execute("SELECT title FROM chat_titles WHERE subject=? AND group_id=?", (subject, data["group_openid"])).fetchone()
                payload = {"text": text, "source": "qq", "uuid": binding["game_uuid"] if binding else "",
                           "name": binding["game_name"] if binding else (nickname or (cached_name[0] if cached_name else "群友")),
                           "group_name": cfg.get("chat_bridge", {}).get("group_aliases", {}).get(data["group_openid"]) or str(data.get("group_name", ""))[:128] or data["group_openid"],
                           "qq_id": data["member_openid"], "role": role, "title": custom_title[0] if custom_title else None, "media": attachments}
                if not servers():
                    raise ValueError("bridge disabled")
                enqueue(db, "game", data["group_openid"] + ":" + event, payload)
            else:
                if data["server"] not in servers():
                    raise web.HTTPForbidden()
                player_uuid = str(uuid.UUID(data["uuid"]))
                name = data["name"]
                if not isinstance(name, str) or not 1 <= len(name) <= 32:
                    raise ValueError("name")
                binding = db.execute("SELECT subject FROM bindings WHERE game_uuid=?", (player_uuid,)).fetchone()
                target = data.get("group", "")
                if not isinstance(target, str) or (target and target not in outbound_groups()):
                    raise web.HTTPForbidden()
                for group in ([target] if target else outbound_groups()):
                    nick = db.execute("SELECT nickname FROM chat_names WHERE subject=? AND group_id=?",
                                      (binding["subject"], group)).fetchone() if binding else None
                    enqueue(db, "qq", group + ":" + event,
                            {"group": group, "text": "[游戏内]" + (nick[0] if nick else name) + ":" + text})
        return web.json_response({"ok": True})

    async def poll(request):
        direction = "game" if request.path.endswith("to-game") else "qq"
        with store.connect() as db:
            rows = db.execute("SELECT id,payload FROM chat_queue WHERE direction=? AND ack=0 AND created>? ORDER BY id LIMIT 50",
                              (direction, time.time()-120)).fetchall()
            snapshot = [{"group": r["group_id"], "member": r["subject"][len(cfg["app_id"])+1:], "title": r["title"]}
                        for r in db.execute("SELECT subject,group_id,title FROM chat_titles ORDER BY group_id,subject")
                        if r["group_id"] in groups() and r["subject"].startswith(cfg["app_id"] + ":")] if direction == "game" else []
        return web.json_response({"messages": [dict(id=r["id"], **json.loads(r["payload"])) for r in rows], "title_snapshot": snapshot})

    async def ack(request):
        ids = (await request.json())["ids"]
        if not isinstance(ids, list) or len(ids) > 50 or any(type(i) is not int for i in ids):
            raise ValueError("ids")
        direction = "game" if request.path.endswith("ack-game") else "qq"
        with store.connect() as db:
            db.executemany("UPDATE chat_queue SET ack=1 WHERE id=? AND direction=?", [(i, direction) for i in ids])
        return web.json_response({"ok": True})

    app.router.add_post("/v1/chat/status", status)
    app.router.add_post("/v1/chat/from-qq", send)
    app.router.add_post("/v1/chat/from-game", send)
    app.router.add_post("/v1/chat/to-game", poll)
    app.router.add_post("/v1/chat/to-qq", poll)
    app.router.add_post("/v1/chat/ack-game", ack)
    app.router.add_post("/v1/chat/ack-qq", ack)

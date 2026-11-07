import hashlib
import json
import sqlite3
import time
import secrets
from pathlib import Path
from contextlib import contextmanager


class BindingError(Exception):
    pass


class Store:
    def __init__(self, path, cooldown=60):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path, self.cooldown = str(path), cooldown
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS bindings (
                    subject TEXT PRIMARY KEY,
                    group_openid TEXT NOT NULL,
                    member_openid TEXT NOT NULL,
                    platform TEXT NOT NULL CHECK(platform IN ('java','bedrock')),
                    game_uuid TEXT NOT NULL UNIQUE,
                    game_name TEXT NOT NULL,
                    updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    reply TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY,
                    subject TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    old_uuid TEXT,
                    new_uuid TEXT NOT NULL,
                    changed REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS links (
                    subject TEXT PRIMARY KEY REFERENCES bindings(subject),
                    bedrock_uuid TEXT NOT NULL UNIQUE,
                    bedrock_name TEXT NOT NULL,
                    java_uuid TEXT NOT NULL UNIQUE,
                    java_name TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS challenges (
                    subject TEXT PRIMARY KEY,
                    code_hash TEXT NOT NULL UNIQUE,
                    bedrock_uuid TEXT NOT NULL,
                    bedrock_name TEXT NOT NULL,
                    java_uuid TEXT NOT NULL,
                    expires REAL NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def query(self, subject):
        with self.connect() as db:
            row = db.execute("SELECT * FROM bindings WHERE subject=?", (subject,)).fetchone()
            if not row:
                return None
            result = dict(row)
            link = db.execute("SELECT bedrock_name FROM links WHERE subject=?", (subject,)).fetchone()
            result["bedrock_name"] = link["bedrock_name"] if link else None
            return result

    def authorized(self, uuid, session_uuid=None):
        with self.connect() as db:
            row = db.execute("SELECT game_uuid FROM bindings WHERE game_uuid=?", (uuid,)).fetchone()
            if row:
                canonical = row["game_uuid"]
            else:
                row = db.execute("""SELECT l.java_uuid FROM links l JOIN bindings b ON b.subject=l.subject
                    WHERE l.bedrock_uuid=? AND b.game_uuid=l.java_uuid""", (uuid,)).fetchone()
                canonical = row["java_uuid"] if row else None
            return canonical is not None and (session_uuid is None or canonical == session_uuid)

    def link_for(self, uuid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM links WHERE bedrock_uuid=? OR java_uuid=?", (uuid, uuid)).fetchone()
            return dict(row) if row else None

    def request_link(self, subject, profile):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            primary = db.execute("SELECT * FROM bindings WHERE subject=?", (subject,)).fetchone()
            if not primary or primary["platform"] != "java":
                raise BindingError("请先 /绑定 Java 你的正版游戏名，再关联基岩账号。")
            owner = db.execute("SELECT subject FROM bindings WHERE game_uuid=?", (profile["uuid"],)).fetchone()
            link = db.execute("SELECT subject FROM links WHERE bedrock_uuid=?", (profile["uuid"],)).fetchone()
            if (owner and owner["subject"] != subject) or (link and link["subject"] != subject):
                raise BindingError("此基岩账号已绑定其他 QQ 身份。")
            code = secrets.token_hex(6).upper()
            db.execute("INSERT OR REPLACE INTO challenges VALUES (?,?,?,?,?,?)", (
                subject, hashlib.sha256(code.encode()).hexdigest(), profile["uuid"], profile["name"],
                primary["game_uuid"], now + 600))
            return {"code": code, "java_name": primary["game_name"], "bedrock_name": profile["name"]}

    def verify_link(self, code, actor_uuid):
        digest = hashlib.sha256(code.upper().encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute("SELECT * FROM challenges WHERE code_hash=?", (digest,)).fetchone()
            if not pending or pending["expires"] < time.time():
                raise BindingError("关联码无效或已过期，请在 QQ 群重新发起 /关联基岩。")
            primary = db.execute("SELECT * FROM bindings WHERE subject=?", (pending["subject"],)).fetchone()
            if not primary or primary["platform"] != "java" or actor_uuid != pending["java_uuid"] or primary["game_uuid"] != actor_uuid:
                raise BindingError("请使用绑定的 Java 正版账号验证；基岩登录不能替代 Java 身份验证。")
            occupied = db.execute("SELECT subject FROM bindings WHERE game_uuid=?", (pending["bedrock_uuid"],)).fetchone()
            owner = db.execute("SELECT subject FROM links WHERE bedrock_uuid=?", (pending["bedrock_uuid"],)).fetchone()
            if occupied or (owner and owner["subject"] != pending["subject"]):
                raise BindingError("此基岩账号已被其他绑定占用。")
            db.execute("INSERT OR REPLACE INTO links VALUES (?,?,?,?,?,?)", (
                pending["subject"], pending["bedrock_uuid"], pending["bedrock_name"],
                actor_uuid, primary["game_name"], time.time()))
            db.execute("DELETE FROM challenges WHERE subject=?", (pending["subject"],))
            db.execute("INSERT INTO audit(subject,event_id,old_uuid,new_uuid,changed) VALUES (?,?,?,?,?)", (
                pending["subject"], "link:" + digest, None, pending["bedrock_uuid"], time.time()))
            return {"java_name": primary["game_name"], "bedrock_name": pending["bedrock_name"]}

    def remove(self, payload, only_link=False):
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        subject = payload["app_id"] + ":" + payload["member_openid"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            event = db.execute("SELECT * FROM events WHERE event_id=?", (payload["event_id"],)).fetchone()
            if event:
                if event["fingerprint"] != fingerprint:
                    raise BindingError("消息标识冲突，请重新发送命令。")
                return json.loads(event["reply"])
            old = db.execute("SELECT * FROM bindings WHERE subject=?", (subject,)).fetchone()
            alias = db.execute("SELECT bedrock_name FROM links WHERE subject=?", (subject,)).fetchone()
            db.execute("DELETE FROM links WHERE subject=?", (subject,))
            db.execute("DELETE FROM challenges WHERE subject=?", (subject,))
            if not only_link:
                db.execute("DELETE FROM bindings WHERE subject=?", (subject,))
            result = {"removed": bool(alias) if only_link else bool(old), "only_link": only_link,
                      "name": old["game_name"] if old else None,
                      "bedrock_name": alias["bedrock_name"] if alias else None}
            now = time.time()
            db.execute("INSERT INTO events VALUES (?,?,?,?)", (payload["event_id"], fingerprint, json.dumps(result), now))
            if old:
                db.execute("INSERT INTO audit(subject,event_id,old_uuid,new_uuid,changed) VALUES (?,?,?,?,?)",
                           (subject, ("unlink:" if only_link else "unbind:") + payload["event_id"], old["game_uuid"], "", now))
            return result

    def bind(self, payload, profile):
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        subject = payload["app_id"] + ":" + payload["member_openid"]
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            event = db.execute("SELECT * FROM events WHERE event_id=?", (payload["event_id"],)).fetchone()
            if event:
                if event["fingerprint"] != fingerprint:
                    raise BindingError("消息标识冲突，请重新发送命令。")
                return json.loads(event["reply"])
            old = db.execute("SELECT * FROM bindings WHERE subject=?", (subject,)).fetchone()
            owner = db.execute("SELECT subject FROM bindings WHERE game_uuid=?", (profile["uuid"],)).fetchone()
            alias = db.execute("SELECT subject FROM links WHERE bedrock_uuid=?", (profile["uuid"],)).fetchone()
            if alias:
                raise BindingError("此基岩账号已有关联，请使用 Java 主账号；更换关联请发送 /关联基岩 新Xbox昵称。")
            if owner and owner["subject"] != subject:
                raise BindingError("此游戏账号已经被其他 QQ 账号绑定，请联系服主处理。")
            if old and old["game_uuid"] != profile["uuid"]:
                if payload["action"] != "rebind":
                    if old["platform"] == "java" and profile["platform"] == "bedrock":
                        raise BindingError("【已有 Java 主账号】想让基岩共用存档，请使用 /关联基岩 " + profile["name"] + "；Java 主账号会保留。")
                    raise BindingError("【已有主账号】更换主账号请用 /换绑Java 新名字 或 /换绑基岩 新Xbox昵称。若从基岩改为双端共通，先 /换绑Java 名字，再 /关联基岩 原Xbox昵称；共通后以 Java 存档为准。")
                if now - old["updated"] < self.cooldown:
                    raise BindingError("换绑过于频繁，请稍后再试。")
            elif not old and payload["action"] == "rebind":
                raise BindingError("你尚未绑定，请先使用 /绑定。")
            changed = not old or old["game_uuid"] != profile["uuid"]
            if changed:
                db.execute("DELETE FROM links WHERE subject=?", (subject,))
                db.execute("DELETE FROM challenges WHERE subject=?", (subject,))
            elif profile["platform"] == "java":
                db.execute("UPDATE links SET java_name=? WHERE subject=?", (profile["name"], subject))
            db.execute("""INSERT INTO bindings VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(subject) DO UPDATE SET group_openid=excluded.group_openid,
                platform=excluded.platform, game_uuid=excluded.game_uuid,
                game_name=excluded.game_name, updated=excluded.updated""",
                (subject, payload["group_openid"], payload["member_openid"], profile["platform"],
                 profile["uuid"], profile["name"], now if changed else old["updated"]))
            result = {"name": profile["name"], "platform": profile["platform"], "changed": changed,
                      "previous_name": old["game_name"] if old and changed else None}
            db.execute("INSERT INTO events VALUES (?,?,?,?)", (payload["event_id"], fingerprint, json.dumps(result), now))
            if changed:
                db.execute("INSERT INTO audit(subject,event_id,old_uuid,new_uuid,changed) VALUES (?,?,?,?,?)",
                           (subject, payload["event_id"], old["game_uuid"] if old else None, profile["uuid"], now))
            return result

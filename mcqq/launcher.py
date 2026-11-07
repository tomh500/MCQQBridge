"""Short-lived launcher pairing. Only trusted bot events can approve a challenge.

Public reverse proxy must expose ONLY challenge and status, never /complete or /v1/*.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import base64
import json
import subprocess
from collections import OrderedDict
from pathlib import Path
from contextlib import contextmanager

from aiohttp import web

PUBLIC_PATHS = frozenset(("/launcher/v1/challenge", "/launcher/v1/status"))

TTL = 600


def sign_receipt(cfg, code, member, number):
    path = Path(cfg["database"]).with_name("launcher-signing.pem")
    data = json.dumps({"state": "authorized", "code": code,
                       "member": member, "group": number,
                       "expires": int(time.time()) + TTL}, separators=(",", ":")).encode()
    # The private key never leaves the server. Only authenticated bot events call this.
    result = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(path)],
                            input=data, capture_output=True, check=True, timeout=5)
    enc = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    return "SG1." + enc(data) + "." + enc(result.stdout)


def groups(cfg):
    configured = cfg.get("launcher_groups")
    if configured is None:
        allowed = cfg.get("allowed_groups", [])
        return {allowed[0]: str(cfg["group_number"])} if len(allowed) == 1 and cfg.get("group_number") else {}
    return {str(k): str(v) for k, v in configured.items()
            if str(v).isdigit() and not str(k).isdigit() and str(k) in cfg.get("allowed_groups", [])}


class Challenges:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = str(path), clock
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS challenges (
                code TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, expires INTEGER NOT NULL,
                member TEXT, group_number TEXT, event_id TEXT UNIQUE)""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self):
        now = int(self.clock())
        with self.connect() as db:
            db.execute("DELETE FROM challenges WHERE expires<=?", (now,))
            if db.execute("SELECT count(*) FROM challenges").fetchone()[0] >= 4096:
                raise web.HTTPTooManyRequests()
            for _ in range(4):
                code, secret = secrets.token_hex(6).upper(), secrets.token_urlsafe(32)
                try:
                    db.execute("INSERT INTO challenges(code,secret_hash,expires) VALUES(?,?,?)",
                               (code, hashlib.sha256(secret.encode()).hexdigest(), now + TTL))
                    return {"code": code, "secret": secret, "expires": now + TTL}
                except sqlite3.IntegrityError:
                    continue
        raise web.HTTPServiceUnavailable()

    def status(self, code, secret):
        if not isinstance(code, str) or not re.fullmatch(r"[0-9A-F]{12}", code):
            raise web.HTTPBadRequest()
        if not isinstance(secret, str) or not 32 <= len(secret) <= 128:
            raise web.HTTPUnauthorized()
        with self.connect() as db:
            row = db.execute("SELECT secret_hash,expires,member,group_number FROM challenges WHERE code=?", (code,)).fetchone()
        if not row or not hmac.compare_digest(row[0], hashlib.sha256(secret.encode()).hexdigest()):
            raise web.HTTPUnauthorized()
        if row[1] <= self.clock():
            return {"state": "expired", "code": code}
        if not row[2]:
            return {"state": "pending", "code": code}
        return {"state": "authorized", "code": code, "expires": row[1], "member": row[2], "group": row[3]}

    def complete(self, code, member, group_number, event_id):
        if not isinstance(code, str) or not re.fullmatch(r"[0-9A-F]{12}", code):
            raise web.HTTPBadRequest()
        with self.connect() as db:
            try:
                changed = db.execute("""UPDATE challenges SET member=?,group_number=?,event_id=?
                    WHERE code=? AND expires>? AND member IS NULL""",
                    (member, group_number, event_id, code, int(self.clock()))).rowcount
            except sqlite3.IntegrityError:
                changed = 0
            return bool(changed)


def register(app, cfg):
    store = Challenges(Path(cfg["database"]).with_name("launcher-auth.sqlite"))
    limits = OrderedDict()

    def limit(request, action):
        # Do not trust caller-supplied X-Forwarded-For. Proxy should also rate-limit.
        key = (request.remote or "unknown", action)
        now = time.monotonic()
        start, count = limits.get(key, (now, 0))
        if now - start >= 60:
            start, count = now, 0
        if count >= (12 if action == "create" else 90):
            raise web.HTTPTooManyRequests()
        limits[key] = (start, count + 1)
        limits.move_to_end(key)
        while len(limits) > 4096:
            limits.popitem(last=False)

    async def challenge(request):
        limit(request, "create")
        if not groups(cfg):
            raise web.HTTPServiceUnavailable(text="Launcher group not configured")
        response = web.json_response(store.create())
        response.headers["Cache-Control"] = "no-store"
        return response

    async def status(request):
        limit(request, "status")
        data = await request.json()
        if not isinstance(data, dict):
            raise web.HTTPBadRequest()
        response = web.json_response(store.status(data.get("code"), data.get("secret")))
        response.headers["Cache-Control"] = "no-store"
        return response

    async def complete(request):
        # Existing service middleware requires bot_token on this private route.
        data = await request.json()
        if not isinstance(data, dict):
            raise web.HTTPBadRequest()
        number = groups(cfg).get(data.get("group_openid"))
        if not number or data.get("app_id") != cfg["app_id"]:
            raise web.HTTPForbidden()
        for key in ("member_openid", "event_id"):
            if not isinstance(data.get(key), str) or not 1 <= len(data[key]) <= 256:
                raise web.HTTPBadRequest()
        accepted = store.complete(data.get("code"), data["member_openid"], number, data["event_id"])
        return web.json_response({"accepted": accepted})

    app.router.add_post("/launcher/v1/challenge", challenge)
    app.router.add_post("/launcher/v1/status", status)
    app.router.add_post("/launcher/v1/complete", complete)


async def reply(bot, message):
    """Return None for unrelated messages, before ordinary binding command parsing."""
    content = re.sub(r"<@!?[^>]+>", "", message.content or "").strip()
    if not content.startswith("/引导验证"):
        return None
    match = re.fullmatch(r"/引导验证\s+([0-9A-Fa-f]{12}|[0-9A-Fa-f]{32})", content)
    if not match:
        return "口令格式无效，请复制引导程序显示的完整验证口令。"
    group = str(getattr(message, "group_openid", "") or "")
    author = getattr(message, "author", None)
    member = str(getattr(author, "member_openid", "") or "")
    event = str(getattr(message, "id", "") or "")
    if group not in groups(bot.settings) or not member or not event:
        return "请使用本人QQ账号在指定群内 @机器人发送验证口令。"
    if len(match[1]) == 32:
        try:
            receipt = sign_receipt(bot.settings, match[1].upper(), member, groups(bot.settings)[group])
        except (OSError, subprocess.SubprocessError):
            return "签名服务不可用，请联系服务器管理员。"
        return "身份验证通过。请复制下列回执并粘贴至引导程序，有效期为10分钟：\n" + receipt
    data = await bot.call_service("/launcher/v1/complete", {
        "app_id": bot.settings["app_id"], "group_openid": group,
        "member_openid": member, "event_id": event, "code": match[1].upper()})
    if data.get("accepted"):
        return "群身份验证通过。请返回引导程序。游戏白名单状态可通过 /我的绑定 查询。"
    return "口令已失效，请重新生成。"

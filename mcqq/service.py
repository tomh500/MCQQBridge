import asyncio
import hmac
import logging
import uuid

import aiohttp
from aiohttp import web

from .config import load
from .profiles import resolve
from .store import BindingError, Store
from . import launcher

log = logging.getLogger(__name__)
SESSION = web.AppKey("session", aiohttp.ClientSession)


def create_app(cfg, resolver=resolve):
    store = Store(cfg["database"], cfg.get("rebind_cooldown_seconds", 60))

    @web.middleware
    async def auth(request, handler):
        if request.path == "/healthz":
            return await handler(request)
        if request.path not in launcher.PUBLIC_PATHS:
            key = "proxy_token" if request.path in ("/v1/authorize", "/v1/link", "/v1/verify", "/v1/status", "/v1/chat/from-game", "/v1/chat/to-game", "/v1/chat/ack-game") else "bot_token"
            if not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + cfg[key]):
                raise web.HTTPUnauthorized()
        try:
            return await handler(request)
        except BindingError as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except (ValueError, KeyError, TypeError):
            return web.json_response({"error": "请求参数无效。"}, status=400)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return web.json_response({"error": "游戏账号服务连接失败，请稍后重试。"}, status=503)

    app = web.Application(middlewares=[auth], client_max_size=65536)

    async def session_context(app):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
            app[SESSION] = session
            yield
    app.cleanup_ctx.append(session_context)

    async def health(request):
        store.authorized("healthcheck")
        return web.json_response({"status": "ok"})

    async def status(request):
        with store.connect() as db:
            count = db.execute("SELECT count(*) FROM bindings").fetchone()[0]
        return web.json_response({"allowed_group_count": len(cfg.get("allowed_groups", [])), "binding_count": count})

    def identity(data):
        if not isinstance(data, dict):
            raise ValueError("body")
        for key in ("app_id", "group_openid", "member_openid"):
            if not isinstance(data.get(key), str) or not 1 <= len(data[key]) <= 128:
                raise ValueError(key)
        if data["app_id"] != cfg["app_id"]:
            raise web.HTTPForbidden()
        if data["group_openid"] not in cfg.get("allowed_groups", []):
            raise BindingError("本群尚未获准绑定，请让服主配置 /本群ID 返回的 group_openid。")
        return data["app_id"] + ":" + data["member_openid"]

    async def bind(request):
        data = await request.json()
        identity(data)
        if data.get("action") not in ("bind", "rebind") or not isinstance(data.get("event_id"), str) or not 1 <= len(data["event_id"]) <= 256:
            raise ValueError("action/event_id")
        if not isinstance(data.get("name"), str) or len(data["name"]) > 32:
            raise ValueError("name")
        # Only authenticated bot traffic can supply the QQ event identity.
        profile = await resolver(request.app[SESSION], data["platform"], data["name"])
        return web.json_response(await asyncio.to_thread(store.bind, data, profile))

    async def query(request):
        data = await request.json()
        result = await asyncio.to_thread(store.query, identity(data))
        return web.json_response({"binding": {"name": result["game_name"], "platform": result["platform"],
                                               "bedrock_name": result["bedrock_name"]} if result else None})

    async def remove(request):
        data = await request.json()
        identity(data)
        if not isinstance(data.get("event_id"), str) or not 1 <= len(data["event_id"]) <= 256:
            raise ValueError("event_id")
        if data.get("action") not in ("unbind", "unlink") or data.get("confirmed") is not True:
            raise ValueError("confirmation")
        result = await asyncio.to_thread(store.remove, data, data["action"] == "unlink")
        return web.json_response(result)

    async def authorize(request):
        game_uuid = str(uuid.UUID(request.query["uuid"]))
        session_uuid = str(uuid.UUID(request.query["session_uuid"]))
        allowed = await asyncio.to_thread(store.authorized, game_uuid, session_uuid)
        return web.Response(text="allow" if allowed else "deny", content_type="text/plain")

    async def request_link(request):
        data = await request.json()
        subject = identity(data)
        if not isinstance(data.get("name"), str) or len(data["name"]) > 32:
            raise ValueError("name")
        profile = await resolver(request.app[SESSION], "bedrock", data["name"])
        return web.json_response(await asyncio.to_thread(store.request_link, subject, profile))

    async def link(request):
        game_uuid = str(uuid.UUID(request.query["uuid"]))
        result = await asyncio.to_thread(store.link_for, game_uuid)
        body = "none" if not result else "\n".join((result["java_uuid"], result["java_name"], result["bedrock_uuid"]))
        return web.Response(text=body, content_type="text/plain")

    async def verify(request):
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("body")
        if data.get("java_authenticated") is not True:
            raise BindingError("请使用 Java 正版客户端验证。")
        actor = str(uuid.UUID(data["uuid"]))
        if not isinstance(data.get("code"), str) or len(data["code"]) != 12:
            raise ValueError("code")
        return web.json_response(await asyncio.to_thread(store.verify_link, data["code"], actor))

    app.router.add_get("/healthz", health)
    app.router.add_get("/v1/status", status)
    app.router.add_post("/v1/bind", bind)
    app.router.add_post("/v1/query", query)
    app.router.add_post("/v1/remove", remove)
    app.router.add_get("/v1/authorize", authorize)
    app.router.add_post("/v1/request-link", request_link)
    app.router.add_get("/v1/link", link)
    app.router.add_post("/v1/verify", verify)
    launcher.register(app, cfg)
    from . import chat
    from . import media
    media_resolver, _, _ = media.register(app, cfg, store)
    chat.register(app, cfg, store, identity, lambda raw: media_resolver(app[SESSION], raw))
    from . import titles
    titles.register(app, cfg, store, identity)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    settings = load()
    web.run_app(create_app(settings), host=settings["listen_host"], port=settings["listen_port"], access_log=None)

"""QQ image/sticker extraction and one-hour, public-image-only fallback hosting."""
import asyncio
import json
import re
import secrets
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit, urljoin

import aiohttp
from aiohttp import web

QQ_DOMAINS = ("qq.com", "qq.com.cn", "qpic.cn", "gtimg.cn", "gtimg.com", "idqqimg.com", "qlogo.cn")
MAX_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 8
TTL = 3600


def qq_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("media URL")
    if value.startswith("//"):
        value = "https:" + value
    elif "://" not in value:
        value = "https://" + value
    url = urlsplit(value)
    host = (url.hostname or "").lower()
    if url.scheme not in ("http", "https") or url.username or url.password or url.port not in (None, 80, 443):
        raise ValueError("media URL")
    if not any(host == domain or host.endswith("." + domain) for domain in QQ_DOMAINS):
        raise ValueError("untrusted media host")
    return value


def extract(data):
    """Preserve images even when SDK models drop rich-message fields or content is empty."""
    items, texts, seen = [], [], set()
    missing_face = False

    def add(url, kind):
        try:
            url = qq_url(url)
        except (ValueError, TypeError):
            return
        if url not in seen and len(items) < MAX_ITEMS:
            seen.add(url)
            items.append({"url": url, "kind": kind})

    def visit(node, depth=0):
        nonlocal missing_face
        if depth > 4 or not isinstance(node, dict):
            return
        content = node.get("content") or ""
        if isinstance(content, str):
            face = None
            if content.lstrip().startswith("{"):
                try:
                    candidate = json.loads(content)
                    if isinstance(candidate, dict) and "faceType" in candidate and "faceId" in candidate:
                        face = candidate
                except (ValueError, TypeError):
                    pass
            # QQ may serialize rich faces as a diagnostic-looking angle-bracket
            # token rather than JSON, including inside otherwise normal text.
            def strip_face(match):
                nonlocal missing_face
                missing_face = True
                return ""
            content = re.sub(r'<faceType\s*=\s*[^<>]*?faceId\s*=\s*[^<>]*?>', strip_face, content, flags=re.I)
            if face:
                # QQ's standard face IDs have an official public GIF counterpart.
                face_id = str(face.get("faceId", ""))
                if str(face.get("faceType")) == "1" and re.fullmatch(r"\d{1,4}", face_id):
                    add("https://qzonestyle.gtimg.cn/qzone/em/e" + face_id + ".gif", "sticker")
                else:
                    missing_face = True
            elif content.strip() not in ("", "[图片]", "[表情包]"):
                texts.append(content)
        for attachment in (node.get("attachments") or [])[:MAX_ITEMS]:
            if not isinstance(attachment, dict):
                continue
            mime = str(attachment.get("content_type", "")).lower()
            filename = str(attachment.get("filename", "")).lower()
            sticker = bool(attachment.get("is_sticker")) or "sticker" in mime or "emoji" in mime or mime == "image/gif" or filename.endswith(".gif")
            if mime.startswith("image/") or sticker or filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                add(attachment.get("url", ""), "sticker" if sticker else "image")
        for child in (node.get("msg_elements") or [])[:MAX_ITEMS]:
            visit(child, depth + 1)
    visit(data)
    if missing_face and not items:
        texts.append("[表情包：暂无图片链接]")
    return {"text": " ".join(dict.fromkeys(texts)).strip(), "media": items}


def image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png", ".png"
    if data.startswith(b"\xff\xd8\xff"): return "image/jpeg", ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")): return "image/gif", ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP": return "image/webp", ".webp"
    raise ValueError("not a supported image")


async def fetch(session, source, *, fallback=False, full=False):
    return await asyncio.wait_for(fetch_checked(session, source, fallback=fallback, full=full), 8)


async def fetch_checked(session, source, *, fallback=False, full=False):
    url = qq_url(source)
    headers = {"Referer": "https://im.qq.com/", "User-Agent": "QQBot-MC-Media/1.0"} if fallback else {}
    for _ in range(4):
        async with session.get(url, headers=headers, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=8)) as response:
            if response.status in (301, 302, 303, 307, 308):
                url = qq_url(urljoin(url, response.headers.get("Location", "")))
                continue
            if response.status != 200:
                raise ValueError("image not public")
            if response.content_length and response.content_length > MAX_BYTES:
                raise ValueError("image exceeds 8 MiB")
            data = await response.content.readexactly(16)
            mime, extension = image_type(data)
            if full:
                async for block in response.content.iter_chunked(65536):
                    data += block
                    if len(data) > MAX_BYTES:
                        raise ValueError("image exceeds 8 MiB")
            return url, mime, extension, data
    raise ValueError("too many redirects")


def register(app, cfg, store):
    directory = Path(cfg["database"]).parent / "media-temp"
    directory.mkdir(parents=True, exist_ok=True)
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS chat_media (name TEXT PRIMARY KEY, mime TEXT NOT NULL, expires REAL NOT NULL)")
    options = cfg.get("media", {})
    public_base = options.get("public_base_url", "").rstrip("/")

    async def resolve(session, raw):
        if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
            raise ValueError("media list")
        validated = []
        for item in raw:
            if not isinstance(item, dict) or item.get("kind") not in ("image", "sticker"):
                raise ValueError("media kind")
            validated.append((item["kind"], qq_url(item["url"])))
        async def one(kind, source):
            try:
                url, _, _, _ = await fetch(session, source)
                return {"kind": kind, "url": url}
            except (ValueError, aiohttp.ClientError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                try:
                    if not public_base:
                        raise ValueError("fallback hosting disabled")
                    _, mime, extension, data = await fetch(session, source, fallback=True, full=True)
                    name = secrets.token_hex(16) + extension
                    (directory/name).write_bytes(data)
                    with store.connect() as db:
                        db.execute("INSERT INTO chat_media VALUES(?,?,?)", (name, mime, time.time()+TTL))
                    return {"kind": kind, "url": public_base + "/" + name}
                except (ValueError, aiohttp.ClientError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                    return {"kind": kind, "url": ""}
        return await asyncio.gather(*(one(kind, source) for kind,source in validated))

    def cleanup():
        with store.connect() as db:
            for row in db.execute("SELECT name FROM chat_media WHERE expires<=?", (time.time(),)).fetchall():
                if re.fullmatch(r"[a-f0-9]{32}\.(png|jpg|gif|webp)", row[0]):
                    (directory/row[0]).unlink(missing_ok=True)
            db.execute("DELETE FROM chat_media WHERE expires<=?", (time.time(),))

    async def serve(request):
        name = request.match_info["name"]
        if not re.fullmatch(r"[a-f0-9]{32}\.(png|jpg|gif|webp)", name):
            raise web.HTTPNotFound()
        with store.connect() as db:
            row = db.execute("SELECT mime,expires FROM chat_media WHERE name=?", (name,)).fetchone()
        if not row or row["expires"] <= time.time() or not (directory/name).is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(directory/name, headers={"Content-Type": row["mime"], "Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})

    # This separate listener exposes only random, expiring image URLs, never the authenticated API.
    async def lifecycle(app):
        runner = None
        cleanup()
        async def janitor():
            while True:
                await asyncio.sleep(TTL)
                cleanup()
        task = asyncio.create_task(janitor())
        try:
            if options.get("port"):
                public = web.Application()
                public.router.add_get("/mcqq-media/{name}", serve)
                runner = web.AppRunner(public, access_log=None)
                await runner.setup()
                listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                listener.bind(("::", int(options["port"])))
                listener.listen(128)
                await web.SockSite(runner, listener).start()
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if runner: await runner.cleanup()
    app.cleanup_ctx.append(lifecycle)
    return resolve, serve, cleanup

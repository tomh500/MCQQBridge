"""Publish generated images and local portraits to QQ's Markdown material library."""
import asyncio
import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from botpy.http import Route


class PortraitMaterials:
    def __init__(self, api, directory):
        self.api = api
        self.directory = Path(directory)
        self.lock = asyncio.Lock()

    async def resolve(self, source):
        match = re.search(r"/(\d+)_crt_[^/]+\.(jpg|jpeg|png|webp|gif)$", urlparse(source).path, re.I)
        if not match:
            raise ValueError("unsupported portrait URL")
        asset = self.directory / (match.group(1) + "." + match.group(2).lower())
        data = await asyncio.to_thread(asset.read_bytes)
        digest = hashlib.sha256(data).hexdigest()
        ext = match.group(2).lower()
        content_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}[ext]
        return await self.publish(data, "mcqq-waifu-" + digest + "." + ext, content_type)

    async def publish(self, data, filename, content_type):
        if not data or len(data) > 10_000_000:
            raise ValueError("invalid image size")
        async with self.lock:
            cursor = ""
            while True:
                query = {"cursor": cursor} if cursor else {}
                page = await self.api._http.request(Route("GET", "/v2/media-images"), params=query)
                for image in page.get("images", []):
                    if image.get("file_name") == filename and str(image.get("url", "")).startswith("qqbot-media://image/v1/"):
                        return image["url"]
                cursor = page.get("next_cursor") or ""
                if not cursor:
                    break
            info = await self.api._http.request(Route("POST", "/v2/media-images/prepare"), json={
                "file_name": filename, "file_size": len(data), "content_type": content_type,
                "md5": hashlib.md5(data).hexdigest(), "sha1": hashlib.sha1(data).hexdigest()})
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as session:
                async with session.put(info["presigned_url"], data=data, headers={"Content-Type": content_type}) as response:
                    response.raise_for_status()
                    etag = response.headers.get("ETag", "").strip('"')
            if etag.lower() != hashlib.md5(data).hexdigest():
                raise ValueError("image upload checksum mismatch")
            done = await self.api._http.request(Route("POST", "/v2/media-images/complete"), json={"upload_id": info["upload_id"], "md5": etag})
            url = done.get("url", "")
            if not url.startswith("qqbot-media://image/v1/"):
                raise ValueError("invalid image material reference")
            return url

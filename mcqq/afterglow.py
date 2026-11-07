"""Private-only adapter for the existing Afterglow OpenAI-compatible endpoint."""
import asyncio
import hashlib
import json
import logging
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)


class Afterglow:
    def __init__(self, connection_path):
        self.path = Path(connection_path)
        self.locks = {}
        self.history = {}

    async def respond(self, user_openid, text):
        try:
            cfg = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return "Afterglow 私聊接入尚未配置，请联系管理员。"
        if user_openid not in cfg.get("official_users", []):
            return "此私聊功能仅向已授权用户开放。"
        if not cfg.get("ready"):
            return "Afterglow 暂未就绪。"
        if text in ("/续温状态", "续温状态"):
            return "Afterglow 已就绪。"
        if text.startswith(("/续温 ", "续温 ")):
            text = text.split(maxsplit=1)[1]
        if not text.strip():
            return None
        lock = self.locks.setdefault(user_openid, asyncio.Lock())
        async with lock:
            history = self.history.setdefault(user_openid, [])
            # Existing AstrBot origin can be configured per owner to retain its conversation ID.
            origin = cfg.get("origins", {}).get(user_openid)
            session = ("astrbot:" + hashlib.sha256(origin.encode()).hexdigest()[:24]
                       if origin else "qqbot:" + hashlib.sha256(user_openid.encode()).hexdigest()[:24])
            request = {"model": "afterglow", "stream": False, "conversation_id": session,
                       "messages": [*history, {"role": "user", "content": text}]}
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as client:
                    async with client.post(cfg["base_url"].rstrip("/") + "/v1/chat/completions",
                                           headers={"Authorization": "Bearer " + cfg["api_key"]}, json=request) as response:
                        if response.status != 200:
                            return "Afterglow 暂时无法回复，请稍后重试。"
                        data = await response.json()
                if data.get("policy", {}).get("should_reply") is False:
                    return None
                reply = data["choices"][0]["message"]["content"]
                if not isinstance(reply, str) or not reply.strip() or reply.strip() == "[silent]":
                    return None
                history.extend([{"role": "user", "content": text}, {"role": "assistant", "content": reply}])
                self.history[user_openid] = history[-20:]
                return reply
            except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, IndexError, TypeError, ValueError):
                log.warning("Afterglow private request failed")
                return "Afterglow 连接失败，请稍后重试。"

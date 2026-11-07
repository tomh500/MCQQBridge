import asyncio
import logging
import json
import time
import re
from collections import OrderedDict
from pathlib import Path

import aiohttp
import botpy

from .afterglow import Afterglow
from .commands import HELP, parse
from .config import load
from . import launcher
from botpy.message import GroupMessage
from . import media


class RichGroupMessage(GroupMessage):
    __slots__ = ("raw_data",)

log = logging.getLogger(__name__)


def binding_summary(binding):
    if not binding:
        return "【尚未绑定】\nJava 玩家：/绑定Java 游戏名\n基岩玩家：/绑定基岩 Xbox昵称\n双端共通：先绑定Java，再关联基岩。"
    if binding["platform"] == "java":
        result = "【你的入服账号】\nJava 主账号：" + binding["name"] + "\n"
        if binding.get("bedrock_name"):
            result += "基岩关联：" + binding["bedrock_name"] + "\n✓ 两端共用 Java 主账号的存档、狐狸和权限。"
        else:
            result += "基岩关联：尚未关联\n只玩 Java：现在即可入服。\n两端都玩：发送 /关联基岩 Xbox昵称。即使名字相同也需验证关联。"
        return result
    return ("【你的入服账号】\n基岩独立账号：" + binding["name"] +
            "\n当前使用基岩自己的存档。\n想共用 Java 存档：先 /换绑Java Java游戏名，再 /关联基岩 " + binding["name"] +
            "\n★ 共通后以 Java 原存档为准，原基岩存档保留但不会合并。")


class QQBot(botpy.Client):
    def __init__(self, settings, **kwargs):
        super().__init__(**kwargs)
        self.settings = settings
        self.afterglow = Afterglow(settings["afterglow_connection"]) if settings.get("features", {}).get("private_ai", False) else None
        self.group_names = {}
        self.seen = OrderedDict()
        self.chat_task = None

    async def bot_connect(self, session):
        # botpy 1.2.1 predates GROUP_MESSAGE_CREATE and drops author nickname/bot fields.
        def dispatch(payload, event):
            data = payload.get("d", {})
            message = RichGroupMessage(self.api, payload.get("id"), data)
            message.raw_data = data
            for key in ("nickname", "username", "bot", "member_role"):
                setattr(message.author, key, data.get("author", {}).get(key))
            self.ws_dispatch(event, message)
        self._connection.parser["group_message_create"] = lambda p: dispatch(p, "group_message_create")
        self._connection.parser["group_at_message_create"] = lambda p: dispatch(p, "group_at_message_create")
        await super().bot_connect(session)

    def duplicate(self, scene, message_id):
        key = (scene, message_id)
        if key in self.seen:
            return True
        self.seen[key] = True
        while len(self.seen) > 4096:
            self.seen.popitem(last=False)
        return False

    async def on_ready(self):
        log.info("MC QQ bot connected; allowed groups: %d", len(self.settings.get("allowed_groups", [])))
        status = Path(self.settings["database"]).parent / "bot-status.json"
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text(json.dumps({"ready_at": time.time(), "allowed_group_count": len(self.settings.get("allowed_groups", []))}))
        if self.chat_task is None or self.chat_task.done():
            self.chat_task = asyncio.create_task(self.chat_delivery())

    async def close(self):
        if self.chat_task:
            self.chat_task.cancel()
            await asyncio.gather(self.chat_task, return_exceptions=True)
        await super().close()

    async def chat_delivery(self):
        delivered = set()
        while True:
            try:
                result = await self.call_service("/v1/chat/to-qq", {})
                for item in result.get("messages", []):
                    if item["id"] not in delivered:
                        # No msg_id: this is an active group message, requiring QQ permission/quota.
                        await self.api.post_group_message(group_openid=item["group"], msg_type=0, content=item["text"])
                        delivered.add(item["id"])
                    await self.call_service("/v1/chat/ack-qq", {"ids": [item["id"]]})
                if len(delivered) > 4096:
                    delivered.clear()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Chat delivery unavailable (%s); waiting before retry", type(exc).__name__)
                await asyncio.sleep(15)
            await asyncio.sleep(1)

    async def group_name(self, group):
        cache = getattr(self, "group_names", None)
        if cache is None: self.group_names = cache = {}
        old = cache.get(group)
        if old and old[0] > time.monotonic(): return old[1]
        name = ""
        try:
            from botpy.http import Route
            result = await self.api._http.request(Route("GET", "/v2/groups/{group_openid}/info", group_openid=group))
            name = result.get("group_name", "") or result.get("name", "")
            if not isinstance(name, str): name = ""
        except Exception:
            log.debug("Group name unavailable; using configured alias or group id")
        cache[group] = (time.monotonic() + (3600 if name else 300), name[:128])
        return name[:128]

    async def relay_group(self, message):
        group = str(getattr(message, "group_openid", "") or "")
        author = getattr(message, "author", None)
        member = str(getattr(author, "member_openid", "") or "")
        text = getattr(message, "content", "") or ""
        raw = getattr(message, "raw_data", None)
        if raw is None:
            raw = {"content": text, "attachments": [vars(a) for a in (getattr(message, "attachments", None) or [])]}
        rich = media.extract(raw)
        if group not in self.settings.get("chat_bridge", {}).get("inbound_groups", self.settings.get("allowed_groups", [])) or not member or (not rich["text"].strip() and not rich["media"]) or getattr(author, "bot", False):
            return
        try:
            result = await self.call_service("/v1/chat/from-qq", {
                "app_id": self.settings["app_id"], "group_openid": group, "member_openid": member,
                "group_name": await self.group_name(group),
                "event_id": message.id, "text": rich["text"], "media": rich["media"],
                "nickname": getattr(author, "nickname", None) or getattr(author, "username", None) or "",
                "role": getattr(author, "member_role", None) or "member"})
            if "error" in result:
                log.warning("Group chat relay rejected")
        except (aiohttp.ClientError, asyncio.TimeoutError):
            log.warning("Group chat relay unavailable")

    async def call_service(self, path, payload):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(self.settings["service_url"].rstrip("/") + path,
                                    headers={"Authorization": "Bearer " + self.settings["bot_token"]}, json=payload) as response:
                if response.status not in (200, 400, 409, 503):
                    raise aiohttp.ClientError("binding service unavailable")
                return await response.json()

    async def group_response(self, message):
        try:
            launcher_response = await launcher.reply(self, message)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
            return "入服小助手的验证服务暂时不可用，请稍后重新发送。"
        if launcher_response is not None:
            return launcher_response
        try:
            action, platform, name = parse(message.content)
        except ValueError as exc:
            return str(exc)
        group = str(getattr(message, "group_openid", "") or "")
        author = getattr(message, "author", None)
        member = str(getattr(author, "member_openid", "") or "")
        if action == "group":
            return "本群 group_openid：" + group
        if action == "help":
            return HELP
        if group not in self.settings.get("allowed_groups", []):
            return "本群尚未开放绑定，请让服主配置 /本群ID 返回的标识。"
        if action == "chat":
            data = await self.call_service("/v1/chat/status", {})
            return ("【群服互通】\n子服：" + "、".join(data.get("servers", [])) +
                    "\n群内文本 → 游戏：[群内]角色或QQ官方身份:文本\n游戏 → 群：/said 文本（普通聊天不转发）\n需要群主开启接收全量消息及主动消息权限。\n你的群身份ID：" + member)
        if not member or not getattr(message, "id", None):
            return "缺少 QQ 官方身份凭证，请重新 @机器人 发送命令。"
        payload = {"app_id": self.settings["app_id"], "group_openid": group, "member_openid": member}
        try:
            if action in ("title_set", "title_clear"):
                data = await self.call_service("/v1/chat/title", dict(payload, event_id=message.id,
                    action="set" if action == "title_set" else "clear", title=name,
                    role=getattr(author, "member_role", None) or "member"))
                if "error" in data:
                    return data["error"]
                return (("头衔已设置为：" + data["title"]) if data["title"] else "已清除自定义头衔，恢复默认身份标签。") + "\n下次可修改：" + str(data["cooldown_seconds"]) + "秒后。"
            if action == "query":
                data = await self.call_service("/v1/query", payload)
                if "error" in data:
                    return data["error"]
                binding = data["binding"]
                return binding_summary(binding)
            if action in ("unbind", "unlink"):
                if name != "确认":
                    data = await self.call_service("/v1/query", payload)
                    if "error" in data:
                        return data["error"]
                    binding = data["binding"]
                    if not binding:
                        return "【无需操作】你目前没有绑定游戏账号，也没有入服白名单。"
                    if action == "unlink":
                        if binding["platform"] != "java":
                            return "【没有双端关联】你当前是基岩独立账号。\n如需退出白名单，请发送 /解绑；存档会保留。"
                        return ("【解除基岩关联】\nJava 主账号 " + binding["name"] +
                                " 将保留；基岩关联和待验证申请会被取消。\n★ 不删除任何存档。\n确认请发送：/解除关联 确认")
                    return ("【退出服务器白名单】\n主账号：" + binding["name"] +
                            ("\n基岩关联：" + binding["bedrock_name"] if binding.get("bedrock_name") else "") +
                            "\n将撤销所有入服资格并取消关联申请，在线账号随后会被踢出。\n★ 游戏存档、狐狸和权限数据保留，以后可重新绑定。\n确认请发送：/解绑 确认")
                payload.update(action=action, confirmed=True, event_id=message.id)
                data = await self.call_service("/v1/remove", payload)
                if "error" in data:
                    return data["error"]
                if action == "unlink":
                    if not data.get("removed"):
                        return "【关联已清理】\n没有已生效的基岩关联；待验证申请已取消。主账号和存档保留。"
                    return "【已解除基岩关联】\nJava 主账号与存档保留，基岩端已失去关联入服资格。待验证申请也已取消。\n重新关联：/关联基岩 Xbox昵称"
                return "【已解绑，欢迎以后再来】\n入服白名单和双端关联已移除，待验证申请已取消。\n游戏存档、狐狸和权限数据保留；以后绑定回同一游戏账号即可继续使用。"
            # A second Bedrock binding is an alias request, never a replacement of the Java save.
            if action == "bind" and platform == "bedrock":
                current = await self.call_service("/v1/query", payload)
                if "error" in current:
                    return current["error"]
                if current.get("binding") and current["binding"]["platform"] == "java":
                    action = "link"
            if action == "link":
                payload["name"] = name
                data = await self.call_service("/v1/request-link", payload)
                if "error" in data:
                    return data["error"]
                return ("【还差一步：在 Java 游戏内确认】\nJava 主账号：" + data["java_name"] +
                        "\n基岩 Xbox 账号：" + data["bedrock_name"] +
                        "\n★ 已识别为双端关联，Java 主账号保留。名字相同也可以关联。\n请用上述 Java 正版账号登录，在游戏聊天栏输入：\n/qqverify " + data["code"] +
                        "\n关联码 10 分钟有效；验证后基岩端重新登录，即可共用 Java 原有库存、狐狸和权限。")
            payload.update(action=action, platform=platform, name=name, event_id=message.id)
            data = await self.call_service("/v1/bind", payload)
            if "error" in data:
                return data["error"]
            label = "Java 主账号" if data["platform"] == "java" else "基岩独立账号"
            result = "【入服资格已开通】\n" + label + "：" + data["name"] + "\n✓ 已加入服务器白名单，可以连接服务器。"
            if data.get("previous_name"):
                result += "\n旧账号 " + data["previous_name"] + " 的入服资格及旧基岩关联已撤销；原存档保留，不会搬到新账号。"
            if data["platform"] == "java":
                result += "\n还玩基岩版？发送 /关联基岩 Xbox昵称，共用这个 Java 账号的存档。"
            else:
                result += "\n这是基岩独立存档。查看状态或双端共通步骤：/我的绑定"
            return result
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
            log.warning("Binding service request failed")
            return "绑定服务暂时不可用，请稍后重试；可用 /我的绑定 确认上次操作是否已完成。"

    async def on_group_at_message_create(self, message):
        await self.on_group_message_create(message)

    async def on_group_message_create(self, message):
        if self.duplicate("group", message.id):
            return
        if getattr(message.author, "bot", False):
            return
        text = re.sub(r"^<@!?[^>]+>\s*", "", message.content or "").strip()
        # Commands remain available when QQ switches @ events to full-message events.
        if not text and not getattr(message, "attachments", None) and not (getattr(message, "raw_data", {}).get("msg_elements")):
            return
        if re.match(r"^/?(?:设置头衔|清除头衔|绑定Java|绑定基岩|关联基岩|我的绑定|换绑Java|换绑基岩|解绑|解除关联|帮助|help|本群ID|群服互通|绑定|换绑|引导验证)(?:\s|$)", text, re.I):
            await message.reply(content=await self.group_response(message))
        else:
            await self.relay_group(message)

    async def on_c2c_message_create(self, message):
        if self.duplicate("private", message.id):
            return
        author = getattr(message, "author", None)
        user = str(getattr(author, "user_openid", "") or getattr(author, "id", "") or "")
        if not user:
            return
        text = (getattr(message, "content", "") or "").strip()
        if self.afterglow is None: return
        reply = await self.afterglow.respond(user, text)
        if reply:
            await message.reply(content=reply)


def main():
    settings = load()
    # The SDK creates clients against the current event loop, including on Python 3.14.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = QQBot(settings, intents=botpy.Intents(public_messages=True))
    try:
        bot.run(appid=settings["app_id"], secret=settings["app_secret"])
    finally:
        loop.close()


if __name__ == "__main__":
    main()

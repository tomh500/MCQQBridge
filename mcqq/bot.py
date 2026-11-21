import asyncio
import logging
import json
import time
import re
import hashlib
import hmac
import struct
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import OrderedDict
from pathlib import Path

import aiohttp
import botpy

from .afterglow import Afterglow
from .commands import HELP, expand_command_group, parse
from .config import load
from . import command_quota, launcher
from botpy.message import GroupMessage
from . import media
from . import status_bot
from . import system_info
from . import reply_controls
from .waifu_images import PortraitMaterials
from .feature_policy import FeaturePolicy
from .group_ai import GroupAI
from .group_reports import BEIJING, CATCHUP, DailyReports, event_time, midnight
from .plugins import configure_group_command, match_group_command, quota_config


class RichGroupMessage(GroupMessage):
    __slots__ = ("raw_data",)

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
GROUP_MENTION = re.compile(r"<@!?([0-9a-f]{32})>", re.IGNORECASE)
CROSS_GROUP_COMMAND = re.compile(r"^/跨群信息(?:\s|$)")
CROSS_GROUP_MODE_SECONDS = 2 * 60 * 60


def plain_game_output(value):
    """Remove Minecraft legacy color codes before displaying command output in QQ."""
    return re.sub(r"§[0-9a-fk-orx]", "", value, flags=re.IGNORECASE)


def mentioned_member(message, argument):
    """Use the QQ mention's official member ID, never a display name."""
    match = re.fullmatch(r"(?:<@!?|@)([A-Fa-f0-9]{32})>?", argument.strip())
    if match:
        return match.group(1).upper()
    raw = getattr(message, "raw_data", None) or {}
    if not isinstance(raw, dict):
        return None
    known_mentions = raw.get("mentions") or []
    mentions = list(known_mentions) + list(raw.get("msg_elements") or [])
    found = set()
    for element in mentions:
        if not isinstance(element, dict):
            continue
        if element.get("type") not in ("at", "mention", "AT") and element not in known_mentions:
            continue
        for value in (element, element.get("data"), element.get("at"), element.get("mention")):
            if isinstance(value, dict):
                for key in ("member_openid", "target_member_openid", "openid", "target"):
                    candidate = value.get(key)
                    if isinstance(candidate, str) and re.fullmatch(r"[A-Fa-f0-9]{32}", candidate):
                        found.add(candidate.upper())
    return next(iter(found)) if len(found) == 1 and argument.strip().startswith("@") else None


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
        self.cross_group_modes = {}
        self.cross_group_mode_updates = {}
        self.cross_group_receipts = OrderedDict()
        self.chat_task = None
        self.expanded_store = reply_controls.ExpandedStore(settings["database"],
            settings.get("daily_waifu", {}).get("redis_url"))
        self.group_ai = GroupAI(settings)
        self.daily_reports = DailyReports(
            self.group_ai, settings, self.send_group_report_image, notify=self.send_group_text,
        )
        self.report_task = None

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
        if self.report_task is None or self.report_task.done():
            self.report_task = asyncio.create_task(self.daily_reports.run())

    async def close(self):
        tasks = [task for task in (self.chat_task, self.report_task) if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.expanded_store.close()
        await asyncio.to_thread(self.group_ai.history.close)
        await super().close()

    def reply_store(self):
        store = getattr(self, "expanded_store", None)
        if store is None:
            self.expanded_store = store = reply_controls.ExpandedStore(self.settings["database"])
        return store

    async def send_group_text(self, group, content, *, msg_id=None, translate=True):
        content = plain_game_output(content)
        if translate:
            content = reply_controls.localize(content)
        if len(content) <= 1700:
            return await self.api.post_group_message(group_openid=group, msg_type=0,
                                                     content=content, **({"msg_id": msg_id} if msg_id else {}))
        return await self.post_full(group, content, msg_id=msg_id)

    async def reply_group_text(self, message, content, *, translate=True, sequence=None):
        content = plain_game_output(content)
        if translate:
            content = reply_controls.localize(content)
        if len(content) <= 1700:
            return await message.reply(content=content, **({"msg_seq": sequence} if sequence else {}))
        return await self.post_full(message.group_openid, content, msg_id=message.id)

    async def send_group_report_image(self, group, image, *, msg_id=None, sequence=1):
        images = getattr(self, "waifu_images", None)
        if images is None:
            self.waifu_images = images = PortraitMaterials(
                self.api, Path(self.settings["database"]).parent / "waifu-portraits")
        filename = "mcqq-report-" + hashlib.sha256(image).hexdigest() + ".png"
        width, height = struct.unpack(">II", image[16:24])
        display_width = min(width, 640)
        display_height = round(height * display_width / width)
        async with asyncio.timeout(40):
            url = await images.publish(image, filename, "image/png")
            kwargs = {"msg_id": msg_id, "msg_seq": sequence} if msg_id else {}
            return await self.api.post_group_message(group_openid=group, msg_type=2,
                markdown={"content": f"![群聊情报 #{display_width}px #{display_height}px]({url})"}, **kwargs)

    async def manual_group_report(self, message, group, member, cutoff):
        try:
            if await self.role_for(group, member) not in ("owner", "admin"):
                await self.reply_group_text(message, "只有 Bot 主人或管理可以绘制群讯息情报。", translate=False)
                return
            images, _ = await self.daily_reports.report(group, midnight(cutoff), cutoff, manual=True)
            await self.send_group_report_image(group, images[0], msg_id=message.id, sequence=1)
        except Exception:
            log.exception("Manual QQ daily report failed")
            await self.reply_group_text(message, "群讯息情报生成或发送失败，请稍后再试。", translate=False)

    async def run_group_plugin(self, command, argument, message, group, member, received):
        quota = quota_config(command)
        resetting = bool(quota and argument == "重置")
        if quota:
            try:
                role = await self.role_for(group, member)
                unrestricted = role in quota["unlimited_roles"]
            except Exception as error:
                log.warning("Group command %s role check failed (%s)", command.name, type(error).__name__)
                await self.reply_group_text(message, "暂时无法核验群内权限，请稍后再试。", translate=False)
                return
            if resetting:
                if role not in quota.get("reset_roles", ("owner", "admin")):
                    await self.reply_group_text(message, "只有 Bot 主人或管理员可以重置群友情报限额。", translate=False)
                    return
                try:
                    await asyncio.to_thread(command_quota.reset_configured, self.settings, command.name, group)
                except Exception:
                    log.exception("Group command quota reset failed")
                    await self.reply_group_text(message, "限额暂时无法重置，请稍后再试。", translate=False)
                    return
                await self.reply_group_text(message, "已重置本群的群友情报限额。", translate=False)
                return
        if command.argument == "mention":
            valid = re.fullmatch(r"(?:<@!?[0-9a-f]{32}>|@[^@<>\r\n]+)", argument, re.I)
            argument = mentioned_member(message, argument) if valid else None
            if not argument:
                await self.reply_group_text(message, f"格式：/{command.name} @群友", translate=False)
                return
        if quota and not unrestricted:
            try:
                status = await asyncio.to_thread(command_quota.take_configured, self.settings, command.name,
                                                 group, member, quota["limits"])
            except Exception:
                log.exception("Group command quota check failed")
                await self.reply_group_text(message, "限额暂时无法核验，请稍后再试。", translate=False)
                return
            if status is not None:
                log.info("Group command %s rejected by quota", command.name)
                await self.reply_group_text(message, command_quota.rejected_message(status), translate=False)
                return
        sequence = 1
        if notice := command.config["command"].get("queue_notice"):
            try:
                await self.reply_group_text(message, notice, translate=False, sequence=sequence)
                sequence += 1
            except Exception as error:
                log.warning("Group command %s queue receipt failed (%s)", command.name, type(error).__name__)
        try:
            started = time.monotonic()
            log.info("Group command %s accepted", command.name)
            slots = getattr(self, "_group_plugin_slots", None)
            if slots is None:
                self._group_plugin_slots = slots = asyncio.Semaphore(2)
            async with asyncio.timeout(180), slots:
                result = await command.handler(self.group_ai, self.settings, group, argument, received, command.config)
            if isinstance(result, bytes):
                elapsed = time.monotonic() - started
                log.info("Group command %s image rendered in %.1fs", command.name, elapsed)
                await self.send_group_report_image(group, result, msg_id=message.id, sequence=sequence)
                log.info("Group command %s image sent in %.1fs", command.name, time.monotonic() - started)
            else:
                await self.reply_group_text(message, result, translate=False, sequence=sequence)
        except Exception:
            log.exception("Group command plugin failed: %s", command.name)
            await self.reply_group_text(message, f"{command.name}生成或发送失败，请稍后再试。",
                                        translate=False, sequence=sequence)

    async def role_for(self, group, member):
        result = await self.call_service("/v1/command/role", {
            "app_id": self.settings["app_id"], "group_openid": group, "member_openid": member})
        return result.get("role", "member")

    async def post_full(self, group, content, *, msg_id=None, event_id=None):
        receipts = []
        for sequence, chunk in enumerate(reply_controls.chunks(content), 1):
            kwargs = {"msg_id": msg_id, "msg_seq": sequence} if msg_id else {"event_id": event_id, "msg_seq": sequence}
            receipts.append(await self.api.post_group_message(group_openid=group, msg_type=0,
                                                              content=chunk, **kwargs))
        return receipts

    async def send_expanded(self, group, token, member, *, msg_id=None):
        try:
            role = await self.role_for(group, member)
            if role not in ("owner", "admin"):
                return False
            content = await self.reply_store().load(group, token)
            if not content:
                return None
            await self.post_full(group, content, msg_id=msg_id)
            return True
        except Exception:
            log.exception("Expanded QQ reply failed")
            return None

    def waifu_button_data(self, group, member, day, draw_token):
        payload = f"{group}|{member}|{day}|{draw_token}".encode()
        signature = hmac.new(self.settings["bot_token"].encode(), payload, hashlib.sha256).hexdigest()[:24]
        return f"waifu_swap:{day}:{draw_token}:{signature}"

    async def send_waifu_card(self, group, data, *, msg_id=None, event_id=None, show_swap=False):
        if "error" in data:
            await self.api.post_group_message(group_openid=group, msg_type=0, content=data["error"],
                **({"msg_id": msg_id} if msg_id else {"event_id": event_id}))
            return
        member = data.get("member_openid", "")
        mention = f"<qqbot-at-user id=\"{member}\" />" if re.fullmatch(r"[A-Fa-f0-9]{32}", member) else ""
        name = re.sub(r"[\[\]<>\n\r]", "", data["name"])
        work = re.sub(r"[\[\]<>\n\r]", "", data.get("work") or "未知作品")
        text = "本次免费更换，你的新老婆名字叫" if data.get("exchanged") else "你的今日老婆名字叫"
        try:
            images = getattr(self, "waifu_images", None)
            if images is None:
                self.waifu_images = images = PortraitMaterials(self.api, Path(self.settings["database"]).parent / "waifu-portraits")
            portrait_url = await images.resolve(data["image_url"])
        except Exception as exc:
            log.warning("Waifu material unavailable (%s)", type(exc).__name__)
            portrait_url = None
        caption = (f"![角色 #100px #150px]({portrait_url})\n" if portrait_url else "") + f"{mention}，{text}：{name}\n> 来自：{work}"
        reference = {"msg_id": msg_id} if msg_id else {"event_id": event_id}
        rows = []
        if msg_id or event_id:
            action = self.waifu_button_data(group, member, data["day"], data["draw_token"])
            buttons = []
            if show_swap and not data.get("swapped") and msg_id:
                buttons.append({"id": "waifu_swap", "render_data": {"label": "🔄换老婆", "visited_label": "🔄换老婆", "style": 1},
                    "action": {"type": 2, "permission": {"type": 2}, "data": "/换老婆", "enter": True}})
            buttons.append({"id": "waifu_accept", "render_data": {"label": "✅就这个了!", "visited_label": "✅就这个了!", "style": 1},
                "action": {"type": 1, "permission": {"type": 2}, "data": action.replace("waifu_swap:", "waifu_accept:", 1)}})
            rows.append({"buttons": buttons})
        rows.append({"buttons": [{"id": "waifu_draw", "render_data": {"label": "🍀我也要抽!", "visited_label": "🍀我也要抽!", "style": 0},
            "action": {"type": 2, "permission": {"type": 2}, "data": "/今日老婆", "enter": True}}]})
        rows.append({"buttons": [{"id": "waifu_wish", "render_data": {"label": "✨许愿", "visited_label": "✨许愿", "style": 1},
            "action": {"type": 2, "permission": {"type": 2}, "data": "/今日老婆 许愿 ", "enter": False}}]})
        try:
            await self.api.post_group_message(group_openid=group, msg_type=2,
                markdown={"content": caption}, keyboard={"content": {"rows": rows}}, msg_seq=1, **reference)
        except Exception as exc:
            # A timeout may mean QQ accepted the card; retrying can duplicate it.
            log.warning("QQ waifu card delivery failed or is uncertain (%s)", type(exc).__name__)

    async def daily_waifu_reply(self, message, action="today"):
        group = str(getattr(message, "group_openid", "") or "")
        allowed = self.settings.get("allowed_groups", [])
        commands = self.settings.get("chat_bridge", {}).get("command_groups", allowed)
        member = str(getattr(getattr(message, "author", None), "member_openid", "") or "")
        if group not in allowed or group not in commands or not member or not getattr(message, "id", None):
            await self.send_group_text(group, "本群尚未开放此指令，或缺少 QQ 官方身份。", msg_id=message.id)
            return
        try:
            data = await self.call_service("/v1/waifu/" + action, {
                "app_id": self.settings["app_id"], "group_openid": group, "member_openid": member})
            data["member_openid"] = member
            await self.send_waifu_card(group, data, msg_id=message.id, show_swap=action == "today")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
            await self.send_group_text(group, "今日老婆暂时无法取得，请稍后再试。", msg_id=message.id)

    async def daily_waifu_reset(self, message):
        group = str(getattr(message, "group_openid", "") or "")
        member = str(getattr(getattr(message, "author", None), "member_openid", "") or "")
        try:
            data = await self.call_service("/v1/waifu/reset", {
                "app_id": self.settings["app_id"], "group_openid": group,
                "member_openid": member, "event_id": message.id})
            if "error" in data:
                await self.reply_group_text(message, data["error"])
            else:
                await self.reply_group_text(message,
                    f"已重置今天全部群友的今日老婆与换取次数，共清除 {data['count']} 笔纪录。"
                    if data.get("reset") else "这次重置请求已处理。")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
            await self.reply_group_text(message, "重置暂时无法使用，请稍后再试。")

    async def chat_delivery(self):
        delivered = set()
        while True:
            try:
                result = await self.call_service("/v1/chat/to-qq", {})
                for item in result.get("messages", []):
                    if item["id"] not in delivered:
                        # No msg_id: this is an active group message, requiring QQ permission/quota.
                        await self.send_group_text(item["group"], item["text"], translate=False)
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
        status_query = path == status_bot.QUERY_PATH
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3 if status_query else 20)) as session:
            async with session.post(self.settings["service_url"].rstrip("/") + path,
                                    headers={"Authorization": "Bearer " + self.settings["bot_token"]}, json=payload) as response:
                if response.status not in ((200, 400, 409, 429, 503) if status_query else (200, 400, 403, 409, 503)):
                    raise aiohttp.ClientError("binding service unavailable")
                return await response.json()

    async def group_response(self, message):
        group = str(getattr(message, "group_openid", "") or "")
        # Bootstrap command: a new group needs its own ID before it can join
        # command_groups or allowed_groups. Never trust a user-supplied ID.
        if group and re.fullmatch(r"/本群ID", re.sub(r"^<@!?[^>]+>\s*", "", message.content or "").strip()):
            return "本群 group_openid：" + group
        command_groups = self.settings.get("chat_bridge", {}).get("command_groups")
        if command_groups is not None and (not isinstance(command_groups, list) or group not in command_groups):
            return "本群暂未开放机器人命令。"
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
        if action == "system_info":
            host, metrics, smp = await asyncio.gather(
                asyncio.to_thread(system_info.read_system_info),
                asyncio.to_thread(system_info.read_extra_metrics),
                status_bot.reply(self, message, formatter=status_bot.format_smp_online)
                if member and getattr(message, "id", None) else asyncio.sleep(0, result="缺少 QQ 官方身份凭证。"),
                return_exceptions=True,
            )
            if isinstance(host, Exception):
                host = "机器状态暂时无法读取。"
            if isinstance(metrics, Exception):
                metrics = "CPU 和硬碟状态暂时无法读取。"
            if isinstance(smp, Exception):
                smp = "状态服务暂时不可用。"
            return f"{host}\n{metrics}\nSMP 在线人数：{smp}"
        if action in ("admin_add", "admin_remove"):
            if not member or not getattr(message, "id", None):
                return "缺少 QQ 官方身份凭证。"
            target = mentioned_member(message, name)
            if not target:
                return "请在命令后真正 @ 一名群成员，例如 /设bot管理 @成员。"
            payload = {"app_id": self.settings["app_id"], "group_openid": group,
                       "member_openid": member, "event_id": message.id,
                       "target_member_openid": target,
                       "action": "add" if action == "admin_add" else "remove"}
            try:
                data = await self.call_service("/v1/command/admin", payload)
                if "error" in data:
                    return data["error"]
                return "已" + ("设置" if action == "admin_add" else "取缔") + " Bot 管理：" + target
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
                return "Bot 管理设置暂时不可用。"
        if action.startswith("cross_group"):
            return await self.cross_group_command(message, action, platform, name)
        if action in ("game_command", "console_command"):
            author = getattr(message, "author", None)
            member = str(getattr(author, "member_openid", "") or "")
            if not member or not getattr(message, "id", None):
                return "缺少 QQ 官方身份凭证，请重新发送命令。"
            payload = {"app_id": self.settings["app_id"], "group_openid": group,
                       "member_openid": member, "event_id": message.id, "command": name,
                       "target": platform, "mode": "console" if action == "console_command" else "player"}
            try:
                result = await self.call_service("/v1/command/submit", payload)
                if "error" in result:
                    return result["error"]
                for _ in range(15):
                    if result.get("state") == "done":
                        return "\n".join(f"{item['server']}：{plain_game_output(item['result']) or '已执行。'}" for item in result["results"])
                    await asyncio.sleep(1)
                    result = await self.call_service("/v1/command/result", payload)
                return "指令已提交；执行结果暂未返回。"
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
                return "游戏指令服务暂时不可用。"
        if action == "chat":
            data = await self.call_service("/v1/chat/status", {})
            return ("【群服互通】\n子服：" + "、".join(data.get("servers", [])) +
                    "\n群内文本 → 游戏：[群内]角色或QQ官方身份:文本\n游戏 → 群：/said 文本（普通聊天不转发）\n需要群主开启接收全量消息及主动消息权限。\n你的群身份ID：" + member)
        if not member or not getattr(message, "id", None):
            return "缺少 QQ 官方身份凭证，请重新 @机器人 发送命令。"
        if action == "server_status":
            return await status_bot.reply(self, message)
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

    def cross_group_outbound(self):
        allowed = self.settings.get("allowed_groups", [])
        return self.settings.get("chat_bridge", {}).get("outbound_groups", allowed)

    async def cross_group_command(self, message, action, target, content):
        group = message.group_openid
        outbound = self.cross_group_outbound()
        aliases = self.settings.get("chat_bridge", {}).get("group_aliases", {})
        if action == "cross_group_list":
            lines = ["【可用跨群目标】"]
            for destination in outbound:
                label = aliases.get(destination) or await self.group_name(destination) or destination
                lines.append(f"{label}：{destination}" + ("（本群）" if destination == group else ""))
            lines.extend((
                "/跨群信息 [群名/别名] 内容（单词别名可省略方括号）",
                "/跨群信息 ALL 内容（发送到所有其他授权群）",
                "直接引用回复 Bot 转发的消息，可回传到来源群。",
                "/跨群信息 临时全量模式 群别名,群ID（2 小时，省略范围时为 ALL）",
                "/跨群信息 结束全量模式",
            ))
            return "\n".join(lines)
        member = getattr(getattr(message, "author", None), "member_openid", None)
        if not member or not getattr(message, "id", None):
            return "缺少 QQ 官方身份凭证，请重新发送命令。"
        if action == "cross_group_mode_stop":
            getattr(self, "cross_group_modes", {}).pop(member, None)
            getattr(self, "cross_group_mode_updates", {}).pop(member, None)
            return "已结束你的临时全量模式。"
        if action == "cross_group_mode_start":
            return await self.start_cross_group_mode(member, target, aliases)
        matches = await self.match_cross_groups(target) if target and target.upper() != "ALL" else []
        if len(matches) > 1 or (action == "cross_group" and target.upper() != "ALL" and not matches):
            return "目标群未找到或名称有歧义；发送 /跨群信息 查询可用群。"
        destination = matches[0] if matches else None
        implicit_all = action == "cross_group_implicit" and not destination
        if destination == group:
            return "目标群就是本群，请选择其他群。"
        if action == "cross_group_implicit" and destination is not None:
            content = content.split(maxsplit=1)[1]
        response = await self.forward_cross_group(
            message, content, [destination] if destination else outbound,
            quiet=self.active_cross_group_mode(member) is not None,
        )
        if implicit_all:
            warning = "⚠️ 未指定目标群，已按 ALL 处理。建议用 /跨群信息 群别名 信息 指定目标。"
            return f"{response}\n{warning}" if response else warning
        return response

    async def start_cross_group_mode(self, member, target, aliases):
        updates = getattr(self, "cross_group_mode_updates", None)
        if updates is None:
            self.cross_group_mode_updates = updates = {}
        request = updates[member] = object()
        try:
            scope = None
            if target.upper() != "ALL":
                scope = []
                for name in target.split(","):
                    name = name.strip()
                    matches = await self.match_cross_groups(name) if name else []
                    if updates.get(member) is not request:
                        return
                    if len(matches) != 1:
                        return f"全量模式目标「{name}」未找到或有歧义，请用英文逗号分隔群别名或群 ID。"
                    scope.append(matches[0])
            now = time.monotonic()
            modes = getattr(self, "cross_group_modes", {})
            self.cross_group_modes = {key: mode for key, mode in modes.items() if mode[0] > now}
            self.cross_group_modes[member] = (now + CROSS_GROUP_MODE_SECONDS, scope)
            label = "ALL" if scope is None else "、".join(aliases.get(item) or item for item in dict.fromkeys(scope))
            return f"已开启临时全量模式，有效期从现在起 2 小时。\n转发范围：{label}（自动跳过发言所在群）"
        finally:
            if updates.get(member) is request:
                del updates[member]

    def active_cross_group_mode(self, member):
        modes = getattr(self, "cross_group_modes", {})
        mode = modes.get(member)
        if mode and mode[0] > time.monotonic():
            return mode
        modes.pop(member, None)

    async def forward_cross_group(self, message, text, targets, *, quiet=False, attachments=()):
        group = message.group_openid
        outbound = self.cross_group_outbound()
        destinations = [target for target in dict.fromkeys(targets) if target != group and target in outbound]
        if not destinations:
            return "当前范围内没有可转发的其他授权群。"
        text = text.replace("\r\n", "\n")
        if len(text) > 2000 or any(ord(char) < 32 and char not in "\t\n" for char in text):
            return "消息过长或含有控制字符（最多 2000 字符）。"
        aliases = self.settings.get("chat_bridge", {}).get("group_aliases", {})
        source = aliases.get(group) or await self.group_name(group) or group
        author = message.author
        sender = getattr(author, "nickname", None) or getattr(author, "username", None) or author.member_openid
        sender = re.sub(r"[\x00-\x1f]", "", str(sender))[:64]
        content = f"【跨群信息｜{source}】{sender}：{text}"
        if len(content) > 2000:
            return "消息含来源标记后超过 2000 字符，请缩短内容。"
        failed = []
        for destination in destinations:
            try:
                if text:
                    result = await self.send_group_text(destination, content, translate=False)
                    for receipt in result if isinstance(result, list) else (result,):
                        self.remember_cross_group_receipt(receipt, destination, group)
                for file_type, url in attachments:
                    uploaded = await self.api.post_group_file(group_openid=destination, file_type=file_type, url=url)
                    receipt = await self.api.post_group_message(
                        group_openid=destination, msg_type=7, content=content if not text else "",
                        media={"file_info": uploaded["file_info"]},
                    )
                    self.remember_cross_group_receipt(receipt, destination, group)
            except Exception:
                log.exception("Cross-group delivery failed for %s", destination)
                failed.append(aliases.get(destination) or destination)
        sent = len(destinations) - len(failed)
        if failed:
            return f"已发送到 {sent}/{len(destinations)} 个群。\n发送失败：{'、'.join(failed)}"
        if not quiet:
            return f"已发送到 {sent} 个群。"

    @staticmethod
    def cross_group_attachments(message):
        raw = getattr(message, "raw_data", None) or {}
        files = []
        for item in (raw.get("attachments") or [])[:media.MAX_ITEMS]:
            if not isinstance(item, dict):
                continue
            mime = str(item.get("content_type", "")).lower().partition("/")[0]
            file_type = {"image": 1, "video": 2, "audio": 3}.get(mime)
            try:
                url = media.qq_url(item.get("url"))
            except ValueError:
                continue
            if file_type:
                files.append((file_type, url))
        return files

    def remember_cross_group_receipt(self, receipt, destination, source):
        if not isinstance(receipt, dict):
            return
        refs = getattr(self, "cross_group_receipts", None)
        if refs is None:
            self.cross_group_receipts = refs = OrderedDict()
        ext = receipt.get("ext_info")
        if not isinstance(ext, dict):
            ext = {}
        for key in (receipt.get("id"), ext.get("ref_idx")):
            if isinstance(key, str) and key:
                refs[destination, key] = source
        while len(refs) > 8192:
            refs.popitem(last=False)

    def cross_group_reply_source(self, message):
        raw = getattr(message, "raw_data", None) or {}
        scene = raw.get("message_scene") or {}
        reference = raw.get("message_reference") or {}
        indices = [reference.get("message_id")]
        indices.extend(part.partition("=")[2] for part in scene.get("ext") or []
                       if isinstance(part, str) and part.startswith("ref_msg_idx="))
        refs = getattr(self, "cross_group_receipts", {})
        for index in indices:
            if isinstance(index, str) and (source := refs.get((message.group_openid, index))):
                return source

    async def match_cross_groups(self, requested):
        outbound = self.cross_group_outbound()
        if requested in outbound:
            return [requested]
        aliases = self.settings.get("chat_bridge", {}).get("group_aliases", {})
        matches = []
        for group in outbound:
            if requested == aliases.get(group) or requested == await self.group_name(group):
                matches.append(group)
        return list(dict.fromkeys(matches))

    async def on_group_at_message_create(self, message):
        await self.on_group_message_create(message, explicit_at=True)

    def feature_rules(self):
        policy = getattr(self, '_feature_policy', None)
        if policy is None:
            self._feature_policy = policy = FeaturePolicy(self.settings)
        return policy

    async def feature_check(self, group, category, *, consume=True, schedule=None):
        try:
            return await asyncio.to_thread(self.feature_rules().check, group, category, consume=consume, schedule=schedule)
        except Exception:
            log.exception('Feature policy check failed')
            return {'allowed': False, 'reason': 'rate'}

    @staticmethod
    def feature_closed_text(result):
        following = result.get('next')
        return ('该功能当前不可用，下次开放：' + following.strftime('%m月%d日 %H:%M') + '。') if following else '该功能维护中，暂不可用。'

    async def on_interaction_create(self, interaction):
        group = str(getattr(interaction, "group_openid", "") or "")
        member = str(getattr(interaction, "group_member_openid", "") or "")
        data = getattr(getattr(interaction, "data", None), "resolved", None)
        button = str(getattr(data, "button_data", "") or "")
        waifu_action = button.startswith(("waifu_accept:", "waifu_swap:"))
        if waifu_action:
            match = re.fullmatch(r"waifu_(?:accept|swap):(\d{4}-\d{2}-\d{2}):([a-f0-9]{32}):([a-f0-9]{24})", button)
            signed = button.replace("waifu_accept:", "waifu_swap:", 1)
            today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
            if (not group or not member or not match or match.group(1) != today
                    or not hmac.compare_digest(signed, self.waifu_button_data(group, member, today, match.group(2)))):
                await self.api.on_interaction_result(interaction.id, 4)
                return
        category = self.feature_rules().category_for(button, button=True)
        if category:
            verdict = await self.feature_check(group, category, consume=not button.startswith('waifu_accept:'))
            if not verdict['allowed']:
                await self.api.on_interaction_result(interaction.id, 0)
                if verdict.get('reason') == 'closed':
                    await self.api.post_group_message(group_openid=group, msg_type=0,
                        content=self.feature_closed_text(verdict), event_id=interaction.id)
                return
        if button.startswith("waifu_accept:"):
            try:
                result = await self.call_service("/v1/waifu/accept", {"app_id": self.settings["app_id"], "group_openid": group, "member_openid": member, "draw_token": match.group(2), "event_id": interaction.id})
                await self.api.on_interaction_result(interaction.id, 1 if "error" in result else 0)
            except Exception:
                log.exception("QQ waifu acceptance failed")
                await self.api.on_interaction_result(interaction.id, 1)
            return
        if button.startswith("waifu_swap:"):
            acknowledged = False
            try:
                result = await self.call_service("/v1/waifu/swap", {
                    "app_id": self.settings["app_id"], "group_openid": group,
                    "member_openid": member, "draw_token": match.group(2)})
                result["member_openid"] = member
                await self.api.on_interaction_result(interaction.id, 0)
                acknowledged = True
                await self.send_waifu_card(group, result, event_id=interaction.id)
            except Exception:
                log.exception("QQ waifu exchange interaction failed")
                if not acknowledged:
                    try:
                        await self.api.on_interaction_result(interaction.id, 1)
                    except Exception:
                        pass
            return
        if not group or not member or not button.startswith("expand:"):
            await self.api.on_interaction_result(interaction.id, 1)
            return
        token = button[len("expand:"):]
        acknowledged = False
        try:
            role = await self.role_for(group, member)
            if role not in ("owner", "admin"):
                await self.api.on_interaction_result(interaction.id, 4)
                return
            content = await self.reply_store().load(group, token)
            if not content:
                await self.api.on_interaction_result(interaction.id, 1)
                return
            await self.api.on_interaction_result(interaction.id, 0)
            acknowledged = True
            await self.post_full(group, content, event_id=interaction.id)
        except Exception:
            log.exception("QQ expansion interaction failed")
            if not acknowledged:
                try:
                    await self.api.on_interaction_result(interaction.id, 1)
                except Exception:
                    pass

    async def on_group_message_create(self, message, explicit_at=False):
        received = datetime.now(BEIJING)
        already_seen = self.duplicate("group", message.id)
        if getattr(message.author, "bot", False):
            return
        raw_text = message.content or ""
        mention_openid = str(self.settings.get("group_ai_mention_openid", "")).casefold()
        # Full group events use the bot's group mention OpenID instead of its AppID.
        explicit_at = explicit_at or any(target.casefold() == mention_openid
                                         for target in GROUP_MENTION.findall(raw_text))
        if already_seen and not explicit_at:
            return
        text = re.sub(r"^<@!?[^>]+>\s*", "", raw_text).strip()
        raw = getattr(message, "raw_data", None) or {}
        # Commands remain available when QQ switches @ events to full-message events.
        if not (text or getattr(message, "attachments", None) or raw.get("attachments") or raw.get("msg_elements")):
            return
        group = str(getattr(message, "group_openid", "") or "")
        member = str(getattr(getattr(message, "author", None), "member_openid", "") or "")
        allowed = self.settings.get("chat_bridge", {}).get("command_groups", self.settings.get("allowed_groups", []))
        group_ai = getattr(self, "group_ai", None)
        reports = getattr(self, "daily_reports", None)
        authorized = self.settings.get("allowed_groups", [])
        llm_mention = explicit_at and text and not text.startswith("/")
        if llm_mention and group in allowed and member and self.duplicate("group_llm", message.id):
            return
        if not already_seen and group_ai and member and group in authorized:
            stamp = event_time(message, received)
            today = midnight(received)
            catchup = received < today + CATCHUP and group in getattr(reports, "groups", ())
            earliest = today - timedelta(days=1) if catchup else today
            if earliest <= stamp:
                try:
                    await group_ai.capture(message, group, member, raw_text, created=min(stamp, received).timestamp())
                except Exception as error:
                    log.warning("Group message could not be cached (%s)", type(error).__name__)
        if member and group in authorized and group in allowed and not CROSS_GROUP_COMMAND.match(text):
            source = self.cross_group_reply_source(message)
            mode = self.active_cross_group_mode(member)
            if source or mode:
                if not already_seen:
                    if source:
                        targets = [source]
                    else:
                        targets = self.cross_group_outbound() if mode[1] is None else mode[1]
                    attachments = self.cross_group_attachments(message)
                    if text or attachments:
                        result = await self.forward_cross_group(message, text, targets, quiet=True, attachments=attachments)
                    else:
                        result = "这条消息没有可转发的正文或受支持的附件。"
                    if result:
                        await self.reply_group_text(message, result, translate=False)
                return
        shortcut = None
        group_intel = re.fullmatch(r"/群情报(?:\s+([\s\S]+))?", text)
        if group_intel:
            argument = group_intel.group(1)
            if argument is None:
                shortcut = "/群情报 今日"
            elif (re.fullmatch(r"(?:<@!?[0-9a-f]{32}>|@[^@<>\r\n]+)", argument, re.I)
                  and mentioned_member(message, argument)):
                shortcut = f"/群情报 成员 {argument}"
        if shortcut:
            if already_seen or group not in authorized or group not in allowed or not member:
                return
            try:
                await self.reply_group_text(
                    message, f"⚠️ 这是非标准用法，建议使用：{shortcut}", translate=False, sequence=3,
                )
            except Exception:
                log.warning("Group intelligence shortcut notice could not be sent")
            text = shortcut
        if text.startswith("/"):
            try:
                text = expand_command_group(text)
            except ValueError as error:
                if not already_seen and member and group in allowed and group in authorized:
                    await self.reply_group_text(message, str(error), translate=False)
                return
        command, argument = match_group_command(text)
        if command:
            command = configure_group_command(command, self.settings)
            if command is None:
                return
            if not already_seen and group_ai and member and group in authorized and group in allowed:
                resetting = argument == "重置" and quota_config(command)
                verdict = {"allowed": True} if resetting else await self.feature_check(
                    group, command.category, schedule=command.schedule)
                if verdict["allowed"]:
                    await self.run_group_plugin(command, argument, message, group, member, received)
                elif verdict.get("reason") == "closed":
                    await self.reply_group_text(message, self.feature_closed_text(verdict))
            return
        if re.match(r"^/群讯息情报统计(?:\s|$)", text):
            if not already_seen and member and group in authorized and reports:
                await self.manual_group_report(message, group, member, received)
            return
        if group in allowed and member:
            if llm_mention or (not already_seen and text == '/历史讯息向量化'):
                verdict = await self.feature_check(group, 'llm', consume=False)
                if not verdict['allowed']:
                    await self.reply_group_text(message, '维护中暂不可用。')
                    return
            category = self.feature_rules().category_for(text)
            if category and not already_seen:
                verdict = await self.feature_check(group, category)
                if not verdict['allowed']:
                    if verdict.get('reason') == 'closed':
                        await self.reply_group_text(message, self.feature_closed_text(verdict))
                    return
        if already_seen:
            if group_ai and llm_mention and group in allowed and member:
                checked = group_ai.check(text)
                if checked is not None:
                    await self.reply_group_text(message, await group_ai.reply(group, checked, member), translate=False)
            return
        if group_ai and group in allowed and member:
            checked = text if text.startswith("/") else group_ai.check(text)
            if checked is None:
                return
            if re.fullmatch(r"/历史讯息向量化", text):
                role = await self.role_for(group, member)
                try:
                    response = (await group_ai.summarize(group) if role in ("owner", "admin")
                                else "只有 Bot 主人或管理可以整理历史讯息。")
                except Exception:
                    log.exception("Group history compression failed")
                    response = "历史讯息整理或保存失败，请稍后再试。"
                await self.reply_group_text(message, response)
                return
            if llm_mention:
                await self.reply_group_text(message, await group_ai.reply(group, checked, member), translate=False)
                return
        if re.fullmatch(r"/今日老婆\s+重置", text):
            await self.daily_waifu_reset(message)
            return
        wish = re.fullmatch(r"/今日老婆\s+许愿\s+(.+)", text)
        if wish:
            if group not in self.settings.get('allowed_groups', []) or group not in allowed or not member or not getattr(message, 'id', None):
                await self.reply_group_text(message, '本群尚未开放此指令，或缺少 QQ 官方身份。')
                return
            try:
                data = await self.call_service('/v1/waifu/wish', {'app_id': self.settings['app_id'], 'group_openid': group, 'member_openid': member, 'event_id': message.id, 'keyword': wish.group(1)})
                data['member_openid'] = member
                await self.send_waifu_card(group, data, msg_id=message.id, show_swap=True)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
                await self.reply_group_text(message, '许愿暂时不可用。')
            return
        points = re.fullmatch(r"/今日老婆\s+积分点\s+(查询|添加|设为)(?:\s+([\s\S]*))?", text)
        if points:
            if group not in self.settings.get('allowed_groups', []) or group not in allowed or not member or not getattr(message, 'id', None):
                await self.reply_group_text(message, '本群尚未开放此指令，或缺少 QQ 官方身份。')
                return
            op = {'查询': 'query', '添加': 'add', '设为': 'set'}[points.group(1)]
            tail = (points.group(2) or '').strip()
            pieces = tail.split()
            target = mentioned_member(message, pieces[0]) if pieces and pieces[0].startswith(('@', '<@')) else None
            if op != 'query' and (not target or len(pieces) != 2 or not re.fullmatch(r'-?[0-9]{1,10}', pieces[1]) or (op == 'set' and pieces[1].startswith('-'))):
                await self.reply_group_text(message, '格式：/今日老婆 积分点 添加|设为 @成员 数字')
                return
            if target is None and pieces and pieces[0].startswith(('@', '<@')):
                await self.reply_group_text(message, '请使用 QQ 的 @成员。')
                return
            payload = {'app_id': self.settings['app_id'], 'group_openid': group, 'member_openid': member, 'event_id': message.id, 'action': op}
            if target:
                payload['target_member_openid'] = target
            if op != 'query':
                payload['amount'] = int(pieces[1])
            try:
                result = await self.call_service('/v1/waifu/points', payload)
                await self.reply_group_text(message, str(result.get('points')) if 'points' in result else result.get('error', '暂时不可用。'))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
                await self.reply_group_text(message, '暂时不可用。')
            return
        if re.match(r"^/今日老婆(?:\s|$)", text) and not re.fullmatch(r"/今日老婆", text):
            await self.reply_group_text(message, '指令格式不正确。')
            return
        if re.fullmatch(r"/今日老婆", text):
            await self.daily_waifu_reply(message)
            return
        if re.fullmatch(r"/换老婆", text):
            await self.daily_waifu_reply(message, action="swap")
            return
        expansion = re.fullmatch(r"/展开\s+([A-Za-z0-9_-]{8,64})", text)
        if expansion:
            group = str(getattr(message, "group_openid", "") or "")
            member = str(getattr(getattr(message, "author", None), "member_openid", "") or "")
            result = await self.send_expanded(group, expansion.group(1), member, msg_id=message.id)
            if result is not True:
                await self.send_group_text(group, "没有展开权限，或内容已过期。", msg_id=message.id)
            return
        if re.match(r"^/(?:服务器|在线|伺服器情报|状态情报|设置头衔|清除头衔|设bot管理|取缔bot管理|取消bot管理|绑定Java|绑定基岩|关联基岩|我的绑定|换绑Java|换绑基岩|解绑|解除关联|帮助|help|本群ID|群服互通|跨群信息|大发命令|发命令|绑定|换绑|引导验证)(?:\s|$)", text, re.I):
            answer = await self.group_response(message)
            preserve_output = re.match(r"^/(?:大发命令|发命令|跨群信息)\s", text)
            if answer:
                await self.reply_group_text(message, answer, translate=not bool(preserve_output))
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
            await message.reply(content=plain_game_output(reply))


def main():
    settings = load()
    # The SDK creates clients against the current event loop, including on Python 3.14.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = QQBot(settings, intents=botpy.Intents(public_messages=True, interaction=True))
    try:
        bot.run(appid=settings["app_id"], secret=settings["app_secret"])
    finally:
        loop.close()


if __name__ == "__main__":
    main()

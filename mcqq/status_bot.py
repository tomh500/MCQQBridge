"""Text-only adapter for the two allowed observation commands."""
import asyncio
from collections import OrderedDict
import math
import time

import aiohttp

from .server_status import QUERY_PATH, SERVER_ID


def format_status(data):
    if not isinstance(data, dict):
        raise ValueError("invalid response")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported schema")
    servers = data["servers"]
    if not isinstance(servers, list) or not 1 <= len(servers) <= 32:
        raise ValueError("servers")
    lines = ["【服务器状态】"]
    for item in servers:
        if not isinstance(item, dict):
            raise ValueError("server item")
        server = item["server_id"]
        if not isinstance(server, str) or not SERVER_ID.fullmatch(server):
            raise ValueError("server")
        freshness = item["freshness"]
        if freshness in ("missing", "expired"):
            lines.append(server + ("：状态未知（尚无快照）" if freshness == "missing" else "：状态未知（快照已过期）"))
            continue
        snapshot = item["snapshot"]
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot")
        if freshness not in ("fresh", "stale") or snapshot["availability"] not in ("online", "offline"):
            raise ValueError("availability")
        online, capacity = snapshot["online_players"], snapshot["max_players"]
        if type(online) is not int or type(capacity) is not int or not 0 <= online <= capacity <= 100000 or capacity < 1:
            raise ValueError("players")
        age = item["age_seconds"]
        if type(age) not in (float, int) or not math.isfinite(age) or age < 0:
            raise ValueError("age")
        label = ("在线 " + str(online) + "/" + str(capacity)) if snapshot["availability"] == "online" else "离线"
        if freshness == "stale":
            label = "数据可能过期；最后观测：" + label
        for key, unit, upper in (("tps", " TPS", 1000), ("mspt_ms", " MSPT ms/tick", 60000)):
            value = snapshot[key]
            if value is not None:
                if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= upper:
                    raise ValueError("metric")
                label += f" | {value:g}{unit}"
        lines.append(f"{server}：{label}（{int(age)}秒前）")
    return "\n".join(lines)


async def reply(bot, message):
    now = time.monotonic()
    limits = getattr(bot, "status_limits", None)
    if limits is None:
        limits = bot.status_limits = OrderedDict()
    group = message.group_openid
    if now - limits.get(group, -100000) < 5:
        return "状态查询过于频繁，请稍后重试。"
    limits[group] = now
    limits.move_to_end(group)
    while len(limits) > 1024:
        limits.popitem(last=False)
    payload = dict(schema_version=1, app_id=bot.settings["app_id"], group_openid=group,
                   member_openid=message.author.member_openid, event_id=message.id)
    try:
        data = await asyncio.wait_for(bot.call_service(QUERY_PATH, payload), timeout=3)
        if not isinstance(data, dict):
            raise ValueError("invalid response")
        if data.get("code") == "rate_limited":
            return "状态查询过于频繁，请稍后重试。"
        if data.get("code") == "disabled":
            return "服务器状态查询尚未启用。"
        return format_status(data)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError, OverflowError):
        return "状态服务暂时不可用，请稍后重试。"

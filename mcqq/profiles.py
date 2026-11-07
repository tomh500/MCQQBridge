import re
import uuid
from urllib.parse import quote

from .store import BindingError


async def resolve(session, platform, name):
    if platform == "java":
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
            raise BindingError("Java 名字须为 3–16 位英文字母、数字或下划线。")
        url = "https://api.mojang.com/users/profiles/minecraft/" + quote(name, safe="")
    elif platform == "bedrock":
        # The argument is the Xbox gamertag, without Floodgate's '.' prefix.
        if not 1 <= len(name) <= 32 or not re.fullmatch(r"[\w #]+", name, re.UNICODE):
            raise BindingError("请填写 Xbox 昵称（含空格、不含服务器的 . 前缀）。")
        url = "https://api.geysermc.org/v2/xbox/xuid/" + quote(name, safe="")
    else:
        raise BindingError("版本只能是 Java 或 基岩。")
    async with session.get(url) as response:
        if response.status in (204, 400, 404):
            raise BindingError("未找到此游戏账号，请检查名字和游戏版本。")
        if response.status != 200:
            raise BindingError("游戏账号查询服务暂时不可用，请稍后重试。")
        data = await response.json()
    if platform == "java":
        return {"uuid": str(uuid.UUID(data["id"])), "name": data["name"], "platform": platform}
    xuid = int(data["xuid"])
    if not 0 < xuid < 2**64:
        raise BindingError("Xbox 身份查询返回无效结果。")
    return {"uuid": str(uuid.UUID(int=xuid)), "name": name, "platform": platform}

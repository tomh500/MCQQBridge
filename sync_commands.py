"""Explicitly register/update this application's group command panel only."""
import asyncio

import aiohttp

from mcqq.commands import COMMANDS
from mcqq.config import load

API = "https://api.sgroup.qq.com"
REMARK = "mcqq-group-managed-v1"


def display_width(text):
    return sum(2 if ord(char) > 127 else 1 for char in text)


def panel_config():
    items = [{"type": "command", "name": name, "desc": desc, "only_admin": False} for name, desc in COMMANDS]
    if len(items) > 20 or any(display_width(i["name"]) > 14 or display_width(i["desc"]) > 30 for i in items):
        raise ValueError("QQ panel field width exceeded (name 14 / description 30, Chinese counts as 2)")
    return {"remark": REMARK, "items": items}


async def read(response):
    data = await response.json(content_type=None)
    if response.status >= 400 or data.get("code", 0):
        raise RuntimeError(f"QQ panel API failed: HTTP {response.status}, code={data.get('code')}, message={data.get('message')}")
    return data


async def main():
    cfg = load()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post("https://bots.qq.com/app/getAppAccessToken",
                                json={"appId": cfg["app_id"], "clientSecret": cfg["app_secret"]}) as response:
            token = (await read(response))["access_token"]
        session.headers.update({"Authorization": "QQBot " + token, "X-Union-Appid": cfg["app_id"]})
        panel = panel_config()
        cursor = None
        existing = None
        while True:
            params = {"scope": "group", "limit": 50}
            if cursor:
                params["cursor"] = cursor
            async with session.get(API + "/v2/panels", params=params) as response:
                data = await read(response)
            existing = next((r for r in data.get("records", []) if r.get("panel", {}).get("remark") == REMARK), None)
            if existing or data.get("is_end") or not data.get("next_cursor"):
                break
            cursor = data["next_cursor"]
        if existing:
            panel_id = str(existing["panel_id"])
            async with session.put(API + "/v2/panels/" + str(existing["panel_id"]), json={"panel": panel}) as response:
                await read(response)
        else:
            async with session.post(API + "/v2/panels", json={"scope": "group", "target_type": "all", "panel": panel}) as response:
                panel_id = str((await read(response))["panel_id"])
        async with session.get(API + "/v2/panels/" + panel_id) as response:
            verified = await read(response)
        actual = verified.get("panel", {}).get("items", [])
        if [i.get("name") for i in actual] != [i["name"] for i in panel["items"]]:
            raise RuntimeError("QQ panel readback did not match submitted commands")
        print("QQ group command panel registered and readback verified: " + ", ".join(i["name"] for i in actual))


if __name__ == "__main__":
    asyncio.run(main())

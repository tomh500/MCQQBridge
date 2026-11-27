"""Group-scoped reply references and QQ's outbound Markdown mention format."""
import re
import time
import unicodedata

from botpy.http import Route


TTL = 300
OPENID = re.compile(r"[0-9a-f]{32}", re.IGNORECASE | re.ASCII)
REFERENCE = re.compile(r"〔qq:([0-9a-f]{16})〕")
INBOUND_AT = re.compile(r'<@!?[0-9a-f]{32}>|<qqbot-at-user\s+id="[0-9a-f]{32}"\s*/?>', re.IGNORECASE)
RAW_AT = re.compile(r"<(?=\s*(?:@|qqbot-))|@(?=everyone\b|all\b|全体)", re.IGNORECASE)
MARKDOWN_PUNCTUATION = re.compile(r"([\\`*_{}\[\]()#+\-.!|~])")


def enabled(cfg, group):
    bridge = cfg.get("chat_bridge", {})
    allowed = cfg.get("allowed_groups", [])
    selected = bridge.get("mention_groups", [])
    return (isinstance(selected, list) and group in selected and group in allowed
            and group in bridge.get("inbound_groups", allowed)
            and group in bridge.get("outbound_groups", allowed))


def configured(cfg):
    return any(enabled(cfg, group) for group in cfg.get("allowed_groups", []))


def label(nickname):
    name = "".join(c for c in nickname if c not in "§@〔〕<>" and unicodedata.category(c)[0] != "C")
    return " ".join(name.split())[:32].strip()


def plain(text):
    return RAW_AT.sub(lambda match: "＜" if match[0] == "<" else "＠", REFERENCE.sub("", text))


def markdown_text(text):
    text = plain(text).translate(str.maketrans("<>&", "＜＞＆"))
    return MARKDOWN_PUNCTUATION.sub(r"\\\1", text)


async def markdown_for(bot, item):
    mention = item.get("mention")
    group = item["group"]
    if not mention or not enabled(bot.settings, group) or mention["expires"] <= time.time():
        return None
    member = mention["member"]
    if not OPENID.fullmatch(member):
        return None
    try:
        state = await bot.api._http.request(Route("GET", "/v2/groups/{group_openid}/bot_state", group_openid=group))
        if state.get("allow_proactive_msg") is not True or state.get("member_openid", "").upper() == member.upper():
            return None
        profile = await bot.api._http.request(Route(
            "GET", "/v2/groups/{group_openid}/members/{member_openid}",
            group_openid=group, member_openid=member,
        ))
        if profile.get("member_openid", "").upper() != member.upper() or profile.get("bot") is not False:
            return None
    except Exception:
        # These endpoints can be restricted to allowlisted QQ bots.
        return None
    if mention["expires"] <= time.time():
        return None
    content = (markdown_text(mention["before"]) + f'<qqbot-at-user id="{member}" />'
               + markdown_text(mention["after"]))
    return {"content": content} if len(content) <= 1700 else None

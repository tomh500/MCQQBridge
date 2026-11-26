"""Resolve explicit QQ group replies for game chat."""

import re
import time
import unicodedata
from collections import OrderedDict

from . import media


MAX_RECENT = 4096
MAX_AGE = 3600
MAX_QUOTE = 240
OPENID = re.compile(r"[0-9a-f]{32}", re.I)
PRIVATE_REFERENCE = re.compile(r"(?:REFIDX_|ROBOT1\.0_|TMP_)\S+")


def object_fields(value):
    return value if isinstance(value, dict) else {}


def strings(*values):
    return tuple(dict.fromkeys(value for value in values if isinstance(value, str) and 0 < len(value) <= 1024))


def scene_indices(raw, field):
    ext = object_fields(raw.get("message_scene")).get("ext")
    if not isinstance(ext, list):
        return ()
    prefix = field + "="
    return tuple(part[len(prefix):] for part in ext if isinstance(part, str) and part.startswith(prefix))


def references(raw):
    reference = object_fields(raw.get("message_reference"))
    return strings(raw.get("ref_msg_idx"), *scene_indices(raw, "ref_msg_idx"), reference.get("message_id"))


def safe_text(value):
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<@!?[0-9a-f]{32}>", "@群成员", value, flags=re.I)
    value = OPENID.sub("[已隐藏]", PRIVATE_REFERENCE.sub("[已隐藏]", value))
    value = "".join(" " if unicodedata.category(c)[0] == "C" or c == "§" else c for c in value)
    return " ".join(value.split())


def display_name(raw):
    profiles = (object_fields(raw.get("author")), object_fields(raw.get("sender")), raw)
    for key in ("member_nickname", "card", "nickname", "username", "display_name"):
        for profile in profiles:
            name = profile.get(key)
            if isinstance(name, str) and not (OPENID.search(name) or PRIVATE_REFERENCE.search(name)):
                if cleaned := safe_text(name):
                    return cleaned[:64]
    return ""


def same_group(raw, group):
    source = raw.get("group_openid") or raw.get("group_id")
    return not source or source == group


def quote_parts(raw):
    """Return the current event, quoted elements, and reference IDs."""
    refs = references(raw)
    elements = raw.get("msg_elements")
    is_reply = str(raw.get("message_type")) == "103"
    if not (refs or is_reply):
        return raw, (), refs
    elements = elements if isinstance(elements, list) else []
    linked = [element for element in elements if isinstance(element, dict)
              and any(element.get(key) in refs for key in ("msg_idx", "id", "message_id"))]
    candidates = [element for element in elements if isinstance(element, dict)
                  and (element.get("msg_idx") or str(element.get("message_type")) == "103")]
    current = {**raw, "msg_elements": [element for element in elements if element not in linked + candidates]}
    quoted = linked
    if not quoted and is_reply and all(index.startswith("TMP_") for index in refs):
        # Full group events can use a temporary index for a nested reply.
        quoted = candidates
    embedded = raw.get("referenced_message")
    if not quoted and isinstance(embedded, dict):
        quoted = [embedded]
    return current, quoted, refs


def excerpt(rich):
    text = safe_text(rich["text"])
    if text.startswith("=== 消息 "):
        return ""
    return text[:MAX_QUOTE] or ("[图片]" if rich["media"] else "")


class RecentGroupMessages:
    def __init__(self):
        self.messages = OrderedDict()

    def remember(self, group, message_id, raw):
        current, _, _ = quote_parts(raw)
        author, text = display_name(raw), excerpt(media.extract(current))
        if not (author or text):
            return
        value = time.monotonic(), author, text
        for index in strings(message_id, raw.get("msg_idx"), *scene_indices(raw, "msg_idx")):
            self.messages[group, index] = value
            self.messages.move_to_end((group, index))
        while len(self.messages) > MAX_RECENT:
            self.messages.popitem(last=False)

    def quote(self, group, message_id, raw, elements, refs):
        if not same_group(object_fields(raw.get("message_reference")), group):
            return ""
        if elements and not all(same_group(element, group) for element in elements):
            return ""
        own = strings(message_id, raw.get("msg_idx"), *scene_indices(raw, "msg_idx"))
        name, text = "", ""
        for index in refs:
            if index not in own and (cached := self.messages.get((group, index))):
                if time.monotonic() - cached[0] <= MAX_AGE:
                    _, name, text = cached
                    break
        if len(elements) == 1:
            element = elements[0]
            name = name or display_name(element)
            text = text or excerpt(media.extract({**element, "msg_elements": []}))
        return f" [回复 {name or '群友'}:{text}]" if text else ""

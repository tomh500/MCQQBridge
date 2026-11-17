import json
import os
from pathlib import Path


def load():
    path = Path(os.environ.get("MCQQ_SETTINGS", str(Path(__file__).resolve().parents[1] / "settings.json"))).resolve()
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    daily = cfg.get("daily_waifu", {})
    if daily.get("enabled") and daily.get("credentials_file"):
        credentials = json.loads((path.parent / daily["credentials_file"]).read_text(encoding="utf-8"))
        daily.update(credentials)
    if os.environ.get("MCQQ_STATUS_REPORTER_TOKEN"):
        cfg["status_reporter_token"] = os.environ["MCQQ_STATUS_REPORTER_TOKEN"]
    for key in ("database", "afterglow_connection"):
        cfg[key] = str((path.parent / cfg[key]).resolve())
    if cfg.get("group_ai_config"):
        cfg["group_ai_config"] = str((path.parent / cfg["group_ai_config"]).resolve())
    if cfg.get("group_ai_word_filter"):
        cfg["group_ai_word_filter"] = str(Path(cfg["group_ai_word_filter"]).resolve())
    for key in ("bot_token", "proxy_token"):
        if len(cfg.get(key, "")) < 32:
            raise ValueError(f"{key} must contain at least 32 random characters")
    if cfg["bot_token"] == cfg["proxy_token"]:
        raise ValueError("Bot and proxy must use separate tokens")
    if any(str(g).isdigit() for g in cfg.get("allowed_groups", [])):
        raise ValueError("allowed_groups requires group_openid, not numeric QQ group numbers")
    inbound = cfg.get("chat_bridge", {}).get("inbound_groups", cfg.get("allowed_groups", []))
    if not isinstance(inbound, list) or any(g not in cfg.get("allowed_groups", []) for g in inbound):
        raise ValueError("inbound_groups must be a subset of allowed_groups")
    return cfg

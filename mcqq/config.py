import json
import os
from pathlib import Path
import yaml


def read_mapping(path):
    path = Path(path)
    text = path.read_text(encoding='utf-8-sig')
    value = yaml.safe_load(text) if path.suffix.lower() in ('.yml', '.yaml') else json.loads(text)
    if not isinstance(value, dict):
        raise ValueError(f'Configuration must be a mapping: {path}')
    return value


def load():
    root = Path(__file__).resolve().parents[1]
    default = next((root / name for name in ('settings.yml', 'settings.yaml', 'settings.json') if (root / name).is_file()), root / 'settings.yml')
    path = Path(os.environ.get("MCQQ_SETTINGS", str(default))).resolve()
    cfg = read_mapping(path)
    daily = cfg.get("daily_waifu", {})
    if daily.get("enabled") and daily.get("credentials_file"):
        credentials = read_mapping(path.parent / daily["credentials_file"])
        daily.update(credentials)
    storage = cfg.get("group_ai_storage") or {}
    if storage.get("credentials_file"):
        credentials = read_mapping(path.parent / storage["credentials_file"])
        storage = {**storage, **{section: {**storage.get(section, {}), **credentials.get(section, {})}
                                for section in ("mongodb", "mysql", "redis")}}
    if storage.get("credentials_from") == "daily_waifu":
        defaults = {
            "mongodb": {"uri": daily.get("mongo_uri"), "database": daily.get("mongo_database")},
            "mysql": daily.get("mysql", {}),
            "redis": {"url": daily.get("redis_url")},
        }
        storage = {**storage, **{section: {**values, **storage.get(section, {})}
                                for section, values in defaults.items()}}
    if storage:
        cfg["group_ai_storage"] = storage
    if os.environ.get("MCQQ_STATUS_REPORTER_TOKEN"):
        cfg["status_reporter_token"] = os.environ["MCQQ_STATUS_REPORTER_TOKEN"]
    for key in ("database", "afterglow_connection"):
        cfg[key] = str((path.parent / cfg[key]).resolve())
    if cfg.get("group_ai_config"):
        cfg["group_ai_config"] = str((path.parent / cfg["group_ai_config"]).resolve())
    if cfg.get("group_ai_word_filter"):
        cfg["group_ai_word_filter"] = str(Path(cfg["group_ai_word_filter"]).resolve())
    if cfg.get("daily_report_font"):
        cfg["daily_report_font"] = str((path.parent / cfg["daily_report_font"]).resolve())
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
    reports = cfg.get("daily_report_groups", [])
    if not isinstance(reports, list) or any(g not in cfg.get("allowed_groups", []) for g in reports):
        raise ValueError("daily_report_groups must be a subset of allowed_groups")
    return cfg

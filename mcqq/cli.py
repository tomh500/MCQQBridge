"""Portable CLI. Credentials and mutable state live in the chosen user directory."""
import argparse
import json
import logging
import os
from pathlib import Path
from importlib.resources import files

def main():
    parser = argparse.ArgumentParser(prog="mcqq")
    parser.add_argument("action", choices=["init", "bot", "api"])
    parser.add_argument("--config")
    args = parser.parse_args()
    default = 'settings.yml'
    if args.action != 'init' and not Path(default).exists():
        default = next((name for name in ('settings.yaml', 'settings.json') if Path(name).exists()), default)
    path = Path(args.config or default).resolve()
    if args.action == "init":
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create: never overwrite existing credentials.
        with path.open("x", encoding="utf-8") as stream:
            template = "settings.example.yml" if path.suffix.lower() in (".yml", ".yaml") else "settings.example.json"
            stream.write(files("mcqq").joinpath(template).read_text(encoding="utf-8"))
        path.chmod(0o600)
        print("Created empty configuration: " + str(path))
        return
    os.environ["MCQQ_SETTINGS"] = str(path)
    logging.basicConfig(level=logging.INFO)
    if args.action == "bot":
        from .bot import main as run_bot
        run_bot()
    else:
        from aiohttp import web
        from .config import load
        from .service import create_app
        cfg = load()
        web.run_app(create_app(cfg), host=cfg["listen_host"], port=cfg["listen_port"], access_log=None)

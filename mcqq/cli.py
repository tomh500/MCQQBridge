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
    parser.add_argument("--config", default="settings.json")
    args = parser.parse_args()
    path = Path(args.config).resolve()
    if args.action == "init":
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create: never overwrite existing credentials.
        with path.open("x", encoding="utf-8") as stream:
            stream.write(files("mcqq").joinpath("settings.example.json").read_text(encoding="utf-8"))
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

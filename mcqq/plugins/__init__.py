"""Built-in group command plugins, registered explicitly with their YAML manifests."""
from dataclasses import dataclass, replace
from importlib.resources import files

import yaml

from . import member_intel


@dataclass(frozen=True)
class GroupCommand:
    name: str
    category: str
    schedule: str
    argument: str
    config: dict
    handler: object
    plugin: str


def load_command(plugin, handler):
    config = yaml.safe_load(files(__package__).joinpath(plugin + ".yml").read_text(encoding="utf-8"))
    spec = config["command"]
    if not spec["name"] or not spec["category"] or spec.get("argument") not in ("mention", "text"):
        raise ValueError(f"Invalid group command manifest for {plugin}")
    return GroupCommand(spec["name"], spec["category"], spec["schedule"], spec["argument"], config, handler, plugin)


COMMANDS = {command.name: command for command in (load_command("member_intel", member_intel.handle),)}


def match_group_command(text):
    pieces = text[1:].split(maxsplit=1) if text.startswith("/") else []
    return (COMMANDS.get(pieces[0]), pieces[1] if len(pieces) > 1 else "") if pieces else (None, "")


def configure_group_command(command, settings):
    overrides = settings.get("plugins", {}).get(command.plugin, {})
    if not overrides.get("enabled", True):
        return None
    if not overrides:
        return command
    spec = command.config["command"]
    options = overrides.get("command", {})
    runtime = {**spec, **options}
    if "quota" in spec:
        runtime["quota"] = {**spec["quota"], **options.get("quota", {})}
    return replace(command, schedule=runtime["schedule"], config={
        **command.config,
        "command": runtime,
        "skill": {**command.config.get("skill", {}), **overrides.get("skill", {})},
    })


def quota_config(command):
    quota = command.config["command"].get("quota")
    return quota if quota and quota.get("enabled", True) else None

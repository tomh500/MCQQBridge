"""Update source labels without rewriting unrelated HOCON settings or credentials."""
import re
import shutil
import time
from pathlib import Path


def updated(text):
    for key, value in (("globalChat", "%mcqq_origin% &f%name%&7: &f%message%"),
                       ("localChat", "%mcqq_origin% &f%name%&7: &f%message%"),
                       ("defaultPrefix", "")):
        text, count = re.subn(r'(?m)^(\s*' + key + r'\s*=\s*)"[^"\r\n]*"',
                              lambda match: match[1] + '"' + value + '"', text)
        if count != 1:
            raise ValueError("Expected exactly one HOCON setting: " + key)
    return text


def main():
    root = Path(__file__).resolve().parents[2]
    config = root / "proxy/plugins/BungeeChat/config.conf"
    value = updated(config.read_text(encoding="utf-8-sig"))
    backup = root / "qqbot/deployment-backups" / ("source-formats-" + time.strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(parents=True)
    shutil.copy2(config, backup / "BungeeChat-config.conf")
    config.write_text(value, encoding="utf-8")
    print("Updated BungeeChat global/local source labels. Backup: " + str(backup))


if __name__ == "__main__":
    main()

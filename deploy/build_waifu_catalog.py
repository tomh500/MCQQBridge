"""Build a curated Bangumi anime-character catalog, without random image APIs."""
import json
import time
from pathlib import Path
import requests

API = "https://api.bgm.tv/v0"
session = requests.Session()
session.headers["User-Agent"] = "MCQQBridge/2.0 (https://github.com/)"
works = ["中二病でも恋がしたい", "けいおん!", "涼宮ハルヒの憂鬱", "Re:ゼロから始める異世界生活", "ぼっち・ざ・ろっく!", "葬送のフリーレン", "魔法少女まどか☆マギカ", "とある科学の超電磁砲", "やはり俺の青春ラブコメはまちがっている。", "五等分の花嫁"]
result = []
seen = set()
for keyword in works:
    response = session.post(API + "/search/subjects", json={"keyword": keyword, "filter": {"type": [2], "nsfw": False}}, timeout=15)
    response.raise_for_status()
    subjects = response.json()["data"]
    if not subjects:
        continue
    subject = subjects[0]
    response = session.get(f"{API}/subjects/{subject['id']}/characters", timeout=15)
    response.raise_for_status()
    for character in response.json()[:12]:
        if character["id"] in seen or not character.get("images"):
            continue
        response = session.get(f"{API}/characters/{character['id']}", timeout=15)
        response.raise_for_status()
        detail = response.json()
        if detail.get("gender") != "female":
            continue
        seen.add(character["id"])
        result.append({"id": character["id"], "name": character["name"],
                       "image_url": character["images"]["large"],
                       "source_url": f"https://bgm.tv/character/{character['id']}",
                       "work": subject.get("name_cn") or subject["name"]})
        time.sleep(.1)
if len(result) < 10:
    raise RuntimeError("catalog too small; refusing to replace")
Path(__file__).resolve().parents[1].joinpath("mcqq/waifu_catalog.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Built {len(result)} entries")

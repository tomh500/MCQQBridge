"""Fetch the curated catalog portraits into a runtime directory on a connected machine."""
import argparse
import concurrent.futures
import json
from pathlib import Path
from urllib.parse import urlparse

import requests

parser = argparse.ArgumentParser()
parser.add_argument('directory', type=Path)
args = parser.parse_args()
args.directory.mkdir(parents=True, exist_ok=True)
catalog = json.loads(Path(__file__).resolve().parents[1].joinpath('mcqq/waifu_catalog.json').read_text(encoding='utf-8'))


def fetch(entry):
    url = entry['image_url']
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'lain.bgm.tv' or not parsed.path.startswith('/pic/crt/l/'):
        raise ValueError('unexpected image host or path')
    ext = Path(parsed.path).suffix.lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp') or not isinstance(entry['id'], int):
        raise ValueError('unexpected image filename')
    response = requests.get(url, timeout=30, headers={'User-Agent': 'MCQQBridge/2.0 (https://github.com/)'})
    response.raise_for_status()
    if not response.headers.get('Content-Type', '').startswith('image/') or not 0 < len(response.content) <= 10_000_000:
        raise ValueError('invalid image response')
    target = args.directory / (str(entry['id']) + ext)
    target.write_bytes(response.content)
    return target


with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    print('Downloaded', len(list(pool.map(fetch, catalog))), 'portraits.')

"""Add coarse image characteristics to character vectors (requires Pillow)."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image, ImageFilter, ImageStat

parser = argparse.ArgumentParser()
parser.add_argument('directory', type=Path)
args = parser.parse_args()
path = Path(__file__).resolve().parents[1] / 'mcqq' / 'waifu_catalog.json'
catalog = json.loads(path.read_text(encoding='utf-8'))
for entry in catalog:
    ext = Path(urlparse(entry['image_url']).path).suffix.lower()
    image_path = args.directory / (str(entry['id']) + ext)
    with Image.open(image_path) as image:
        image = image.convert('RGB').resize((64, 64))
        hsv = ImageStat.Stat(image.convert('HSV')).mean
        edge = ImageStat.Stat(image.convert('L').filter(ImageFilter.FIND_EDGES)).mean[0]
    brightness = '明亮' if hsv[2] >= 170 else '中等' if hsv[2] >= 100 else '偏暗'
    saturation = '鲜艳' if hsv[1] >= 140 else '柔和' if hsv[1] >= 70 else '低饱和'
    lines = '细节较多' if edge >= 45 else '细节较少'
    entry['features'] = [x for x in entry.get('features', []) if not x.startswith('画面:')]
    entry['features'].extend(('画面:明度:' + brightness, '画面:饱和度:' + saturation, '画面:线条:' + lines))
path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Annotated', len(catalog), 'portraits.')

"""One compact celestial chart for group rankings and topic summaries."""
from io import BytesIO
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFont, ImageOps

WIDTH = 1280
RANK_LIMIT = 12
INK, SOFT, MUTED = "#f2f7ff", "#cbdaf1", "#a6b8d4"
PANEL, BORDER = "#101d35", "#30476c"
GOLD, SILVER, BRONZE = "#ffdc81", "#bbd9ff", "#ffc0a0"


def avatar_thumbnail(data, size=96):
    try:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height <= 12_000_000:
                return ImageOps.fit(source.convert("RGB"), (size, size), Image.Resampling.LANCZOS)
    except (OSError, ValueError, Image.DecompressionBombError):
        pass
    return None


def font_path(configured):
    if configured:
        return configured
    candidates = (
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    )
    for path in candidates:
        if Path(path).is_file():
            return path
    raise OSError("Set daily_report_font to a Chinese font or install Noto Sans CJK")


def png(image):
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


class Canvas:
    def __init__(self, height, font):
        self.image = Image.new("RGB", (WIDTH, height))
        self.draw = ImageDraw.Draw(self.image)
        path = font_path(font)
        self.fonts = {size: ImageFont.truetype(path, size) for size in (20, 23, 25, 28, 32, 36, 44, 54, 64, 82)}
        for y in range(height):
            glow = (1 - y / height) ** 2
            self.draw.line((0, y, WIDTH, y), fill=(7 + int(12 * glow), 13 + int(14 * glow), 25 + int(33 * glow)))
        stars = random.Random(734)
        for _ in range(370):
            self.draw.point((stars.randrange(WIDTH), stars.randrange(height)),
                            fill=stars.choice(("#395579", "#6482ac", "#9eb5d1")))

    def panel(self, box, *, fill=PANEL, outline=BORDER):
        self.draw.rounded_rectangle(box, 22, fill=fill, outline=outline, width=2)

    def text(self, x, y, text, size, color=INK, anchor="la"):
        self.draw.text((x, y), text, font=self.fonts[size], fill=color, anchor=anchor)

    def wrap(self, text, size, width, limit):
        font = self.fonts[size]
        clean = " ".join(str(text).split())
        lines, line = [], ""
        for char in clean:
            if line and font.getlength(line + char) > width:
                lines.append(line)
                line = ""
            if len(lines) >= limit:
                while lines[-1] and font.getlength(lines[-1] + "…") > width:
                    lines[-1] = lines[-1][:-1]
                lines[-1] += "…"
                return lines
            line += char
        return [*lines, line] if line else lines

    def portrait(self, x, y, size, name, avatar, color=SOFT):
        self.draw.ellipse((x-4, y-4, x+size+3, y+size+3), outline=color, width=3)
        portrait = avatar_thumbnail(avatar, size) if avatar else None
        if portrait is not None:
            mask = Image.new("L", (size, size))
            ImageDraw.Draw(mask).ellipse((0, 0, size-1, size-1), fill=255)
            self.image.paste(portrait, (x, y), mask)
        else:
            self.draw.ellipse((x, y, x+size-1, y+size-1), fill="#304970")
            initial = str(name).strip()[:1] or "?"
            self.text(x+size//2, y+size//2, initial, 32 if size >= 64 else 20, INK, "mm")


def render(start, end, manual, group, hours, rankings, blocks, font=None):
    timeline = blocks[:6]
    height = 950 + 158 * ((len(timeline) + 1) // 2)
    chart = Canvas(height, font)
    draw = chart.draw
    chart.text(50, 28, "群讯息情报", 64)
    name = (chart.wrap(group, 25, 395, 1) or ["本群"])[0]
    chart.text(55, 110, name + (" · 手动统计" if manual else " · 每日统计"), 25, GOLD)
    chart.text(1228, 49, f"{sum(hours):,} 条讯息  /  {len(rankings):,} 位发言者", 36, INK, "ra")
    chart.text(1228, 108, f"{start:%m-%d %H:%M} 至 {end:%m-%d %H:%M} · 北京时间", 23, SOFT, "ra")

    chart.panel((48, 166, 1232, 331))
    chart.text(72, 183, "全天发言星轨", 28)
    peak = max(hours, default=0)
    if peak:
        chart.text(1208, 187, f"峰值 {hours.index(peak):02d}:00 · {peak:,} 条", 23, GOLD, "ra")
    for hour, count in enumerate(hours):
        x = 77 + hour * 47
        rise = round(64 * count / peak) if peak else 0
        draw.rounded_rectangle((x, 288-max(4, rise), x+27, 288), 4,
                               fill=GOLD if count and count == peak else "#588dd1" if count else "#30476c")
        if hour % 3 == 0 or hour == 23:
            chart.text(x+13, 310, f"{hour:02}", 20, MUTED, "mm")

    chart.text(49, 354, "群友发言排行", 36)
    chart.text(1230, 367, "按发言条数排列", 23, SOFT, "ra")
    top = rankings[:3]
    top_count = rankings[0][1] if rankings else 1
    for rank, x, y, color in ((2, 48, 468, SILVER), (1, 446, 421, GOLD), (3, 844, 468, BRONZE)):
        if rank > len(top):
            continue
        name, count, avatar = top[rank-1]
        chart.panel((x, y, x+388, 649), outline=color)
        draw.ellipse((x+16, y+24, x+126, y+134), outline=BORDER, width=2)
        chart.portrait(x+35, y+43, 72, name, avatar, color)
        chart.text(x+140, y+13, f"#{rank:02}", 23, color)
        chart.text(x+140, y+47, chart.wrap(name, 28, 223, 1)[0], 28)
        chart.text(x+140, y+80, f"{count:,}", 54, color)
        chart.text(x+356, y+118, "条", 20, SOFT, "ra")
        draw.rounded_rectangle((x+26, 620, x+362, 628), 4, fill=BORDER)
        draw.rounded_rectangle((x+26, 620, x+26+max(6, round(336*count/top_count)), 628), 4, fill=color)
    if not rankings:
        chart.panel((48, 419, 1232, 649))
        chart.text(640, 533, "本时段暂无发言", 36, SOFT, "mm")

    for rank, (name, count, avatar) in enumerate(rankings[3:RANK_LIMIT], 4):
        index = rank - 4
        x, y = 48+(index % 3)*398, 670+(index//3)*65
        chart.panel((x, y, x+388, y+54))
        chart.text(x+15, y+14, f"{rank:02}", 23, SOFT)
        chart.portrait(x+62, y+10, 34, name, avatar)
        chart.text(x+112, y+13, chart.wrap(name, 25, 171, 1)[0], 25)
        chart.text(x+366, y+9, f"{count:,}", 32, INK, "ra")
    extra = rankings[RANK_LIMIT:]
    if extra:
        chart.text(1230, 872, f"其余 {len(extra):,} 位 · 合计 {sum(row[1] for row in extra):,} 条", 23, SOFT, "ra")

    if timeline:
        chart.text(50, 896, "话题时间线", 32)
    for index, (window, topics, unavailable) in enumerate(timeline):
        x, y = 48+(index % 2)*598, 946+(index//2)*152
        chart.panel((x, y, x+586, y+140))
        chart.text(x+18, y+11, window, 23, GOLD)
        for line, (title, detail, users) in enumerate(topics[:2]):
            speakers = " · " + "、".join(users[:2]) if users else ""
            content = chart.wrap(title + "  " + detail + speakers, 23, 548, 1)
            chart.text(x+18, y+53+line*33, content[0], 23, INK)
        if not topics:
            text = "LLM 话题暂不可用" if unavailable else "没有可提炼的话题"
            chart.text(x+18, y+56, text, 23, MUTED)
        elif unavailable:
            chart.text(x+569, y+13, "部分话题未生成", 20, MUTED, "ra")
    return [png(chart.image)]


def combine_pending(images):
    """Keep pre-upgrade staged pages deliverable as one bounded image."""
    if len(images) == 1:
        return images[0]
    canvas = Image.new("RGB", (WIDTH, 1440), "#0a1427")
    columns = 2 if len(images) <= 4 else 3
    rows = (len(images) + columns - 1) // columns
    cell_w, cell_h = WIDTH // columns, canvas.height // rows
    for index, data in enumerate(images):
        with Image.open(BytesIO(data)) as source:
            page = ImageOps.contain(source.convert("RGB"), (cell_w, cell_h))
            canvas.paste(page, ((index % columns)*cell_w, (index // columns)*cell_h))
    return png(canvas)

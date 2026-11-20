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
        path = font_path(font)
        self.fonts = {size: ImageFont.truetype(path, size) for size in (20, 23, 25, 28, 32, 36, 44, 54, 64, 82)}

        if height is not None:
            self.background(height)

    def background(self, height):
        self.image = Image.new("RGB", (WIDTH, height))
        self.draw = ImageDraw.Draw(self.image)
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

    def wrap(self, text, size, width, limit=None):
        font = self.fonts[size]
        clean = " ".join(str(text).split())
        lines, line = [], ""
        for char in clean:
            if line and (font.getbbox(line + char)[2] if limit is None else font.getlength(line + char)) > width:
                lines.append(line)
                line = ""
            if limit is not None and len(lines) >= limit:
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
    chart = Canvas(None, font)
    group_label = (" ".join(str(group).split()) or "本群") + (" · 手动统计" if manual else " · 每日统计")
    group_lines = chart.wrap(group_label, 25, 600)
    header_extra = 32 * (len(group_lines) - 1)

    top = rankings[:3]
    top_names = [chart.wrap(name, 28, 223) or ["?"] for name, _, _ in top]
    top_extra = 36 * max((len(lines) - 1 for lines in top_names), default=0)
    compact = []
    for name, count, avatar in rankings[3:RANK_LIMIT]:
        width = 234 - chart.fonts[32].getbbox(f"{count:,}")[2]
        compact.append((name, count, avatar, chart.wrap(name, 25, width) or ["?"]))
    compact_rows = [compact[i:i+3] for i in range(0, len(compact), 3)]
    compact_heights = [54 + 32 * (max(len(entry[3]) for entry in row) - 1) for row in compact_rows]

    timeline = []
    for window, topics, unavailable in blocks[:6]:
        wrapped = []
        for title, detail, users in topics:
            speakers = " · " + "、".join(users[:2]) if users else ""
            wrapped.append((chart.wrap(title, 25, 548), chart.wrap(detail + speakers, 23, 548)))
        height = 98 if not wrapped else 52 + sum(
            33 * len(title) + 31 * len(detail) + 12 for title, detail in wrapped
        )
        timeline.append((window, wrapped, unavailable, height))
    timeline_rows = [timeline[i:i+2] for i in range(0, len(timeline), 2)]
    timeline_heights = [max(card[3] for card in row) for row in timeline_rows]

    compact_y = 670 + header_extra + top_extra
    extra = rankings[RANK_LIMIT:]
    after_rankings = compact_y + sum(height + 11 for height in compact_heights)
    timeline_y = after_rankings + (34 if extra else 0)
    height = timeline_y + (50 + sum(height + 12 for height in timeline_heights) if timeline else 0) + 22
    chart.background(height)
    draw = chart.draw
    chart.text(50, 28, "群讯息情报", 64)
    for index, line in enumerate(group_lines):
        chart.text(55, 110 + index * 32, line, 25, GOLD)
    chart.text(1228, 49, f"{sum(hours):,} 条讯息  /  {len(rankings):,} 位发言者", 36, INK, "ra")
    chart.text(1228, 108, f"{start:%m-%d %H:%M} 至 {end:%m-%d %H:%M} · 北京时间", 23, SOFT, "ra")

    shift = header_extra
    chart.panel((48, 166+shift, 1232, 331+shift))
    chart.text(72, 183+shift, "全天发言星轨", 28)
    peak = max(hours, default=0)
    if peak:
        chart.text(1208, 187+shift, f"峰值 {hours.index(peak):02d}:00 · {peak:,} 条", 23, GOLD, "ra")
    for hour, count in enumerate(hours):
        x = 77 + hour * 47
        rise = round(64 * count / peak) if peak else 0
        draw.rounded_rectangle((x, 288+shift-max(4, rise), x+27, 288+shift), 4,
                               fill=GOLD if count and count == peak else "#588dd1" if count else "#30476c")
        if hour % 3 == 0 or hour == 23:
            chart.text(x+13, 310+shift, f"{hour:02}", 20, MUTED, "mm")

    chart.text(49, 354+shift, "群友发言排行", 36)
    chart.text(1230, 367+shift, "按发言条数排列", 23, SOFT, "ra")
    top_count = rankings[0][1] if rankings else 1
    for rank, x, y, color in ((2, 48, 468, SILVER), (1, 446, 421, GOLD), (3, 844, 468, BRONZE)):
        if rank > len(top):
            continue
        name, count, avatar = top[rank-1]
        y += shift
        bottom = 649 + shift + top_extra
        chart.panel((x, y, x+388, bottom), outline=color)
        draw.ellipse((x+16, y+24, x+126, y+134), outline=BORDER, width=2)
        chart.portrait(x+35, y+43, 72, name, avatar, color)
        chart.text(x+140, y+13, f"#{rank:02}", 23, color)
        for index, line in enumerate(top_names[rank-1]):
            chart.text(x+140, y+47+index*36, line, 28)
        chart.text(x+140, y+80+top_extra, f"{count:,}", 54, color)
        chart.text(x+356, y+118+top_extra, "条", 20, SOFT, "ra")
        draw.rounded_rectangle((x+26, bottom-29, x+362, bottom-21), 4, fill=BORDER)
        draw.rounded_rectangle((x+26, bottom-29, x+26+max(6, round(336*count/top_count)), bottom-21), 4, fill=color)
    if not rankings:
        chart.panel((48, 419+shift, 1232, 649+shift))
        chart.text(640, 533+shift, "本时段暂无发言", 36, SOFT, "mm")

    rank = 4
    y = compact_y
    for row, height in zip(compact_rows, compact_heights):
        for column, (name, count, avatar, lines) in enumerate(row):
            x = 48 + column * 398
            chart.panel((x, y, x+388, y+height))
            chart.text(x+15, y+14, f"{rank:02}", 23, SOFT)
            chart.portrait(x+62, y+10, 34, name, avatar)
            for index, line in enumerate(lines):
                chart.text(x+112, y+13+index*32, line, 25)
            chart.text(x+366, y+9, f"{count:,}", 32, INK, "ra")
            rank += 1
        y += height + 11
    if extra:
        chart.text(1230, y+5, f"其余 {len(extra):,} 位 · 合计 {sum(row[1] for row in extra):,} 条", 23, SOFT, "ra")

    if timeline_rows:
        chart.text(50, timeline_y, "话题时间线", 32)
    y = timeline_y + 50
    for row, height in zip(timeline_rows, timeline_heights):
        for column, (window, topics, unavailable, _) in enumerate(row):
            x = 48 + column * 598
            chart.panel((x, y, x+586, y+height))
            chart.text(x+18, y+11, window, 23, GOLD)
            if not topics:
                status = "LLM 话题暂不可用" if unavailable else "没有可提炼的话题"
                chart.text(x+18, y+52, status, 23, MUTED)
            elif unavailable:
                chart.text(x+569, y+13, "部分话题未生成", 20, MUTED, "ra")
            cursor = y + 45
            for title, detail in topics:
                for line in title:
                    chart.text(x+18, cursor, line, 25)
                    cursor += 33
                for line in detail:
                    chart.text(x+18, cursor, line, 23, SOFT)
                    cursor += 31
                cursor += 12
        y += height + 12
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

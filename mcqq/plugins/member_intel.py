"""Build and render one member portrait using only evidence from the current group."""
import asyncio
from datetime import datetime
import hashlib
import json
import logging
import re
import time

import aiohttp

from ..group_report_image import Canvas, GOLD, INK, MUTED, SOFT, png
from ..group_reports import BEIJING, fetch_avatars, midnight
from ..llm_context import chat_text, context_batches

log = logging.getLogger(__name__)


def select_evidence(rows, target, skill):
    """Scan the entire day for target messages, direct mentions and nearby turns."""
    indexes = set()
    target_mentions = re.compile(r"<@!?" + re.escape(target) + r">", re.I)
    neighbors = skill["context_neighbors"]
    window = skill["context_window_seconds"]
    for index, (created, member, _, raw, _) in enumerate(rows):
        if member == target:
            for nearby in range(max(0, index-neighbors), min(len(rows), index+neighbors+1)):
                if abs(rows[nearby][0] - created) <= window:
                    indexes.add(nearby)
        elif target_mentions.search(raw):
            indexes.add(index)
    return [rows[index] for index in sorted(indexes)]


async def examine(ai, batches, prompt, limit):
    results = await asyncio.gather(*(ai.analyze_json(prompt, batch, max_tokens=900) for batch in batches),
                                   return_exceptions=True)
    notes = []
    for result in results:
        if isinstance(result, Exception):
            raise result
        raw = result.get("notes")
        if not isinstance(raw, str):
            raise ValueError("invalid evidence notes")
        if text := ai.check(raw.strip()[:limit]):
            notes.append(text)
    return list(dict.fromkeys(notes))


async def handle(ai, settings, group, target, received, config):
    rows, memories, name = await asyncio.to_thread(ai.history.member_evidence, group, target,
                                                  midnight(received).timestamp(), received.timestamp())
    target_rows = [row for row in rows if row[1] == target]
    if not target_rows and not memories:
        return "本群还没有这位群友的发言缓存或向量记忆。"
    skill = config["skill"]
    evidence_rows = select_evidence(rows, target, skill)
    ordered = []
    target_texts = []
    labels_by_row = {row: f"M{index:02d}" for index, row in enumerate(target_rows, 1)}
    references = {key: datetime.fromtimestamp(row[0], BEIJING).strftime("%H:%M")
                  for row, key in labels_by_row.items()}
    participants = {member: f"群友{index}" for index, member in enumerate(
        dict.fromkeys(row[1] for row in evidence_rows if row[1] != target), 1)}
    for row in evidence_rows:
        created, member, _, raw, _ = row
        text = chat_text(raw, ai.check)
        if text and re.match(r"^(?:@群友\s*)?/群友情报(?:\s|$)", text.strip()):
            continue
        speaker = "目标 " + labels_by_row[row] if member == target else participants[member]
        value = "[文字已过滤]" if text is None else text or "[无文本讯息]"
        ordered.append((datetime.fromtimestamp(created, BEIJING).strftime("%H:%M:%S"), speaker, value))
        if member == target and text and not text.lstrip().startswith("/"):
            target_texts.append(text)
    for index, memory in enumerate(memories, 1):
        if text := chat_text(memory, ai.check):
            key = f"H{index:02d}"
            ordered.append(("记忆", "目标 " + key, text))
            references[key] = "历史记忆"
    result = {}
    group_context = {"cached_messages": len(rows), "speakers": len({row[1] for row in rows})}
    if target_texts or memories:
        try:
            async with asyncio.timeout(skill["timeout_seconds"]):
                result = await cached_analysis(ai, group, target, received, ordered, target_texts, memories,
                                               group_context, skill)
        except (aiohttp.ClientError, TimeoutError, ValueError, TypeError, KeyError, IndexError) as error:
            log.warning("Member intel LLM unavailable (%s)", type(error).__name__)

    def field(key):
        raw = result.get(key)
        return (ai.check(" ".join(raw.split()[:120])[:260]) or "") if isinstance(raw, str) else ""

    def observations(key):
        shown = []
        entries = result.get(key)
        for item in entries if isinstance(entries, list) else []:
            if not isinstance(item, dict):
                continue
            title, detail, cited = item.get("title"), item.get("detail"), item.get("evidence")
            if not isinstance(title, str) or not isinstance(detail, str) or not isinstance(cited, list):
                continue
            title, detail = ai.check(title.strip()[:30]), ai.check(detail.strip()[:160])
            links = list(dict.fromkeys(ref for ref in cited if isinstance(ref, str) and ref in references))[:3]
            if title and detail and links:
                shown.append((title, detail, "、".join(f"{ref} {references[ref]}" for ref in links)))
        return shown[:3]

    labels = result.get("labels")
    labels = list(dict.fromkeys(text for label in (labels if isinstance(labels, list) else [])
                                if isinstance(label, str) and (text := ai.check(label.strip()[:12]))))[:5]
    phrases = result.get("catchphrases")
    phrases = list(dict.fromkeys(phrase.strip() for phrase in (phrases if isinstance(phrases, list) else [])
                                if isinstance(phrase, str) and 2 <= len(phrase.strip()) <= 16
                                and ai.check(phrase.strip()) == phrase.strip()
                                and sum(phrase.strip() in text for text in target_texts) >= 2))[:3]
    mbti, basis = field("mbti").upper(), field("basis")
    traits, interests, style = field("traits"), field("interests"), field("style")
    summary = field("summary") or " ".join(value for value in (traits, interests, style) if value)
    strengths, friction = observations("strengths"), observations("friction")
    stats_only = not (traits or interests or style)
    if not re.fullmatch(r"[EI][NS][TF][JP]", mbti) or not basis or (len(target_texts) < 6 and len(memories) < 2):
        mbti, basis = "", "可核对的发言习惯不足，暂不猜测。"
    if stats_only:
        hours = len({datetime.fromtimestamp(row[0], BEIJING).hour for row in target_rows})
        labels = ["本地统计", "按本群发言整理"]
        traits = f"今日收到 {len(target_rows):,} 条发言，分布在 {hours} 个小时时段。"
        interests = "暂未生成话题分析。"
        if target_texts:
            avg = round(sum(map(len, target_texts)) / len(target_texts))
            questions = sum("?" in text or "？" in text for text in target_texts)
            style = f"有 {len(target_texts):,} 条可分析文字，平均约 {avg:,} 字，其中 {questions:,} 条带问号。"
        mbti, phrases = "", []
        basis = "本次根据缓存做本地统计，未生成性格推测。"
        summary = f"{traits} {style} 本次没有足够的模型结果来判断其偏好、长处或沟通摩擦。"
    name = next((row[2] for row in reversed(target_rows) if row[2]), name) or "这位群友"
    name = ai.check(name) or "这位群友"
    urls = [row[4] for row in reversed(target_rows) if row[4]]
    if fallback := await asyncio.to_thread(ai.history.avatar_url, group, target):
        urls.append(fallback)
    key = f"{group}:{target}"
    avatar = (await fetch_avatars({key: list(dict.fromkeys(urls))[:3]}, ai.history)).get(key)
    return await asyncio.to_thread(render_portrait, received, name, avatar, len(target_rows), len(memories),
                                   traits, interests, style, phrases, mbti, basis,
                                   settings.get("daily_report_font"), stats_only=stats_only, labels=labels,
                                   strengths=strengths, friction=friction, summary=summary)


async def cached_analysis(ai, group, target, received, ordered, target_texts, memories, group_context, skill):
    policy = await asyncio.to_thread(ai.feature_policy.check, group, "llm", consume=False)
    if not policy["allowed"]:
        return {}
    ttl = skill.get("cache_ttl_seconds", 0)
    shared_cache = ttl and getattr(ai.history, "shared_cache", False)
    if ttl:
        fingerprint = json.dumps([group, target, received.astimezone(BEIJING).date().isoformat(),
                                  ai.config.get("model"), ai.config.get("output_language"), skill, ordered],
                                 ensure_ascii=False, sort_keys=True)
        key = hashlib.sha256(fingerprint.encode()).hexdigest()
        if shared_cache:
            cached = await asyncio.to_thread(ai.history.get_cached, "member-intel-v1", key)
            try:
                result = json.loads(cached) if cached else None
                if isinstance(result, dict):
                    return result
            except (ValueError, TypeError):
                pass
        else:
            local_cache = getattr(ai, "_member_intel_cache", None)
            if local_cache is None:
                ai._member_intel_cache = local_cache = {}
            if (cached := local_cache.get(key)) and cached[0] > time.monotonic():
                return cached[1]
    if not ai.configured() or time.monotonic() < ai.unavailable_until:
        return {}
    result = await analyze(ai, ordered, target_texts, memories, group_context, skill)
    if ttl and any(isinstance(result.get(field), str) and result[field].strip()
                   for field in ("traits", "interests", "style")):
        if shared_cache:
            await asyncio.to_thread(ai.history.set_cached, "member-intel-v1", key,
                                    json.dumps(result, ensure_ascii=False), ttl)
        else:
            if key not in local_cache and len(local_cache) >= 64:
                local_cache.pop(next(iter(local_cache)))
            local_cache[key] = (time.monotonic() + ttl, result)
    return result


async def analyze(ai, ordered, target_texts, memories, group_context, skill):
    batches = list(context_batches(ordered, budget=skill["context_batch_chars"],
                                  max_rows=skill["context_batch_rows"]))
    if not batches:
        return {}
    if len(batches) == 1:
        evidence = {"chat_evidence": json.loads(batches[0])}
    else:
        notes = await examine(ai, batches, skill["excerpt"], 450)
        while sum(map(len, notes)) > 9000:
            batches = list(context_batches((("证据", note) for note in notes), budget=6500))
            notes = await examine(ai, batches, skill["merge"], 650)
        evidence = {"notes": notes}
    evidence.update(recent_examples=[text[-500:] for text in target_texts[-12:]],
                    target_messages=len(target_texts), member_memories=len(memories), group_context=group_context)
    data = json.dumps(evidence, ensure_ascii=False)
    try:
        return await ai.analyze_json(skill["portrait"], data, max_tokens=skill["result_max_tokens"])
    except json.JSONDecodeError:
        return await ai.analyze_json(skill["portrait"] + " 回复从 { 开始，到 } 结束，必须符合 JSON 语法。",
                                     data, max_tokens=skill["result_max_tokens"])


def render_portrait(moment, name, avatar, count, memories, traits, interests, style, phrases, mbti, basis, font,
                    *, stats_only=False, labels=(), strengths=(), friction=(), summary=""):
    image = Canvas(1830, font)

    def wrap(text, size, width, limit):
        lines = image.wrap(text, size, width-size, limit)
        for index in range(1, len(lines)):
            if marks := re.match(r"^[，。！？：；、）》】]+", lines[index]):
                lines[index-1] += marks[0]
                lines[index] = lines[index][len(marks[0]):]
        return [line for line in lines if line]

    image.text(52, 33, "群友情报", 64)
    source = " · 本地统计" if stats_only else " · 本群观察"
    image.text(1226, 56, moment.strftime("%Y-%m-%d") + source, 25, MUTED, "ra")
    image.panel((48, 143, 1232, 330), outline="#567bba")
    image.portrait(82, 177, 112, name, avatar, GOLD)
    image.text(221, 174, (image.wrap(name, 54, 625, 1) or ["这位群友"])[0], 54)
    image.text(224, 252, f"今日缓存 {count:,} 条  ·  历史记忆 {memories:,} 条", 28, SOFT)
    image.text(1198, 191, "MBTI · 趣味推测", 23, GOLD, "ra")
    image.text(1198, 231, mbti or "待观察", 44, INK, "ra")

    image.panel((48, 352, 1232, 467))
    image.text(74, 367, "核心标签", 32, GOLD)
    tags = "  ·  ".join(labels) or "现有资料还不足以提炼稳定标签"
    for line, value in enumerate(wrap(tags, 25, 1100, 2)):
        image.text(75, 417+line*24, value, 25, INK)

    cards = (("群内特点", traits), ("常聊与喜好", interests),
             ("表达习惯", style), ("重复用语", "、".join(phrases)))
    for index, (title, text) in enumerate(cards):
        x, y = 48 + index % 2 * 602, 490 + index // 2 * 214
        image.panel((x, y, x+582, y+193))
        image.text(x+25, y+14, title, 32, GOLD)
        for line, value in enumerate(wrap(text or "资料不足", 25, 528, 4)):
            image.text(x+25, y+65+line*28, value, 25, INK)

    for x, heading, observations in ((48, "可观察的长处", strengths), (650, "可能的沟通摩擦", friction)):
        image.panel((x, 921, x+582, 1417))
        image.text(x+25, 938, heading, 32, GOLD)
        if not observations:
            image.text(x+25, 1001, "当前聊天依据不足", 25, MUTED)
        for index, (title, detail, refs) in enumerate(observations):
            y = 993 + index*135
            title = image.wrap(title, 25, 528, 1)
            if title:
                image.text(x+25, y, title[0], 25, SOFT)
            for line, value in enumerate(wrap(detail, 23, 528, 3)):
                image.text(x+25, y+32+line*25, value, 23, INK)
            for value in image.wrap("发言依据  " + refs, 20, 528, 1):
                image.text(x+25, y+110, value, 20, MUTED)

    image.panel((48, 1440, 1232, 1602))
    image.text(74, 1453, "MBTI 推测依据", 32, GOLD)
    for line, value in enumerate(wrap(basis, 28, 1100, 2)):
        image.text(75, 1504+line*34, value, 28)
    image.panel((48, 1623, 1232, 1780))
    image.text(74, 1639, "本次情报总结", 32, GOLD)
    for line, value in enumerate(wrap(summary or "当前资料不足。", 25, 1100, 3)):
        image.text(75, 1690+line*26, value, 25)
    image.text(51, 1791, "来自本群可用发言，仅供娱乐", 20, MUTED)
    return png(image.image)

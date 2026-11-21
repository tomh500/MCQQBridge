"""Chunk structured chat evidence without truncating the input history."""
import json
import re


def chat_text(raw, check):
    return check(re.sub(r"<@!?[^>]+>", "@群友", raw))


def context_batches(records, *, budget=7000, max_rows=30):
    """Split long records and keep all pieces in chronological order."""
    batch, size = [], 2
    for record in records:
        for offset in range(0, len(record[-1]), 900):
            entry = json.dumps((*record[:-1], record[-1][offset:offset + 900]), ensure_ascii=False)
            if batch and (size + len(entry) + 1 > budget or len(batch) >= max_rows):
                yield "[" + ",".join(batch) + "]"
                batch, size = [], 2
            batch.append(entry)
            size += len(entry) + 1
    if batch:
        yield "[" + ",".join(batch) + "]"


async def complete_json(ai, instructions, evidence, *, max_tokens):
    answer = await ai.complete([
        {"role": "system", "content": instructions},
        {"role": "user", "content": evidence},
    ], max_tokens=max_tokens)
    if not isinstance(answer, str):
        raise ValueError("expected JSON text")
    answer = re.sub(r"\A```(?:json)?\s*|\s*```\Z", "", answer.strip(), flags=re.I)
    result = json.loads(answer)
    if not isinstance(result, dict):
        raise ValueError("expected a JSON object")
    return result

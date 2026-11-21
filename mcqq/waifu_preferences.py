"""Sparse preference vectors and unbiased weighted selection."""
import math
import secrets

MAX_POINTS = 2_147_483_647


def features(entry):
    tags = entry.get("features") or []
    return sorted({str(t)[:100] for t in tags if isinstance(t, str) and t.strip()})


def learn(vector, entry):
    result = dict(vector or {})
    for tag in features(entry):
        result[tag] = min(int(result.get(tag, 0)) + 1, MAX_POINTS)
    return result


def similarity(vector, entry):
    tags = features(entry)
    if not tags or not vector:
        return 0.0
    values = [max(0, int(v)) for k, v in vector.items() if not k.startswith("_")]
    norm = math.sqrt(sum(v * v for v in values) * len(tags))
    return sum(max(0, int(vector.get(tag, 0))) for tag in tags) / norm if norm else 0.0


def pick(entries, vector=None):
    if not entries:
        raise ValueError("empty character catalog")
    vector = vector or {}
    # Each learned confirmation increases the matching score by 2.5%;
    # probabilities are normalized across every eligible character.
    count = int(vector.get("_confirmations", 0))
    weights = [1.0 + .025 * count * similarity(vector, entry) for entry in entries]
    point = secrets.randbelow(1 << 53) / (1 << 53) * sum(weights)
    for entry, weight in zip(entries, weights):
        point -= weight
        if point < 0:
            return entry
    return entries[-1]

import math
import struct
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Match:
    person_id: str
    similarity: float


def normalize_embedding(values: Iterable[float]) -> list[float]:
    embedding = [float(value) for value in values]
    magnitude = math.sqrt(sum(value * value for value in embedding))
    if not embedding or magnitude == 0.0:
        raise ValueError("Face embedding must contain non-zero values")
    return [value / magnitude for value in embedding]


def encode_embedding(values: Iterable[float]) -> bytes:
    embedding = normalize_embedding(values)
    return struct.pack(f"<{len(embedding)}f", *embedding)


def decode_embedding(value: bytes) -> list[float]:
    if not value or len(value) % 4:
        raise ValueError("Stored embedding has an invalid byte length")
    return list(struct.unpack(f"<{len(value) // 4}f", value))


def find_best_match(
    probe: Iterable[float], templates: Iterable[tuple[str, bytes]], threshold: float
) -> Match | None:
    normalized_probe = normalize_embedding(probe)
    best: Match | None = None
    for person_id, encoded in templates:
        enrolled = decode_embedding(encoded)
        if len(enrolled) != len(normalized_probe):
            continue
        similarity = sum(left * right for left, right in zip(normalized_probe, enrolled, strict=True))
        if best is None or similarity > best.similarity:
            best = Match(person_id=person_id, similarity=similarity)
    return best if best is not None and best.similarity >= threshold else None
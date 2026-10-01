"""Embeddings for RAG and semantic-similarity evaluation.

`hashing` is a deterministic lexical embedding (feature hashing over word n-grams) intended for local
development without an embedding API. It is real lexical retrieval, not semantic; production deployments
should set ISOCLINE_EMBEDDING_PROVIDER=openai_compatible or ollama.
"""
from __future__ import annotations

import hashlib
import math
import re

import httpx

from isocline.core.config import get_settings

_WORD = re.compile(r"[a-z0-9]+")


def _hashing(text: str, dim: int) -> list[float]:
    v = [0.0] * dim
    words = _WORD.findall(text.lower())
    feats = words + [f"{a}_{b}" for a, b in zip(words, words[1:])]
    for f in feats:
        h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
        v[h % dim] += 1.0 if (h >> 63) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _fit(vec: list[float], dim: int) -> list[float]:
    return vec[:dim] + [0.0] * max(0, dim - len(vec))


async def embed(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    if not texts:
        return []
    if s.embedding_provider == "hashing":
        return [_hashing(t, s.embedding_dim) for t in texts]
    async with httpx.AsyncClient(timeout=60) as c:
        if s.embedding_provider == "ollama":
            r = await c.post(f"{s.embedding_base_url.rstrip('/')}/api/embed", json={"model": s.embedding_model, "input": texts})
            r.raise_for_status()
            return [_fit(e, s.embedding_dim) for e in r.json()["embeddings"]]
        headers = {"Authorization": f"Bearer {s.embedding_api_key}"} if s.embedding_api_key else {}
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            r = await c.post(f"{s.embedding_base_url.rstrip('/')}/embeddings", headers=headers,
                             json={"model": s.embedding_model, "input": texts[i:i + 64]})
            r.raise_for_status()
            out += [_fit(d["embedding"], s.embedding_dim) for d in sorted(r.json()["data"], key=lambda d: d["index"])]
        return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)

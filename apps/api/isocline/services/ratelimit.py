"""Fixed-window rate limiting backed by Redis, with an in-process fallback when Redis is unreachable
(development/tests). Limits are enforced per client key (user id, API key prefix or IP)."""
from __future__ import annotations

import time
from collections import defaultdict

from isocline.core.config import get_settings
from isocline.core.logging import log

_local: dict[str, list] = defaultdict(lambda: [0, 0.0])
_redis = None
_redis_failed_at = 0.0


async def _client():
    global _redis, _redis_failed_at
    if _redis is None and time.monotonic() - _redis_failed_at > 30:
        try:
            import redis.asyncio as redis
            _redis = redis.from_url(get_settings().redis_url, socket_connect_timeout=0.3, socket_timeout=0.3)
            await _redis.ping()
        except Exception:
            _redis, _redis_failed_at = None, time.monotonic()
    return _redis


async def hit(key: str, limit: int, window: int = 60) -> bool:
    """Returns True if the request is allowed."""
    global _redis, _redis_failed_at
    bucket = int(time.time() // window)
    r = await _client()
    if r is not None:
        try:
            k = f"isocline:rl:{key}:{bucket}"
            n = await r.incr(k)
            if n == 1:
                await r.expire(k, window + 1)
            return n <= limit
        except Exception as e:
            log.warning("rate_limit_redis_failed", error=str(e))
            _redis, _redis_failed_at = None, time.monotonic()
    slot = _local[key]
    if slot[1] != bucket:
        slot[0], slot[1] = 0, bucket
    slot[0] += 1
    return slot[0] <= limit


def reset_local() -> None:
    _local.clear()

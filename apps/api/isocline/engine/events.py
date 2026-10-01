"""Live event delivery. Events are persisted in run_events (source of truth) and fanned out through Redis pub/sub."""
from __future__ import annotations

import json
from collections import defaultdict

EVENT_TYPES = [
    "RUN_STARTED", "RUN_RESUMED", "NODE_QUEUED", "NODE_STARTED", "NODE_RETRY", "NODE_FALLBACK", "TOOL_STARTED",
    "TOOL_COMPLETED", "NODE_COMPLETED", "NODE_FAILED", "NODE_SKIPPED", "NODE_WAITING", "LOOP_ITERATION",
    "BUDGET_WARNING", "RUN_WAITING", "RUN_COMPLETED", "RUN_FAILED", "RUN_CANCELLED",
]


def channel(run_id: str) -> str:
    return f"isocline:run:{run_id}"


class EventBus:
    async def publish(self, run_id: str, event: dict) -> None: ...


class NullBus(EventBus):
    async def publish(self, run_id, event):
        return None


class MemoryBus(EventBus):
    """In-process bus used by tests."""

    def __init__(self):
        self.events: dict[str, list[dict]] = defaultdict(list)

    async def publish(self, run_id, event):
        self.events[run_id].append(event)


class RedisBus(EventBus):
    def __init__(self, url: str):
        import redis.asyncio as redis
        self.redis = redis.from_url(url)

    async def publish(self, run_id, event):
        await self.redis.publish(channel(run_id), json.dumps(event, default=str))


async def subscribe(url: str, run_id: str):
    """Async generator of live events for one run."""
    import redis.asyncio as redis
    r = redis.from_url(url)
    ps = r.pubsub()
    await ps.subscribe(channel(run_id))
    try:
        while True:
            msg = await ps.get_message(ignore_subscribe_messages=True, timeout=15)
            if msg is None:
                yield None  # keepalive tick
                continue
            yield json.loads(msg["data"])
    finally:
        await ps.unsubscribe(channel(run_id))
        await ps.aclose()
        await r.aclose()

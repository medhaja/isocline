"""Shared HTTP helper for provider adapters."""
import json

import httpx

from .base import ProviderError, classify_http


async def post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10)) as c:
            r = await c.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as e:
        raise ProviderError("timeout", f"Timed out after {timeout}s") from e
    except httpx.TransportError as e:
        raise ProviderError("unavailable", f"Could not reach provider: {e.__class__.__name__}") from e
    if r.status_code >= 400:
        err = classify_http(r.status_code, r.text)
        if r.status_code == 429:
            ra = r.headers.get("retry-after")
            try:
                err.retry_after = float(ra) if ra else None
            except ValueError:
                pass
        raise err
    try:
        return r.json()
    except json.JSONDecodeError as e:
        raise ProviderError("unavailable", "Provider returned invalid JSON") from e


async def get_json(url: str, headers: dict, timeout: float = 15) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(url, headers=headers)
    except httpx.TimeoutException as e:
        raise ProviderError("timeout", "Timed out listing models") from e
    except httpx.TransportError as e:
        raise ProviderError("unavailable", f"Could not reach provider: {e.__class__.__name__}") from e
    if r.status_code >= 400:
        raise classify_http(r.status_code, r.text)
    return r.json()


def parse_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {"value": v}
    except json.JSONDecodeError:
        return {"_raw": raw}

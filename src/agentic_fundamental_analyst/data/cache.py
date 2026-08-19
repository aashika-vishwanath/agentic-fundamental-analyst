import functools
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, TypeVar

import diskcache

T = TypeVar("T")

_CACHE_DIR = Path.home() / ".cache" / "agentic-fundamental-analyst"
_cache = diskcache.Cache(str(_CACHE_DIR))


def _make_key(source: str, func_name: str, args: tuple, kwargs: dict) -> str:
    payload = {"source": source, "func": func_name, "args": args, "kwargs": kwargs}
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def cached(
    source: str, ttl: timedelta
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Wrap an async fetch function so repeated calls with the same args within
    `ttl` are served from disk instead of re-hitting the network. Cache key
    includes every positional/keyword arg, not just a ticker, so distinct
    query params never collide.
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            key = _make_key(source, func.__name__, args, kwargs)
            if key in _cache:
                return _cache[key]  # type: ignore[return-value]
            result = await func(*args, **kwargs)
            _cache.set(key, result, expire=ttl.total_seconds())
            return result

        return wrapper

    return decorator


def clear_cache() -> None:
    _cache.clear()

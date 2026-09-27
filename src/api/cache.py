import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

DEFAULT_TTL_SECONDS = 300


class TTLCache:
    """Thread-safe mapping of ``(key) -> (value, expires_at)``."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._store: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_set(
        self, key: Any, factory: Callable[[], T], ttl_seconds: int | None = None
    ) -> T:
        """Return the cached value for ``key``, computing it when missing."""
        ttl = self.ttl_seconds if ttl_seconds is None else ttl_seconds
        now = time.monotonic()
        with self._lock:
            hit = self._store.get(key)
            if hit is not None and hit[0] > now:
                return hit[1]

        value = factory()

        with self._lock:
            self._store[key] = (time.monotonic() + ttl, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

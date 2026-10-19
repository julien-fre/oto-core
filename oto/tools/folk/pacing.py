"""Request pacing for the Folk API, shared process-wide per key.

Folk applies two policies (developer.folk.app/api-reference/rate-limits,
2026-10-19): a burst of 20 requests per 2-second window (10 per second on
average) and 600 requests per minute. The default spacing below sends at most
8 requests per second: under the burst average, under the minute cap (480),
with a margin for other traffic on the same account. Folk counts per USER, not
per key; a client only knows its key, so the pacing is keyed by a SHA-256
fingerprint of the key (never the key itself) and two keys of one user are
paced apart — the 429 retry of the client remains the backstop.

The state lives at module level: the consumer builds a client per call, often
from a thread pool, so a pacer held by the instance would never be shared.
Each request reserves, under a lock, the next start for its key, then sleeps
until that start outside the lock.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Callable, Dict

#: ~8 requests per second, under Folk's burst policy (20 per 2 s).
DEFAULT_MIN_INTERVAL_S = 0.125


def key_fingerprint(api_key: str) -> str:
    """Stable key for an API key: its SHA-256 digest, never the key."""
    return hashlib.sha256(f"folk|{api_key}".encode()).hexdigest()


class FolkPacer:
    """Spaces request starts per key by a minimum interval, across threads.

    `clock` (monotonic seconds) and `sleep` are injectable so that tests can
    drive time without waiting.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        # fingerprint -> earliest start of the next request
        self._next_at: Dict[str, float] = {}

    def reserve(self, api_key: str, min_interval_s: float) -> float:
        """Reserve the next start for `api_key` and return how long to wait."""
        if min_interval_s < 0:
            raise ValueError("min_interval_s must be >= 0")
        fingerprint = key_fingerprint(api_key)
        with self._lock:
            now = self._clock()
            start = max(now, self._next_at.get(fingerprint, now))
            self._next_at[fingerprint] = start + min_interval_s
        return start - now

    def acquire(self, api_key: str, min_interval_s: float) -> None:
        """Wait for this key's next start, reserved under the lock."""
        delay = self.reserve(api_key, min_interval_s)
        if delay > 0:
            self._sleep(delay)


#: The process-wide pacer every `FolkClient` uses unless given its own.
SHARED_PACER = FolkPacer()

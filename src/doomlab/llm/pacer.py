"""Space request starts evenly so we stay under the endpoint's rate limit.

Purdue documents 60 requests/minute/user, but measured on 2026-09-25 (data/rate_limit_probe.json) the 21st
request inside any ~60 s window is refused, whatever the spacing; exactly 20/min sits on the edge and 18/min
is sustainable. Even spacing keeps us under that rolling window at all times.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class RequestPacer:
    def __init__(
        self,
        per_minute: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = 60.0 / per_minute
        self._clock, self._sleep = clock, sleep
        self._next: float | None = None
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        """Return when the next request may start. Waiting counts against the caller's time budget."""
        async with self._lock:
            now = self._clock()
            if self._next is not None and now < self._next:
                await self._sleep(self._next - now)
                now = self._next
            self._next = now + self._interval

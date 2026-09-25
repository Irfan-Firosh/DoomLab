"""Space request starts evenly so we stay under the endpoint's rate limit.

Purdue publishes 60 requests/minute/user; we pace at 20 (one start every 3 s). Even spacing, rather than a
rolling-window count, also keeps us under any shorter window the server may enforce: a live run was refused
after 20 requests in 8 seconds, well inside one minute.
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

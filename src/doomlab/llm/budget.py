"""Per-episode LLM spending caps: calls, tokens and wall-clock seconds."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

DEFAULT_MAX_CALLS = 40
DEFAULT_MAX_TOKENS = 40_000
DEFAULT_MAX_SECONDS = 300.0


class BudgetExhausted(Exception):
    """Raised by `check()` when the next call would exceed a cap."""


@dataclass
class Budget:
    max_calls: int = DEFAULT_MAX_CALLS
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_seconds: float = DEFAULT_MAX_SECONDS
    calls: int = 0
    tokens: int = 0
    tokens_known: bool = True  # False once any reply lacked usage: token totals are then a lower bound
    _started: float | None = field(default=None, repr=False)

    def check(self) -> None:
        """Call before each LLM request. Starts the clock on first use."""
        if self._started is None:
            self._started = time.monotonic()
        if self.calls >= self.max_calls:
            raise BudgetExhausted(f"calls: used {self.calls} of {self.max_calls}")
        if self.tokens >= self.max_tokens:
            raise BudgetExhausted(f"tokens: used {self.tokens} of {self.max_tokens}")
        elapsed = time.monotonic() - self._started
        if elapsed >= self.max_seconds:
            raise BudgetExhausted(f"seconds: {elapsed:.0f} of {self.max_seconds:.0f}")

    def record(self, *, tokens: int | None) -> None:
        self.calls += 1
        if tokens is None:
            self.tokens_known = False
        else:
            self.tokens += tokens

"""Append-only JSONL trace: one event per line, flushed as it happens so a crash loses nothing."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _jsonable(value: Any) -> Any:
    if hasattr(value, "item"):  # numpy scalars
        return value.item()
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"cannot serialise {type(value).__name__}")


class TraceWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("a", encoding="utf-8")
        self._t0 = time.monotonic()

    def __enter__(self) -> TraceWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def write(self, event: str, **fields: Any) -> None:
        record = {"event": event, "t": round(time.monotonic() - self._t0, 3), **fields}
        self._file.write(json.dumps(record, default=_jsonable) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()

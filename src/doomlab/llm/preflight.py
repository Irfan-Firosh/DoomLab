"""`doomlab preflight`: verify the model endpoint behaves as the design assumes, and record the evidence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import vizdoom

from doomlab.config import ConfigError, Settings
from doomlab.llm.client import ChatResult, LLMError, RCACClient

MAX_TOKENS = 512
TEMPERATURE = 0.0

PROBE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "turn_to",
            "description": "Turn toward a visible target by id",
            "parameters": {
                "type": "object",
                "properties": {"target_id": {"type": "integer"}},
                "required": ["target_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "attack",
            "description": "Fire the weapon",
            "parameters": {
                "type": "object",
                "properties": {"burst": {"type": "integer", "minimum": 1, "maximum": 5}},
                "required": ["burst"],
            },
        },
    },
]
PROBE_MESSAGES = [
    {
        "role": "user",
        "content": "You see enemy id 7 at 25 degrees left, not centered. Ammo 26. Choose exactly one tool call.",
    }
]


@dataclass(frozen=True)
class Decoding:
    """Model settings frozen by a passing preflight. Every episode in an experiment uses the same ones."""

    model_id: str
    temperature: float
    max_tokens: int
    disable_thinking: bool


def load_frozen_decoding(path: Path, model_id: str) -> Decoding:
    """Read decoding from preflight.json; refuse if preflight failed or was run for a different model."""
    if not path.exists():
        raise ConfigError(f"{path} not found; run `doomlab preflight` first")
    report = json.loads(path.read_text())
    if not report.get("ok"):
        raise ConfigError(f"last preflight did not pass ({path}); fix it and rerun `doomlab preflight`")
    if report.get("model_id") != model_id:
        raise ConfigError(
            f"preflight was run for {report.get('model_id')!r} but RCAC_MODEL is {model_id!r}; rerun `doomlab preflight`"
        )
    frozen = report["decoding_frozen"]
    return Decoding(
        model_id=model_id,
        temperature=float(frozen["temperature"]),
        max_tokens=int(frozen["max_tokens"]),
        disable_thinking=frozen["thinking"] == "off",
    )


def interval_overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Seconds during which both [start, end] intervals were in flight."""
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def _call_summary(result: ChatResult) -> dict[str, Any]:
    first = result.tool_calls[0] if result.tool_calls else None
    return {
        "ok": first is not None,
        "example_call": {"name": first.name, "arguments": first.arguments} if first else None,
        "latency_s": round(result.latency_s, 3),
        "reasoning_present": result.reasoning_present,
        "usage": result.usage,
    }


async def _probe(client: RCACClient, *, disable_thinking: bool) -> ChatResult:
    return await client.chat(
        PROBE_MESSAGES,
        tools=PROBE_TOOLS,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        disable_thinking=disable_thinking,
    )


def _completion_tokens(result: ChatResult) -> int | None:
    return (result.usage or {}).get("completion_tokens")


async def run_preflight(client: RCACClient, settings: Settings, out_path: Path) -> dict[str, Any]:
    """Run every check, write the report to `out_path`, and return it. Never records the API key."""
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "endpoint": settings.base_url,
        "model_id": settings.model_id,
        "vizdoom_version": vizdoom.__version__,
        "ok": False,
        "error": None,
    }
    try:
        available = await client.list_models()
        report["model_listed"] = settings.model_id in available
        if not report["model_listed"]:
            family = settings.model_id.split(":")[0].rstrip("0123456789.")
            similar = [m for m in available if m.startswith(family)] or available[:10]
            report["error"] = {
                "kind": "model_not_listed",
                "message": f"{settings.model_id!r} is not offered by the endpoint; similar: {similar}",
            }
            return _write(report, out_path)

        default = await _probe(client, disable_thinking=False)
        report["tool_calling"] = _call_summary(default)

        switched = await _probe(client, disable_thinking=True)
        thinking_off = not switched.reasoning_present and bool(switched.tool_calls)
        report["thinking"] = {
            "disable_attempted": "chat_template_kwargs.enable_thinking=false",
            "disabled": thinking_off,
            "completion_tokens_default": _completion_tokens(default),
            "completion_tokens_switched": _completion_tokens(switched),
            "switched_call": _call_summary(switched),
        }
        report["usage_reported"] = default.usage is not None and switched.usage is not None

        a, b = await asyncio.gather(
            _probe(client, disable_thinking=thinking_off),
            _probe(client, disable_thinking=thinking_off),
        )
        report["overlap_probe"] = {
            "overlap_s": round(interval_overlap((a.started, a.finished), (b.started, b.finished)), 3),
            "latencies_s": [round(a.latency_s, 3), round(b.latency_s, 3)],
            "concurrent": interval_overlap((a.started, a.finished), (b.started, b.finished)) > 0,
        }
        report["decoding_frozen"] = {
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "thinking": "off" if thinking_off else "on",
        }
        report["ok"] = bool(report["model_listed"] and report["tool_calling"]["ok"])
    except LLMError as exc:
        report["error"] = {"kind": exc.kind, "message": str(exc)}
    return _write(report, out_path)


def _write(report: dict[str, Any], out_path: Path) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n")
    return report

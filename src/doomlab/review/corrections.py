"""Corrections: a verdict on one flagged decision (typed by a human, or AI-drafted and marked so), each a regression case.

A record keeps a snapshot of the moment (observation, history, menu), so a regression case can be asked of any
policy later without the game and without the original trace (runs/ is not committed).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doomlab.agents.base import StepRecord
from doomlab.config import REPO_ROOT
from doomlab.env.perception import Fact, Observation
from doomlab.review.flags import Flag, Step
from doomlab.tools.registry import TOOLS, ToolCall, ToolSpec, validate_args

CORRECTIONS = REPO_ROOT / "corrections" / "corrections.jsonl"
PINNED_ARGS = ("target_id", "burst")  # arguments a correction holds the agent to; `degrees` is left free
LABELS = ("wrong_tool", "wrong_target", "premature_attack", "missed_pickup", "stuck_loop", "other")
_CALL = re.compile(r"^\s*(\w+)\s*\((.*)\)\s*$")


def parse_call(text: str) -> ToolCall:
    """'go_to(target_id=12)' -> ToolCall. Only integer arguments exist in this tool set."""
    match = _CALL.match(text)
    if not match:
        raise ValueError("write it like go_to(target_id=12) or observe()")
    name, inner = match.groups()
    args: dict[str, Any] = {}
    for part in filter(None, (p.strip() for p in inner.split(","))):
        key, sep, value = part.partition("=")
        if not sep or not value.strip().lstrip("-").isdigit():
            raise ValueError(f"argument {part!r} must look like name=number")
        args[key.strip()] = int(value)
    return ToolCall(name, args)


def check_call(call: ToolCall, step: Step) -> str | None:
    """Why a corrected call could not have been made at that moment, or None if it could."""
    spec = TOOLS.get(call.name)
    if spec is None or call.name not in step.tools:
        return f"{call.name} is not on this agent's menu here; it had {list(step.tools)}"
    problem = validate_args(spec, call.arguments)
    if problem:
        return problem
    if "target_id" in call.arguments:
        target = next((f for f in step.observation.facts if f.id == call.arguments["target_id"]), None)
        if target is None:
            return f"id {call.arguments['target_id']} was not visible; visible ids: {[f.id for f in step.observation.facts]}"
        if call.name == "go_to" and target.kind != "item":
            return f"go_to needs an item; id {target.id} is a {target.kind}"
    return None


def expectation(original_tool: str, corrected: ToolCall | None) -> dict[str, Any]:
    """With a corrected call: make that call with the same target and burst (turn angles may differ).
    Without one: do not repeat the tool."""
    if corrected is None:
        return {"kind": "not_tool", "tool": original_tool}
    pinned = {k: v for k, v in corrected.arguments.items() if k in PINNED_ARGS}
    return {"kind": "call", "tool": corrected.name, "args": pinned}


def meets(expect: dict[str, Any], call: ToolCall) -> bool:
    if expect["kind"] == "not_tool":
        return call.name != expect["tool"]
    return call.name == expect["tool"] and all(call.arguments.get(k) == v for k, v in expect["args"].items())


def describe_expectation(expect: dict[str, Any]) -> str:
    if expect["kind"] == "not_tool":
        return f"must not call {expect['tool']}"
    args = ", ".join(f"{k}={v}" for k, v in expect["args"].items())
    return f"must call {expect['tool']}({args})"


def record(flag: Flag, case_id: str, label: str, fix: str, corrected: ToolCall | None, *,
           author: str = "human", source: str | None = None) -> dict[str, Any]:
    """`author` is "human" for corrections typed in `doomlab review`; "assistant" for AI-drafted ones, which must
    never be reported as human corrections unless a human approves them."""
    s = flag.step
    return {
        "action": "corrected", "id": case_id, "key": _key(flag), "trace": s.trace, "step": s.step,
        "author": author, "approved_by_human": author == "human", "source": source,
        "reason": flag.reason, "label": label, "fix": fix,
        "original": {"tool": s.call.name, "args": s.call.arguments, "ok": s.ok, "code": s.code},
        "corrected": None if corrected is None else {"tool": corrected.name, "args": corrected.arguments},
        "expect": expectation(s.call.name, corrected),
        "snapshot": snapshot(s),
        "created": datetime.now(timezone.utc).isoformat(),
    }


def skipped(flag: Flag) -> dict[str, Any]:
    return {"action": "skipped", "key": _key(flag), "trace": flag.step.trace, "step": flag.step.step}


def snapshot(s: Step) -> dict[str, Any]:
    obs = s.observation
    return {
        "scenario": s.scenario, "seed": s.seed, "variant": s.variant, "mode": s.mode, "tools": list(s.tools),
        "observation": {"tic": obs.tic, "health": obs.health, "ammo": obs.ammo, "kills": obs.kills,
                        "facts": [asdict(f) for f in obs.facts]},
        "history": [asdict(h) for h in s.history],
    }


def context_from(snap: dict[str, Any]) -> tuple[Observation, tuple[StepRecord, ...], tuple[ToolSpec, ...]]:
    o = snap["observation"]
    observation = Observation(tic=o["tic"], facts=tuple(Fact(**f) for f in o["facts"]), health=o["health"],
                              ammo=o["ammo"], kills=o["kills"])
    history = tuple(StepRecord(**h) for h in snap["history"])
    return observation, history, tuple(TOOLS[name] for name in snap["tools"])


def load_records(path: Path = CORRECTIONS) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_record(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def cases(path: Path = CORRECTIONS) -> list[dict[str, Any]]:
    return [r for r in load_records(path) if r["action"] == "corrected"]


def next_case_id(path: Path) -> str:
    return f"rc-{len(cases(path)) + 1:03d}"


def _key(flag: Flag) -> str:
    return f"{flag.step.trace}#{flag.step.step}"

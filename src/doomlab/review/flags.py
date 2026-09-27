"""Rebuild every decision in a trace, then shortlist the ones worth a human look.

A reviewer cannot read ~2,500 dev steps, so deterministic rules pick candidates: at most one per reason per
episode, and never the same step twice. Test-split episodes are refused: corrections must never come from them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doomlab.agents.base import StepRecord
from doomlab.agents.modes import ROLE_TOOL_NAMES
from doomlab.env.perception import Fact, Observation
from doomlab.tools.registry import ToolCall

TEST_SEEDS = range(1000, 1010)  # eval.harness.SPLITS["test"]; kept here to avoid importing the harness
LOW_HEALTH = 50.0
BEFORE_DEATH_STEPS = 3
MAX_FLAGS = 40
PLAY_OUT = "wait_until_end"  # the runner standing still after the agent stopped: not a decision
TURN_TOLERANCE_DEG = 5.0  # a turn must bring the enemy at least this much closer to centre to count as toward it

# (reason, priority): lower number = shown first
REASONS = {
    "medikit_ignored": 1,
    "before_death": 2,
    "premature_attack": 3,
    "turned_from_enemy": 4,
    "wasteful_burst": 5,
    "rejected": 6,
}


@dataclass(frozen=True)
class Step:
    """One decision as the agent faced it: what it saw, its history and menu, what it did and what happened."""

    trace: str
    scenario: str
    seed: int
    variant: str
    mode: str | None
    step: int
    observation: Observation
    history: tuple[StepRecord, ...]
    tools: tuple[str, ...]
    call: ToolCall
    ok: bool
    code: str | None
    message: str


@dataclass(frozen=True)
class Flag:
    step: Step
    reason: str
    detail: str


def episode_steps(path: Path) -> tuple[list[Step], dict[str, Any]]:
    events = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    start = next(e for e in events if e["event"] == "episode_start")
    end = next((e for e in events if e["event"] == "episode_end"), {})
    observed = {e["step"]: e for e in events if e["event"] == "observe"}
    steps: list[Step] = []
    history: list[StepRecord] = []
    decisions = (e for e in events if e["event"] == "tool_exec" and e["step"] in observed and e["tool"] != PLAY_OUT)
    for e in decisions:
        mode = e.get("mode")
        tools = tuple(t for t in start["tools"] if mode is None or t in ROLE_TOOL_NAMES[mode])
        steps.append(Step(
            trace=Path(path).name, scenario=start["scenario"], seed=start["seed"], variant=start["agent"], mode=mode,
            step=e["step"], observation=_observation(observed[e["step"]]), history=tuple(history), tools=tools,
            call=ToolCall(e["tool"], e["args"]), ok=e["ok"], code=e["code"], message=e["message"],
        ))
        history.append(StepRecord(step=e["step"], tool=e["tool"], args=e["args"], ok=e["ok"], code=e["code"],
                                  message=e["message"], tics_used=e["tics"]))
    return steps, end


def shortlist(paths: list[Path], limit: int = MAX_FLAGS) -> list[Flag]:
    flags: list[Flag] = []
    for path in paths:
        steps, end = episode_steps(path)
        if (steps and steps[0].seed in TEST_SEEDS) or _seed_in_name(path) in TEST_SEEDS:
            raise ValueError(f"{Path(path).name} is a test-split episode; corrections must come from dev episodes only")
        flags += _flag_episode(steps, end)
    flags.sort(key=lambda f: (REASONS[f.reason], f.step.scenario, f.step.seed, f.step.variant, f.step.step))
    return flags[:limit]


def _flag_episode(steps: list[Step], end: dict[str, Any]) -> list[Flag]:
    last = {s.step for s in steps[-BEFORE_DEATH_STEPS:]} if end.get("dead") else set()
    used: set[str] = set()
    flags = []
    for s in steps:
        for reason, detail in sorted(_reasons(s, s.step in last), key=lambda r: REASONS[r[0]]):
            if reason not in used:
                used.add(reason)
                flags.append(Flag(s, reason, detail))
                break
    return flags


def _reasons(s: Step, near_death: bool) -> list[tuple[str, str]]:
    obs, found = s.observation, []
    items = [f for f in obs.facts if f.kind == "item"]
    enemies = [f for f in obs.facts if f.kind == "enemy"]
    if items and obs.health is not None and obs.health < LOW_HEALTH and s.call.name != "go_to":
        found.append(("medikit_ignored", f"{items[0].name} visible at health {obs.health:g}, not taken"))
    if near_death:
        found.append(("before_death", f"one of the last {BEFORE_DEATH_STEPS} decisions before dying"))
    if s.code == "NO_ENEMY_IN_CONE":
        found.append(("premature_attack", "attacked with no enemy in the aim cone"))
    if turned_away(s):
        found.append(("turned_from_enemy", f"turned away with {enemies[0].name} in view"))
    if s.call.name == "attack" and s.ok and s.call.arguments.get("burst", 1) > 1:
        found.append(("wasteful_burst", f"fired a burst of {s.call.arguments['burst']}; one hit usually kills"))
    if not s.ok and s.code != "NO_ENEMY_IN_CONE":
        found.append(("rejected", f"rejected: {s.code}"))
    return found


def turned_away(s: Step) -> bool:
    """A turn while an enemy is in view and could be fought, that does not bring the nearest enemy closer to
    the centre: wrong direction, or so far past it that it ends up further off than before."""
    enemies = [f for f in s.observation.facts if f.kind == "enemy"]
    if s.call.name != "turn" or not enemies or not s.observation.ammo or "attack" not in s.tools:
        return False
    bearing = enemies[0].bearing_deg  # facts arrive nearest first
    degrees = s.call.arguments.get("degrees", 0)
    return abs(bearing - degrees) >= abs(bearing) - TURN_TOLERANCE_DEG


def _observation(e: dict[str, Any]) -> Observation:
    facts = tuple(Fact(**{k: f[k] for k in ("id", "name", "kind", "bearing_deg", "ahead", "offset", "distance")})
                  for f in e["facts"])
    return Observation(tic=e["tic"], facts=facts, health=e["health"], ammo=e["ammo"], kills=e["kills"])


def _seed_in_name(path: Path) -> int | None:
    part = Path(path).stem.rsplit("-", 2)[-2] if Path(path).stem.count("-") >= 2 else ""
    return int(part[1:]) if part.startswith("s") and part[1:].isdigit() else None

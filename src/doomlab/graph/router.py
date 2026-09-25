"""Fixed-priority router: the first rule that matches decides where the episode goes next.

1. STOP      the game ended, the agent stopped, recovery is exhausted, or the step cap is reached
2. RECOVER   the last call was rejected: ask the same agent again with the rejection up front
3. CONTINUE  (commander topology) nothing relevant changed: the current specialist keeps going
4. PLAN      otherwise: ask the agent, or for a team, ask the commander to choose a mode first
A fixed order means the same situation always takes the same road, which keeps runs replayable.
"""

from __future__ import annotations

from dataclasses import dataclass

from doomlab.agents.base import StepRecord
from doomlab.agents.modes import FIGHT, HANDOFF_TOOL, NAVIGATE
from doomlab.env.perception import Observation

# Rejected calls use no game time, so a streak of rejections is by definition a streak without progress.
MAX_CONSECUTIVE_REJECTIONS = 3


@dataclass(frozen=True)
class Route:
    next: str  # "stop" | "recover" | "continue" | "plan"
    why: str
    stop_reason: str | None = None  # set when an agent stopped early; None when the game ended on its own


def trailing_rejections(history: tuple[StepRecord, ...]) -> int:
    count = 0
    for step in reversed(history):
        if step.ok:
            break
        count += 1
    return count


def route(
    history: tuple[StepRecord, ...],
    *,
    finished: bool,
    max_steps: int,
    stopped: str | None,
    team: bool = False,
    trigger: str | None = None,
    mode: str | None = None,
) -> Route:
    if stopped:
        return Route("stop", f"agent stopped: {stopped}", stopped)
    if finished:
        return Route("stop", "episode finished")
    rejections = trailing_rejections(history)
    if rejections >= MAX_CONSECUTIVE_REJECTIONS:
        return Route("stop", f"{rejections} rejections in a row", "recovery_exhausted")
    if len(history) >= max_steps:
        return Route("stop", f"step cap {max_steps} reached", "step_limit")
    if rejections:
        last = history[-1]
        return Route("recover", f"{last.tool} rejected {last.code} ({rejections}/{MAX_CONSECUTIVE_REJECTIONS})")
    if team and not trigger:
        return Route("continue", f"stay in {mode} mode")
    return Route("plan", trigger or "ask the agent")


def commander_trigger(
    mode: str | None,
    modes: tuple[str, ...],
    history: tuple[StepRecord, ...],
    observation: Observation,
    *,
    enemy_at_choice: bool,
) -> str | None:
    """Why the commander must choose again, or None to let the current specialist continue.

    `enemy_at_choice` is whether an enemy was visible when the commander last chose. "Enemy appeared" fires on
    that change only: if the commander chose navigate while looking at an enemy, it meant it, and re-asking it
    every step the enemy stays in view would cost a call per step for the same answer.
    """
    if mode is None:
        return "no mode yet"
    if len(modes) < 2:
        return None  # nothing to switch to
    last = history[-1] if history else None
    if last is not None and last.ok and last.tool == HANDOFF_TOOL:
        return f"{mode} specialist reported back: {last.args.get('reason', '')}"
    enemy = any(f.kind == "enemy" for f in observation.facts)
    if mode == FIGHT and not enemy:
        return "fight mode but no enemy visible"
    if mode == FIGHT and not observation.ammo:
        return "fight mode but out of ammo"
    if mode == NAVIGATE and enemy and not enemy_at_choice and observation.ammo:
        return "enemy appeared while navigating"
    return None

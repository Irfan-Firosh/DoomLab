"""What the LLM reads. Built fresh every turn from visible facts and recent results (no growing chat log)."""

from __future__ import annotations

from doomlab.agents.base import StepRecord
from doomlab.env.perception import Observation, describe
from doomlab.tools.executor import IN_CONE_OFFSET, in_cone

HISTORY_TURNS = 5

GOALS = {
    "basic": "Kill the single monster as fast as possible. The episode has a short time limit.",
    "defend_the_center": "You stand still in the centre. Kill as many approaching enemies as you can and survive.",
    "health_gathering": "The floor hurts you. Collect medikits to stay alive as long as possible.",
}

SYSTEM_TEMPLATE = """You control a player in the game Doom by calling tools.
Every turn you receive what is visible right now and the results of your recent actions.
Call exactly one tool per turn.

Rules:
- Use only target ids from the Visible list.
- attack only works when an enemy is IN AIM CONE (within {cone:g} units of your crosshair). Otherwise call aim_at on it first.
- If a call was REJECTED, read the reason and choose differently.

Goal: {goal}"""


def system_prompt(scenario: str) -> str:
    return SYSTEM_TEMPLATE.format(cone=IN_CONE_OFFSET, goal=GOALS.get(scenario, "Play well."))


def turn_prompt(observation: Observation, history: tuple[StepRecord, ...]) -> str:
    lines = describe(observation).splitlines()
    status, facts = lines[0], lines[1:]
    cone_by_id = {f.id: in_cone(f) for f in observation.facts}
    visible = []
    for fact, line in zip(observation.facts, facts):
        suffix = f"  IN AIM CONE: {'yes' if cone_by_id[fact.id] else 'no'}" if fact.kind == "enemy" else ""
        visible.append(line + suffix)
    parts = [f"Status: {status}", "Visible:", *(visible or facts)]
    recent = history[-HISTORY_TURNS:]
    if recent:
        parts.append("Your recent actions:")
        for step in recent:
            call = f"{step.tool}({', '.join(f'{k}={v}' for k, v in step.args.items())})"
            result = f"ok: {step.message} ({step.tics_used} tics)" if step.ok else f"REJECTED {step.code}: {step.message}"
            parts.append(f"- step {step.step}: {call} -> {result}")
    parts.append("Choose your next tool call.")
    return "\n".join(parts)

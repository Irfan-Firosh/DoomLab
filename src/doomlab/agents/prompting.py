"""What the LLM reads. Built fresh every turn from visible facts and recent results (no growing chat log)."""

from __future__ import annotations

from doomlab.agents.base import StepRecord
from doomlab.env.perception import Observation, describe
from doomlab.agents.modes import FIGHT, NAVIGATE
from doomlab.graph.router import MAX_CONSECUTIVE_REJECTIONS, trailing_rejections
from doomlab.tools.executor import in_cone

HISTORY_TURNS = 5

# Each goal states how the episode is scored (runner.SCORES), so the model optimises what we measure.
# 35 tics = 1 second of game time.
GOALS = {
    "basic": (
        "Kill the single monster. Score: tics until the kill, fewer is better. "
        "The episode ends at 300 tics without a kill."
    ),
    "defend_the_center": (
        "You stand in the centre and cannot move; enemies approach from all sides. "
        "Score: tics survived, more is better, up to the time limit of 2100 tics (surviving to it is success). "
        "You start with 26 bullets; kills are reported but only survival is scored."
    ),
    "health_gathering": (
        "The floor hurts you. Collect medikits to stay alive. "
        "Score: tics survived, more is better, up to the time limit of 2100 tics (surviving to it is success)."
    ),
    "health_gathering_supreme": (
        "The floor hurts you and medikits are scarce in a larger area; Poison (hazard) hurts you too. "
        "Collect medikits to stay alive. "
        "Score: tics survived, more is better, up to the time limit of 2100 tics (surviving to it is success)."
    ),
}

SYSTEM_TEMPLATE = """You control a player in the game Doom by calling tools.{role}
Every turn you receive what is visible right now and the results of your recent actions.
Call exactly one tool per turn.

Rules:
- Use only target ids from the Visible list.
- attack only works when an enemy is marked IN AIM CONE: yes. Otherwise call aim_at on it first.
- If a call was REJECTED, read the reason and choose differently.

Goal: {goal}"""


ROLES = {
    FIGHT: "You are the Combat specialist: aim at and shoot enemies. "
    "When no enemy is left to fight, or you cannot fight, call report_back.",
    NAVIGATE: "You are the Navigator: turn to look around and walk to items. "
    "When an enemy needs fighting or you are stuck, call report_back.",
}

COMMANDER_SYSTEM = """You command a two-specialist team playing the game Doom. You never act in the game yourself.
Choose which specialist acts next by calling choose_mode:
- fight: the Combat specialist aims at and shoots visible enemies.
- navigate: the Navigator turns to look around and walks to items.
You are asked again when the situation changes or a specialist reports back.

Goal: {goal}"""


def system_prompt(scenario: str, role: str | None = None) -> str:
    role_line = f"\n{ROLES[role]}" if role else ""
    return SYSTEM_TEMPLATE.format(goal=GOALS.get(scenario, "Play well."), role=role_line)


def commander_system_prompt(scenario: str) -> str:
    return COMMANDER_SYSTEM.format(goal=GOALS.get(scenario, "Play well."))


def commander_prompt(observation: Observation, history: tuple[StepRecord, ...], *, trigger: str, current: str | None) -> str:
    lines = [f"You are asked because: {trigger}.", f"Current mode: {current or 'none'}."]
    return "\n".join([*lines, turn_prompt(observation, history, closing="Choose the next mode with choose_mode.")])


def turn_prompt(
    observation: Observation, history: tuple[StepRecord, ...], *, closing: str = "Choose your next tool call."
) -> str:
    lines = describe(observation).splitlines()
    status, facts = lines[0], lines[1:]
    cone_by_id = {f.id: in_cone(f) for f in observation.facts}
    visible = []
    for fact, line in zip(observation.facts, facts):
        suffix = f"  IN AIM CONE: {'yes' if cone_by_id[fact.id] else 'no'}" if fact.kind == "enemy" else ""
        visible.append(line + suffix)
    parts = [*_recovery_note(history), f"Status: {status}", "Visible:", *(visible or facts)]
    recent = history[-HISTORY_TURNS:]
    if recent:
        parts.append("Your recent actions:")
        for step in recent:
            call = _call_text(step)
            result = f"ok: {step.message} ({step.tics_used} tics)" if step.ok else f"REJECTED {step.code}: {step.message}"
            parts.append(f"- step {step.step}: {call} -> {result}")
    parts.append(closing)
    return "\n".join(parts)


def _call_text(step: StepRecord) -> str:
    return f"{step.tool}({', '.join(f'{k}={v}' for k, v in step.args.items())})"


def _recovery_note(history: tuple[StepRecord, ...]) -> list[str]:
    """Put a rejection first, where the model cannot miss it, with how many more it may afford."""
    streak = trailing_rejections(history)
    if not streak:
        return []
    last = history[-1]
    return [
        f"YOUR LAST CALL WAS REJECTED: {_call_text(last)} -> {last.code}: {last.message}",
        f"Do not repeat it; choose a different call. Rejections in a row: {streak} of {MAX_CONSECUTIVE_REJECTIONS}"
        f" (at {MAX_CONSECUTIVE_REJECTIONS} you lose control for the rest of the episode).",
    ]

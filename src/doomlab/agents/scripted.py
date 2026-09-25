"""Rule-based baseline: aim at the nearest enemy, shoot once it is in the cone. No LLM.

It reads only the facts the LLM will see, so the comparison is fair.
"""

from __future__ import annotations

from doomlab.agents.base import StepRecord
from doomlab.env.perception import Observation
from doomlab.tools.executor import in_cone
from doomlab.tools.registry import ToolCall, ToolSpec


class ScriptedAgent:
    name = "scripted"

    def decide(
        self, observation: Observation, tools: tuple[ToolSpec, ...], history: tuple[StepRecord, ...]
    ) -> ToolCall | None:
        available = {t.name for t in tools}
        enemies = [f for f in observation.facts if f.kind == "enemy"]  # facts arrive sorted nearest-first
        if not enemies:
            return None
        if "attack" in available and observation.ammo and any(in_cone(f) for f in enemies):
            return ToolCall("attack", {"burst": 1})
        if "aim_at" in available and not any(in_cone(f) for f in enemies):
            return ToolCall("aim_at", {"target_id": enemies[0].id})
        return None

"""Rule-based baseline. No LLM; it reads only the facts the LLM will see, so the comparison is fair.

1. enemy in its aim cone and ammo left -> attack
2. enemy visible                       -> aim_at the nearest enemy
3. item visible                        -> go_to the nearest item
4. nothing useful visible              -> turn 90 degrees and look again
"""

from __future__ import annotations

from doomlab.agents.base import StepRecord
from doomlab.env.perception import Observation
from doomlab.tools.executor import in_cone
from doomlab.tools.registry import ToolCall, ToolSpec


SCAN_DEGREES = 90


class ScriptedAgent:
    name = "scripted"

    def decide(
        self, observation: Observation, tools: tuple[ToolSpec, ...], history: tuple[StepRecord, ...]
    ) -> ToolCall | None:
        available = {t.name for t in tools}
        enemies = [f for f in observation.facts if f.kind == "enemy"]  # facts arrive sorted nearest-first
        items = [f for f in observation.facts if f.kind == "item"]
        if enemies and "attack" in available:
            if not observation.ammo:
                return None  # nothing useful left to do
            if any(in_cone(f) for f in enemies):
                return ToolCall("attack", {"burst": 1})
            return ToolCall("aim_at", {"target_id": enemies[0].id})
        if items and "go_to" in available:
            return ToolCall("go_to", {"target_id": items[0].id})
        if "turn" in available:
            return ToolCall("turn", {"degrees": SCAN_DEGREES})
        return None

"""`random` baseline: a uniformly random callable tool with random schema-valid arguments. No LLM.

It shows what the harness achieves on its own: `aim_at` steers precisely and the executor refuses bad shots,
so whatever `random` scores is skill built into the tools, and an LLM's value is how far it gets above that.

"Callable" means the arguments can be filled validly: a tool that needs a target is skipped when nothing
suitable is visible (go_to only targets items). Game preconditions (aim cone, ammo) are left to the
executor, exactly as for every other agent. Seeded per episode, so a run repeats exactly.
"""

from __future__ import annotations

import random
from typing import Any

from doomlab.agents.base import StepRecord
from doomlab.env.perception import Fact, Observation
from doomlab.tools.registry import ToolCall, ToolSpec


class RandomAgent:
    name = "random"

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)
        self.config = {"seed": seed}

    def decide(
        self, observation: Observation, tools: tuple[ToolSpec, ...], history: tuple[StepRecord, ...]
    ) -> ToolCall | None:
        callable_tools = [t for t in tools if _targets(t, observation) != []]
        if not callable_tools:
            return None
        spec = self._rng.choice(callable_tools)
        return ToolCall(spec.name, self._arguments(spec, observation))

    def _arguments(self, spec: ToolSpec, observation: Observation) -> dict[str, Any]:
        args: dict[str, Any] = {}
        for name, rule in spec.parameters["properties"].items():
            if name == "target_id":
                args[name] = self._rng.choice(_targets(spec, observation)).id
            elif rule.get("type") == "integer":
                args[name] = self._integer(rule)
            else:
                raise ValueError(f"random agent cannot fill argument {name!r} of {spec.name}")
        return args

    def _integer(self, rule: dict[str, Any]) -> int:
        excluded = rule.get("not", {}).get("const")
        while True:
            value = self._rng.randint(rule["minimum"], rule["maximum"])
            if value != excluded:
                return value


def _targets(spec: ToolSpec, observation: Observation) -> list[Fact] | None:
    """Facts this tool may target, or None when it takes no target."""
    if "target_id" not in spec.parameters["properties"]:
        return None
    return [f for f in observation.facts if spec.name != "go_to" or f.kind == "item"]

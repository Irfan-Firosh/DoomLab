"""`commander`: a Commander picks the job (fight or navigate); a specialist with only that job's tools acts.

All three are the same model behind ReactAgent, sharing one budget, so the comparison with `react_single`
measures the topology, not extra spending. The runner's graph decides *when* the commander is asked
(see graph/router.py `commander_trigger`); this class only answers when asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from doomlab.agents.base import AgentStop, StepRecord
from doomlab.agents.modes import FIGHT, NAVIGATE
from doomlab.agents.prompting import commander_prompt, commander_system_prompt, system_prompt
from doomlab.agents.react import ChatClient, ReactAgent
from doomlab.env.perception import Observation
from doomlab.llm.budget import Budget
from doomlab.llm.preflight import Decoding
from doomlab.tools.registry import ToolSpec, validate_args

MAX_MODE_ATTEMPTS = 2


@dataclass(frozen=True)
class ModeChoice:
    mode: str
    reason: str
    auto: bool  # True when only one mode was possible, so no model was asked


def choose_mode_spec(modes: tuple[str, ...]) -> ToolSpec:
    return ToolSpec(
        name="choose_mode",
        description="Choose which specialist acts next.",
        parameters={
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": list(modes)},
                "reason": {"type": "string", "description": "one short sentence"},
            },
            "required": ["mode"],
            "additionalProperties": False,
        },
    )


class CommanderTeam:
    name = "commander"

    def __init__(
        self, client: ChatClient, *, scenario: str, decoding: Decoding, budget: Budget, lessons: tuple[str, ...] = ()
    ) -> None:
        def member(role: str, system: str) -> ReactAgent:
            return ReactAgent(client, scenario=scenario, decoding=decoding, budget=budget, system=system, role=role)

        self._boss = member("commander", commander_system_prompt(scenario, lessons))
        self._specialists = {mode: member(mode, system_prompt(scenario, mode, lessons)) for mode in (FIGHT, NAVIGATE)}
        self.config = {**self._boss.config, "topology": "commander"}

    def specialist(self, mode: str) -> ReactAgent:
        return self._specialists[mode]

    def drain_events(self) -> list[dict[str, Any]]:
        return [e for agent in (self._boss, *self._specialists.values()) for e in agent.drain_events()]

    async def choose_mode(
        self, observation: Observation, modes: tuple[str, ...], history: tuple[StepRecord, ...],
        *, trigger: str, current: str | None,
    ) -> ModeChoice:
        if len(modes) == 1:
            return ModeChoice(modes[0], "the only possible mode in this scenario", auto=True)
        spec = choose_mode_spec(modes)
        prompt = commander_prompt(observation, history, trigger=trigger, current=current)
        problem = ""
        for _ in range(MAX_MODE_ATTEMPTS):
            call = await self._boss.ask(prompt, (spec,))
            problem = f"called {call.name}" if call.name != spec.name else validate_args(spec, call.arguments)
            if problem is None:
                return ModeChoice(call.arguments["mode"], call.arguments.get("reason", ""), auto=False)
            prompt = f"{prompt}\nYour last answer was invalid ({problem}). Call choose_mode with mode in {list(modes)}."
        raise AgentStop("no_valid_mode", problem)

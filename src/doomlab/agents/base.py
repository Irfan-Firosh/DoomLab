"""The contract every agent satisfies: scripted rules, random, and LLM agents alike."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Awaitable
from typing import Any, Protocol

from doomlab.env.perception import Observation
from doomlab.tools.registry import ToolCall, ToolSpec


class AgentStop(Exception):
    """An agent ending the episode cleanly for a known reason (e.g. budget, llm_error, no_tool_call)."""

    def __init__(self, outcome: str, message: str = "") -> None:
        super().__init__(f"{outcome}: {message}" if message else outcome)
        self.outcome = outcome
        self.message = message


@dataclass(frozen=True)
class StepRecord:
    """What happened on one decision: the call, whether it ran, and its verified effect."""

    step: int
    tool: str
    args: dict[str, Any]
    ok: bool
    code: str | None
    message: str
    tics_used: int
    llm_calls: int = 0
    llm_seconds: float = 0.0
    llm_tokens: int | None = 0


class Agent(Protocol):
    name: str

    def decide(
        self, observation: Observation, tools: tuple[ToolSpec, ...], history: tuple[StepRecord, ...]
    ) -> ToolCall | None | Awaitable[ToolCall | None]:
        """Pick the next tool call, or None to give up. LLM agents may be async; raise AgentStop to end cleanly."""
        ...

"""`react_single`: one LLM picks one tool per turn (Reason + Act), through the same harness as every agent."""

from __future__ import annotations

from typing import Any, Protocol

from doomlab.agents.base import AgentStop, StepRecord
from doomlab.agents.prompting import system_prompt, turn_prompt
from doomlab.env.perception import Observation
from doomlab.llm.budget import Budget, BudgetExhausted
from doomlab.llm.client import ChatResult, LLMError
from doomlab.llm.preflight import Decoding
from doomlab.tools.registry import ToolCall, ToolSpec, to_openai

REMINDER = "You must respond with exactly one tool call, not text."
MAX_ATTEMPTS = 2
CONTENT_LOG_CHARS = 500


class ChatClient(Protocol):
    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ChatResult: ...


class ReactAgent:
    name = "react_single"

    def __init__(
        self,
        client: ChatClient,
        *,
        scenario: str,
        decoding: Decoding,
        budget: Budget,
        system: str | None = None,
        role: str | None = None,
        lessons: tuple[str, ...] = (),
    ) -> None:
        self._client = client
        self._decoding = decoding
        self._budget = budget
        self._system = system or system_prompt(scenario, lessons=lessons)
        self._role = role  # tags trace events when this agent is one member of a team
        self._events: list[dict[str, Any]] = []
        self.config = {
            "model": decoding.model_id,
            "temperature": decoding.temperature,
            "max_tokens": decoding.max_tokens,
            "thinking": "off" if decoding.disable_thinking else "on",
            "budget": {"calls": budget.max_calls, "tokens": budget.max_tokens, "seconds": budget.max_seconds},
        }

    def drain_events(self) -> list[dict[str, Any]]:
        """LLM-call events since the last drain, for the runner to write into the trace."""
        events, self._events = self._events, []
        return events

    async def decide(
        self, observation: Observation, tools: tuple[ToolSpec, ...], history: tuple[StepRecord, ...]
    ) -> ToolCall:
        return await self.ask(turn_prompt(observation, history), tools)

    async def ask(self, prompt: str, tools: tuple[ToolSpec, ...]) -> ToolCall:
        """One decision from a prepared prompt: retries once on a text reply or a transient error."""
        messages = [
            {"role": "system", "content": self._system},
            {"role": "user", "content": prompt},
        ]
        payload = to_openai(tools)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            result = await self._call(messages, payload, attempt)
            if result is None:
                continue  # transient error, retry
            if result.tool_calls:
                return result.tool_calls[0]
            messages = [*messages, {"role": "assistant", "content": result.content}, {"role": "user", "content": REMINDER}]
        raise AgentStop("no_tool_call", f"no tool call after {MAX_ATTEMPTS} attempts")

    async def _call(self, messages: list[dict[str, Any]], payload: list[dict[str, Any]], attempt: int) -> ChatResult | None:
        try:
            self._budget.check()
        except BudgetExhausted as exc:
            raise AgentStop("budget", str(exc)) from exc
        try:
            result = await self._client.chat(
                messages,
                tools=payload,
                temperature=self._decoding.temperature,
                max_tokens=self._decoding.max_tokens,
                disable_thinking=self._decoding.disable_thinking,
            )
        except LLMError as exc:
            self._events.append({"event": "llm_error", **self._tag(), "attempt": attempt, "kind": exc.kind, "message": str(exc)})
            if exc.kind == "auth":
                raise
            if attempt == MAX_ATTEMPTS:
                raise AgentStop("llm_error", str(exc)) from exc
            return None
        tokens = (result.usage or {}).get("total_tokens")
        self._budget.record(tokens=tokens)
        self._events.append(
            {
                "event": "llm_call",
                **self._tag(),
                "attempt": attempt,
                "latency_s": round(result.latency_s, 3),
                "usage": result.usage,
                "tool_calls": [{"name": c.name, "arguments": c.arguments} for c in result.tool_calls],
                "content": result.content[:CONTENT_LOG_CHARS],
                "prompt": messages[-1]["content"] if attempt == 1 else None,
            }
        )
        return result

    def _tag(self) -> dict[str, str]:
        return {"role": self._role} if self._role else {}

"""Play one episode: observe -> agent decides -> executor acts -> record, until the episode ends."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from doomlab.agents.base import Agent, AgentStop, StepRecord
from doomlab.env.perception import Observation
from doomlab.tools.executor import Executor, Session, ToolResult
from doomlab.trace import TraceWriter

MAX_STEPS = 30

# Per-scenario success rules, applied to the final observation. Thursday adds the other scenarios.
SUCCESS_RULES: dict[str, Callable[[Observation], bool]] = {
    "basic": lambda final: (final.kills or 0) >= 1,
}


@dataclass(frozen=True)
class EpisodeResult:
    scenario: str
    seed: int
    agent: str
    outcome: str  # success | timeout | step_limit | gave_up | budget | llm_error | no_tool_call | ended
    steps: tuple[StepRecord, ...]
    tics: int
    kills: int
    rejected: int
    llm_calls: int = 0
    llm_seconds: float = 0.0
    tokens: int | None = 0  # None when the endpoint did not report usage for some call
    trace_path: str | None = None


@dataclass
class _LLMTally:
    calls: int = 0
    seconds: float = 0.0
    tokens: int = 0
    tokens_known: bool = True
    events: list[dict[str, Any]] = field(default_factory=list)

    def absorb(self, events: list[dict[str, Any]]) -> tuple[int, float, int | None]:
        """Add one decision's LLM events; return that decision's (calls, seconds, tokens)."""
        calls, seconds, tokens, known = 0, 0.0, 0, True
        for e in events:
            if e["event"] != "llm_call":
                continue
            calls += 1
            seconds += e["latency_s"]
            total = (e.get("usage") or {}).get("total_tokens")
            if total is None:
                known = False
            else:
                tokens += total
        self.calls += calls
        self.seconds += seconds
        self.tokens += tokens
        self.tokens_known &= known
        return calls, seconds, tokens if known else None


def run_episode(session: Session, agent: Agent, *, scenario: str, seed: int, max_steps: int = MAX_STEPS) -> EpisodeResult:
    """Synchronous wrapper for callers without an event loop (scripted agents, tests)."""
    return asyncio.run(arun_episode(session, agent, scenario=scenario, seed=seed, max_steps=max_steps))


async def arun_episode(
    session: Session,
    agent: Agent,
    *,
    scenario: str,
    seed: int,
    max_steps: int = MAX_STEPS,
    trace: TraceWriter | None = None,
) -> EpisodeResult:
    emit = trace.write if trace else (lambda event, **fields: None)
    executor = Executor(session)
    tally = _LLMTally()
    steps: list[StepRecord] = []
    stopped: str | None = None
    gave_up = False
    emit("episode_start", scenario=scenario, seed=seed, agent=agent.name, buttons=session.info.buttons,
         tools=[t.name for t in executor.tools], config=getattr(agent, "config", {}))

    while len(steps) < max_steps and not session.game.is_episode_finished():
        observation = executor.observe()
        emit("observe", step=len(steps) + 1, tic=observation.tic, ammo=observation.ammo, health=observation.health,
             kills=observation.kills, facts=[asdict(f) for f in observation.facts])
        try:
            decision = agent.decide(observation, executor.tools, tuple(steps))
            call = await decision if inspect.isawaitable(decision) else decision
        except AgentStop as stop:
            stopped = stop.outcome
            _flush_llm_events(agent, tally, emit)
            emit("agent_stop", outcome=stop.outcome, message=stop.message)
            break
        llm = _flush_llm_events(agent, tally, emit)
        if call is None:
            gave_up = True
            break
        result = executor.execute(call.name, call.arguments)
        emit("tool_exec", step=len(steps) + 1, **_tool_fields(result))
        steps.append(
            StepRecord(
                step=len(steps) + 1, tool=call.name, args=dict(call.arguments), ok=result.ok, code=result.code,
                message=result.message, tics_used=result.tics_used,
                llm_calls=llm[0], llm_seconds=round(llm[1], 3), llm_tokens=llm[2],
            )
        )

    final = executor.observe()
    outcome = _outcome(scenario, final, finished=session.game.is_episode_finished(), stopped=stopped, gave_up=gave_up)
    result = EpisodeResult(
        scenario=scenario, seed=seed, agent=agent.name, outcome=outcome, steps=tuple(steps),
        tics=sum(s.tics_used for s in steps), kills=int(final.kills or 0), rejected=sum(not s.ok for s in steps),
        llm_calls=tally.calls, llm_seconds=round(tally.seconds, 3), tokens=tally.tokens if tally.tokens_known else None,
        trace_path=str(trace.path) if trace else None,
    )
    emit("episode_end", outcome=outcome, steps=len(steps), tics=result.tics, kills=result.kills,
         rejected=result.rejected, llm_calls=result.llm_calls, llm_seconds=result.llm_seconds, tokens=result.tokens)
    return result


def _flush_llm_events(agent: Agent, tally: _LLMTally, emit: Callable[..., None]) -> tuple[int, float, int | None]:
    drain = getattr(agent, "drain_events", None)
    events = drain() if drain else []
    for event in events:
        emit(event["event"], **{k: v for k, v in event.items() if k != "event"})
    return tally.absorb(events)


def _tool_fields(result: ToolResult) -> dict[str, Any]:
    return {
        "tool": result.tool, "args": result.args, "ok": result.ok, "code": result.code, "message": result.message,
        "tics": result.tics_used, "buttons": [list(b) for b in result.buttons], "kills_gained": result.kills_gained,
        "episode_finished": result.episode_finished,
    }


def _outcome(scenario: str, final: Observation, *, finished: bool, stopped: str | None, gave_up: bool) -> str:
    rule = SUCCESS_RULES.get(scenario)
    if rule and rule(final):
        return "success"
    if stopped:
        return stopped
    if finished:
        return "timeout" if rule else "ended"
    return "gave_up" if gave_up else "step_limit"

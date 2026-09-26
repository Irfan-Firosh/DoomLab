"""Play one episode as a state graph: route -> plan/recover (agent decides) -> act (executor) -> route ... -> finish."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from doomlab.agents.base import Agent, AgentStop, StepRecord
from doomlab.agents.modes import available_modes, role_tools
from doomlab.env.perception import Observation
from doomlab.graph.engine import END, Graph
from doomlab.graph.router import commander_trigger, route
from doomlab.tools.executor import Executor, Session, ToolResult
from doomlab.tools.registry import ToolCall, ToolSpec
from doomlab.trace import TraceWriter

MAX_STEPS = 200
# When an agent stops acting, time must still pass: the rest of the episode is played out standing still,
# so quitting can never dodge a death. Infrastructure failures (llm_error) are left as they are.
PLAY_OUT_AFTER = frozenset({"gave_up", "step_limit", "budget", "no_tool_call", "no_valid_mode", "recovery_exhausted"})

# Success rules, applied to the final observation and whether the episode ended.
SUCCESS_RULES: dict[str, Callable[[Observation, bool], bool]] = {
    "basic": lambda final, finished: (final.kills or 0) >= 1,
    "defend_the_center": lambda final, finished: finished and not final.dead,  # alive at the time limit
    "health_gathering": lambda final, finished: finished and not final.dead,
    "health_gathering_supreme": lambda final, finished: finished and not final.dead,
}

# Scores say *how well*, even when nobody succeeds. (name, higher_is_better)
SCORES: dict[str, tuple[str, bool]] = {
    "basic": ("tics", False),
    "defend_the_center": ("survived_tics", True),  # kills are capped by 26 ammo; holding out longer is uncapped
    "health_gathering": ("survived_tics", True),
    "health_gathering_supreme": ("survived_tics", True),
}


@dataclass(frozen=True)
class EpisodeResult:
    scenario: str
    seed: int
    agent: str
    outcome: str  # decided by the game: success | died | timeout | ended; or llm_error (infrastructure)
    steps: tuple[StepRecord, ...]
    tics: int
    kills: int
    rejected: int
    llm_calls: int = 0
    llm_seconds: float = 0.0
    tokens: int | None = 0  # None when the endpoint did not report usage for some call
    trace_path: str | None = None
    score: float = 0.0  # see SCORES for its meaning per scenario
    stop_reason: str | None = None  # why the agent stopped early: gave_up | step_limit | budget | no_tool_call | recovery_exhausted | llm_error


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
    config_hash: str | None = None,
) -> EpisodeResult:
    emit = trace.write if trace else (lambda event, **fields: None)
    executor = Executor(session)
    tally = _LLMTally()
    emit("episode_start", scenario=scenario, seed=seed, agent=agent.name, buttons=session.info.buttons,
         tools=[t.name for t in executor.tools], config=getattr(agent, "config", {}),
         **({"config_hash": config_hash} if config_hash else {}))

    graph = _episode_graph(session, agent, executor, tally, emit, max_steps)
    state = await graph.run("route", _EpisodeState(), on_transition=lambda src, dst, s: emit(
        "transition", **{"from": src, "to": dst, "step": len(s.steps)}, **({"why": s.why} if src == "route" else {})))

    final = executor.observe()
    steps, reason = state.steps, state.stop_reason
    outcome = _outcome(scenario, final, finished=session.game.is_episode_finished(), stop_reason=reason)
    tics = sum(s.tics_used for s in steps)
    result = EpisodeResult(
        scenario=scenario, seed=seed, agent=agent.name, outcome=outcome, steps=steps,
        tics=tics, kills=int(final.kills or 0), rejected=sum(not s.ok for s in steps),
        llm_calls=tally.calls, llm_seconds=round(tally.seconds, 3), tokens=tally.tokens if tally.tokens_known else None,
        trace_path=str(trace.path) if trace else None,
        score=_score(scenario, final, tics),
        stop_reason=reason,
    )
    emit("episode_end", outcome=outcome, steps=len(steps), tics=result.tics, kills=result.kills,
         rejected=result.rejected, llm_calls=result.llm_calls, llm_seconds=result.llm_seconds, tokens=result.tokens,
         score=result.score, dead=final.dead, stop_reason=reason)
    return result


@dataclass(frozen=True)
class _EpisodeState:
    steps: tuple[StepRecord, ...] = ()
    call: ToolCall | None = None  # the decision waiting to be acted on
    llm: tuple[int, float, int | None] = (0, 0.0, 0)  # LLM cost of that decision (commander + specialist)
    route: str = "plan"
    why: str = ""
    stop_reason: str | None = None  # set by an agent stopping (AgentStop / None) or by the router
    mode: str | None = None  # commander topology: the current specialist's job
    enemy_at_choice: bool = False  # was an enemy visible when the commander last chose?


def _episode_graph(session: Session, agent: Agent, executor: Executor, tally: _LLMTally,
                   emit: Callable[..., None], max_steps: int) -> Graph[_EpisodeState]:
    """route -> [commander ->] plan | recover -> act -> route ... -> finish. Only `act` touches the game.

    A team (commander topology) adds the `commander` node and the CONTINUE route; a single agent never uses them.
    """
    team = callable(getattr(agent, "choose_mode", None))
    modes = available_modes(executor.tools) if team else ()
    if team and not modes:
        raise ValueError("commander topology: this scenario offers neither fight nor navigate")

    def menu(state: _EpisodeState) -> tuple[ToolSpec, ...]:
        return role_tools(state.mode, executor.tools) if team else executor.tools

    def route_node(state: _EpisodeState) -> _EpisodeState:
        trigger = None
        if team:
            trigger = commander_trigger(state.mode, modes, state.steps, executor.observe(),
                                        enemy_at_choice=state.enemy_at_choice)
        decision = route(state.steps, finished=session.game.is_episode_finished(), max_steps=max_steps,
                         stopped=state.stop_reason, team=team, trigger=trigger, mode=state.mode)
        return replace(state, route=decision.next, why=decision.why, stop_reason=decision.stop_reason)

    async def commander_node(state: _EpisodeState) -> _EpisodeState:
        observation = executor.observe()
        try:
            choice = await agent.choose_mode(observation, modes, state.steps, trigger=state.why, current=state.mode)
        except AgentStop as stop:
            return _stopped(state, stop)
        llm = _flush_llm_events(agent, tally, emit)
        emit("mode", step=len(state.steps) + 1, mode=choice.mode, previous=state.mode, auto=choice.auto,
             trigger=state.why, reason=choice.reason)
        enemy = any(f.kind == "enemy" for f in observation.facts)
        return replace(state, mode=choice.mode, enemy_at_choice=enemy, llm=llm)

    async def decide_node(state: _EpisodeState) -> _EpisodeState:
        observation = executor.observe()
        emit("observe", step=len(state.steps) + 1, tic=observation.tic, ammo=observation.ammo,
             health=observation.health, kills=observation.kills, facts=[asdict(f) for f in observation.facts])
        actor = agent.specialist(state.mode) if team else agent
        try:
            decision = actor.decide(observation, menu(state), state.steps)
            call = await decision if inspect.isawaitable(decision) else decision
        except AgentStop as stop:
            return _stopped(state, stop)
        llm = _flush_llm_events(agent, tally, emit)
        return replace(state, call=call, llm=_add_llm(state.llm, llm), stop_reason=None if call else "gave_up")

    def _stopped(state: _EpisodeState, stop: AgentStop) -> _EpisodeState:
        _flush_llm_events(agent, tally, emit)
        emit("agent_stop", outcome=stop.outcome, message=stop.message)
        return replace(state, call=None, stop_reason=stop.outcome)

    def act_node(state: _EpisodeState) -> _EpisodeState:
        call, (calls, seconds, tokens) = state.call, state.llm
        result = executor.execute(call.name, call.arguments, allowed=menu(state) if team else None)
        emit("tool_exec", step=len(state.steps) + 1, **({"mode": state.mode} if team else {}), **_tool_fields(result))
        record = StepRecord(
            step=len(state.steps) + 1, tool=call.name, args=dict(call.arguments), ok=result.ok, code=result.code,
            message=result.message, tics_used=result.tics_used,
            llm_calls=calls, llm_seconds=round(seconds, 3), llm_tokens=tokens,
        )
        return replace(state, steps=(*state.steps, record), call=None, llm=(0, 0.0, 0))

    def finish_node(state: _EpisodeState) -> _EpisodeState:
        reason = state.stop_reason
        if reason not in PLAY_OUT_AFTER or session.game.is_episode_finished():
            return state
        idle = executor.play_out()
        emit("tool_exec", step=len(state.steps) + 1, reason=reason, **_tool_fields(idle))
        record = StepRecord(step=len(state.steps) + 1, tool=idle.tool, args={}, ok=True, code=None,
                            message=f"{idle.message} (after {reason})", tics_used=idle.tics_used)
        return replace(state, steps=(*state.steps, record))

    # at most 4 hops per step (route, commander, plan, act), plus start and finish
    graph: Graph[_EpisodeState] = Graph(max_transitions=5 * max_steps + 10)
    graph.node("route", route_node)
    graph.node("plan", decide_node)  # the single agent, or the current specialist
    graph.node("recover", decide_node)  # same agent; the prompt now leads with the rejection it must fix
    graph.node("act", act_node)
    graph.node("finish", finish_node)
    next_after_route = {"stop": "finish", "recover": "recover", "continue": "plan", "plan": "plan"}
    if team:
        graph.node("commander", commander_node)
        graph.branch("commander", lambda s: "route" if s.stop_reason else "plan", targets=("plan", "route"))
        next_after_route["plan"] = "commander"
    graph.branch("route", lambda s: next_after_route[s.route], targets=set(next_after_route.values()))
    for decider in ("plan", "recover"):
        graph.branch(decider, lambda s: "act" if s.call else "route", targets=("act", "route"))
    graph.edge("act", "route")
    graph.edge("finish", END)
    return graph


def _add_llm(a: tuple[int, float, int | None], b: tuple[int, float, int | None]) -> tuple[int, float, int | None]:
    tokens = None if a[2] is None or b[2] is None else a[2] + b[2]
    return a[0] + b[0], a[1] + b[1], tokens


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


def _score(scenario: str, final: Observation, tics: int) -> float:
    name = SCORES.get(scenario, ("tics", False))[0]
    return float(final.kills or 0) if name == "kills" else float(tics)


def _outcome(scenario: str, final: Observation, *, finished: bool, stop_reason: str | None) -> str:
    rule = SUCCESS_RULES.get(scenario)
    if rule and rule(final, finished):
        return "success"
    if final.dead:
        return "died"
    if stop_reason == "llm_error":
        return "llm_error"
    return "timeout" if rule else "ended"

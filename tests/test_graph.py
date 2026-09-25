import dataclasses

import pytest

from doomlab.agents.base import StepRecord
from doomlab.graph.engine import END, Graph, GraphError
from doomlab.graph.router import MAX_CONSECUTIVE_REJECTIONS, route, trailing_rejections


@dataclasses.dataclass(frozen=True)
class Counter:
    n: int = 0


def _bump(state):
    return dataclasses.replace(state, n=state.n + 1)


async def _abump(state):
    return dataclasses.replace(state, n=state.n + 1)


# ------------------------------------------------------------------ engine


async def test_graph_follows_edges_and_branches_and_reports_transitions():
    graph = Graph(max_transitions=50)
    graph.node("inc", _bump)
    graph.node("ainc", _abump)  # async nodes work too
    graph.edge("inc", "ainc")
    graph.branch("ainc", lambda s: END if s.n >= 4 else "inc", targets=("inc", END))
    seen = []
    final = await graph.run("inc", Counter(), on_transition=lambda src, dst, s: seen.append((src, dst)))
    assert final.n == 4
    assert seen == [("inc", "ainc"), ("ainc", "inc"), ("inc", "ainc"), ("ainc", END)]


async def test_graph_never_mutates_the_input_state():
    graph = Graph(max_transitions=5)
    graph.node("inc", _bump)
    graph.edge("inc", END)
    start = Counter()
    assert (await graph.run("inc", start)).n == 1 and start.n == 0


async def test_transition_cap_stops_a_graph_that_would_loop_forever():
    graph = Graph(max_transitions=10)
    graph.node("spin", _bump)
    graph.edge("spin", "spin")
    with pytest.raises(GraphError, match="10 transitions"):
        await graph.run("spin", Counter())


def test_edges_to_unknown_nodes_are_rejected_when_wired():
    graph = Graph(max_transitions=5)
    graph.node("a", _bump)
    with pytest.raises(GraphError):
        graph.edge("a", "nowhere")
    with pytest.raises(GraphError):
        graph.branch("a", lambda s: END, targets=("nowhere",))


async def test_branch_choosing_an_undeclared_target_fails_loudly():
    graph = Graph(max_transitions=5)
    graph.node("a", _bump)
    graph.node("b", _bump)
    graph.branch("a", lambda s: "b", targets=(END,))
    with pytest.raises(GraphError, match="undeclared"):
        await graph.run("a", Counter())


def test_a_node_needs_exactly_one_way_out():
    graph = Graph(max_transitions=5)
    graph.node("a", _bump)
    graph.edge("a", END)
    with pytest.raises(GraphError):
        graph.edge("a", END)


async def test_unknown_entry_or_dead_end_node_fails():
    graph = Graph(max_transitions=5)
    graph.node("a", _bump)
    with pytest.raises(GraphError, match="no outgoing"):
        await graph.run("a", Counter())
    with pytest.raises(GraphError, match="unknown"):
        await graph.run("zzz", Counter())


# ------------------------------------------------------------------ router


def _step(n, ok):
    return StepRecord(step=n, tool="attack", args={"burst": 1}, ok=ok, code=None if ok else "NO_ENEMY_IN_CONE",
                      message="", tics_used=14 if ok else 0)


def test_trailing_rejections_counts_only_the_current_streak():
    history = (_step(1, False), _step(2, True), _step(3, False), _step(4, False))
    assert trailing_rejections(history) == 2
    assert trailing_rejections(()) == 0


def test_router_plans_by_default_and_recovers_after_a_rejection():
    assert route((), finished=False, max_steps=10, stopped=None).next == "plan"
    decision = route((_step(1, False),), finished=False, max_steps=10, stopped=None)
    assert decision.next == "recover" and "NO_ENEMY_IN_CONE" in decision.why


def test_router_stop_beats_everything_else():
    rejected = (_step(1, False),)
    assert route(rejected, finished=True, max_steps=10, stopped=None) == route((), finished=True, max_steps=10, stopped=None)
    finished = route(rejected, finished=True, max_steps=10, stopped=None)
    assert finished.next == "stop" and finished.stop_reason is None  # the game ended on its own
    agent = route(rejected, finished=False, max_steps=10, stopped="budget")
    assert (agent.next, agent.stop_reason) == ("stop", "budget")


def test_router_ends_recovery_after_the_limit():
    streak = tuple(_step(i, False) for i in range(1, MAX_CONSECUTIVE_REJECTIONS + 1))
    decision = route(streak, finished=False, max_steps=100, stopped=None)
    assert (decision.next, decision.stop_reason) == ("stop", "recovery_exhausted")
    almost = route(streak[:-1], finished=False, max_steps=100, stopped=None)
    assert almost.next == "recover"


def test_router_step_limit():
    steps = (_step(1, True), _step(2, True))
    assert route(steps, finished=False, max_steps=2, stopped=None).stop_reason == "step_limit"

from fakes import FakeSession

from doomlab.runner import run_episode
from doomlab.agents.scripted import ScriptedAgent
from doomlab.tools.registry import ToolCall


class ScriptAgent:
    """Replays fixed decisions; returns None when out of script."""

    name = "script"

    def __init__(self, calls):
        self._calls = list(calls)

    def decide(self, observation, tools, history):
        return self._calls.pop(0) if self._calls else None


class StubbornAgent:
    name = "stubborn"

    def decide(self, observation, tools, history):
        return ToolCall("attack", {"burst": 1})  # always rejected: target is far off-centre


def test_scripted_agent_succeeds_on_fake_basic():
    result = run_episode(FakeSession(target_y=40.0), ScriptedAgent(), scenario="basic", seed=0)
    assert result.outcome == "success"
    assert [s.tool for s in result.steps] == ["aim_at", "attack"]
    assert result.kills == 1 and result.rejected == 0 and result.tics > 0


def test_step_limit_stops_an_agent_that_never_finishes():
    calls = [ToolCall("aim_at", {"target_id": 0})] * 10  # valid, but never shoots
    result = run_episode(FakeSession(target_y=200.0), ScriptAgent(calls), scenario="basic", seed=0, max_steps=5)
    assert (result.outcome, result.stop_reason) == ("timeout", "step_limit")
    assert [s.tool for s in result.steps] == ["aim_at"] * 5 + ["wait_until_end"]  # rest played out standing still


def test_recovery_is_exhausted_after_three_rejections_in_a_row():
    result = run_episode(FakeSession(target_y=200.0), StubbornAgent(), scenario="basic", seed=0)
    assert (result.outcome, result.stop_reason) == ("timeout", "recovery_exhausted")
    assert result.rejected == 3 and all(s.code == "NO_ENEMY_IN_CONE" for s in result.steps[:3])
    assert result.steps[-1].tool == "wait_until_end"


def test_a_good_call_resets_the_rejection_streak():
    bad, aim = ToolCall("attack", {"burst": 1}), ToolCall("aim_at", {"target_id": 0})
    calls = [bad, bad, ToolCall("observe", {}), bad, bad, aim, ToolCall("attack", {"burst": 1})]  # observe: ok once
    result = run_episode(FakeSession(target_y=40.0), ScriptAgent(calls), scenario="basic", seed=0)
    assert result.outcome == "success" and result.rejected == 4 and result.stop_reason is None


def test_trace_records_graph_transitions_including_a_recovery(tmp_path):
    import json

    from doomlab.runner import arun_episode
    from doomlab.trace import TraceWriter

    calls = [ToolCall("attack", {"burst": 1}), ToolCall("aim_at", {"target_id": 0}), ToolCall("attack", {"burst": 1})]
    path = tmp_path / "ep.jsonl"

    async def go():
        with TraceWriter(path) as trace:
            return await arun_episode(FakeSession(target_y=40.0), ScriptAgent(calls), scenario="basic", seed=0, trace=trace)

    import asyncio

    assert asyncio.run(go()).outcome == "success"
    hops = [(e["from"], e["to"]) for e in map(json.loads, path.read_text().splitlines()) if e["event"] == "transition"]
    assert hops == [
        ("route", "plan"), ("plan", "act"), ("act", "route"),
        ("route", "recover"), ("recover", "act"), ("act", "route"),  # the rejected attack is recovered from
        ("route", "plan"), ("plan", "act"), ("act", "route"),
        ("route", "finish"), ("finish", "__end__"),
    ]


def test_gave_up_is_recorded():
    result = run_episode(FakeSession(), ScriptAgent([]), scenario="basic", seed=0)
    assert (result.outcome, result.stop_reason) == ("timeout", "gave_up")
    assert [s.tool for s in result.steps] == ["wait_until_end"] and result.tics == 300


def test_timeout_when_episode_ends_without_a_kill():
    session = FakeSession(target_y=200.0, timeout=30)
    calls = [ToolCall("aim_at", {"target_id": 0})] * 3
    result = run_episode(session, ScriptAgent(calls), scenario="basic", seed=0)
    assert result.outcome == "timeout" and result.kills == 0


def test_no_decisions_after_the_episode_ends():
    session = FakeSession(target_y=0.0)
    calls = [ToolCall("attack", {"burst": 1}), ToolCall("attack", {"burst": 1})]
    result = run_episode(session, ScriptAgent(calls), scenario="basic", seed=0)
    assert result.outcome == "success" and len(result.steps) == 1


async def test_react_agent_through_runner_writes_a_trace(tmp_path):
    import json

    from fake_llm import FakeLLM, reply

    from doomlab.agents.react import ReactAgent
    from doomlab.llm.budget import Budget
    from doomlab.llm.preflight import Decoding
    from doomlab.runner import arun_episode
    from doomlab.trace import TraceWriter

    llm = FakeLLM([reply("attack", {"burst": 1}), reply("aim_at", {"target_id": 0}), reply("attack", {"burst": 1})])
    agent = ReactAgent(llm, scenario="basic", decoding=Decoding("qwen3.8:27b", 0.0, 512, True), budget=Budget())
    path = tmp_path / "ep.jsonl"
    with TraceWriter(path) as trace:
        result = await arun_episode(FakeSession(target_y=40.0), agent, scenario="basic", seed=0, trace=trace)
    assert result.outcome == "success"
    assert [s.code for s in result.steps] == ["NO_ENEMY_IN_CONE", None, None]  # the model's early attack was rejected
    assert result.llm_calls == 3 and result.tokens == 300
    events = [json.loads(line)["event"] for line in path.read_text().splitlines()]
    assert events[0] == "episode_start" and events[-1] == "episode_end"
    assert events.count("llm_call") == 3 and events.count("tool_exec") == 3 and events.count("observe") == 3


async def test_agent_stop_becomes_the_outcome():
    from fake_llm import FakeLLM, reply

    from doomlab.agents.react import ReactAgent
    from doomlab.llm.budget import Budget
    from doomlab.llm.preflight import Decoding
    from doomlab.runner import arun_episode

    llm = FakeLLM([reply("aim_at", {"target_id": 0})])
    agent = ReactAgent(llm, scenario="basic", decoding=Decoding("qwen3.8:27b", 0.0, 512, True), budget=Budget(max_calls=1))
    result = await arun_episode(FakeSession(target_y=40.0), agent, scenario="basic", seed=0)
    assert (result.outcome, result.stop_reason) == ("timeout", "budget") and result.llm_calls == 1
    assert [s.tool for s in result.steps] == ["aim_at", "wait_until_end"]


def test_death_ends_episode_as_died():
    session = FakeSession(buttons=("TURN_LEFT", "TURN_RIGHT", "MOVE_FORWARD"), target_y=None, health=5.0, drain=1.0, timeout=2100)
    calls = [ToolCall("turn", {"degrees": 90})] * 3
    result = run_episode(session, ScriptAgent(calls), scenario="health_gathering", seed=0)
    assert result.outcome == "died" and result.score == result.tics


def test_defend_success_means_alive_at_time_limit():
    session = FakeSession(buttons=("TURN_LEFT", "TURN_RIGHT", "ATTACK"), target_y=0.0, health=100.0, timeout=40)
    calls = [ToolCall("attack", {"burst": 1})] + [ToolCall("turn", {"degrees": 90})] * 5
    result = run_episode(session, ScriptAgent(calls), scenario="defend_the_center", seed=0)
    assert result.outcome == "success" and result.kills == 1 and result.score == result.tics == 40


def test_scores_are_named_per_scenario():
    from doomlab.runner import SCORES

    assert SCORES["basic"][0] == "tics" and SCORES["defend_the_center"][0] == "survived_tics"
    assert SCORES["health_gathering"][0] == "survived_tics"


def test_looking_again_without_acting_is_rejected_and_counts_toward_recovery():
    calls = [ToolCall("observe", {})] * 5
    result = run_episode(FakeSession(target_y=200.0), ScriptAgent(calls), scenario="basic", seed=0)
    assert [s.code for s in result.steps[:4]] == [None, "NOTHING_CHANGED", "NOTHING_CHANGED", "NOTHING_CHANGED"]
    assert result.stop_reason == "recovery_exhausted"

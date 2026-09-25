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


def test_step_limit_stops_a_stuck_agent():
    result = run_episode(FakeSession(target_y=200.0), StubbornAgent(), scenario="basic", seed=0, max_steps=5)
    assert result.outcome == "step_limit"
    assert len(result.steps) == 5 and result.rejected == 5
    assert all(s.code == "NO_ENEMY_IN_CONE" for s in result.steps)


def test_gave_up_is_recorded():
    result = run_episode(FakeSession(), ScriptAgent([]), scenario="basic", seed=0)
    assert result.outcome == "gave_up" and result.steps == ()


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
    assert result.outcome == "budget" and len(result.steps) == 1 and result.llm_calls == 1

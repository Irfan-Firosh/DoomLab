import pytest
from fake_llm import FakeLLM, reply

from doomlab.agents.base import AgentStop, StepRecord
from doomlab.agents.react import ReactAgent
from doomlab.env.perception import Fact, Observation
from doomlab.llm.budget import Budget
from doomlab.llm.client import LLMError
from doomlab.llm.preflight import Decoding
from doomlab.tools.registry import TOOLS, ToolCall

DECODING = Decoding(model_id="qwen3.8:27b", temperature=0.0, max_tokens=512, disable_thinking=True)
TOOLSET = tuple(TOOLS.values())


def obs(offset=110.0):
    fact = Fact(id=0, name="Cacodemon", kind="enemy", bearing_deg=16.0, ahead=384.0, offset=offset, distance=399.0)
    return Observation(tic=14, facts=(fact,), health=None, ammo=50.0, kills=0.0)


def agent(llm, budget=None):
    return ReactAgent(llm, scenario="basic", decoding=DECODING, budget=budget or Budget())


async def test_returns_the_models_tool_call():
    llm = FakeLLM([reply("aim_at", {"target_id": 0})])
    assert await agent(llm).decide(obs(), TOOLSET, ()) == ToolCall("aim_at", {"target_id": 0})


async def test_request_uses_frozen_decoding_and_scenario_tools():
    llm = FakeLLM([reply("observe")])
    await agent(llm).decide(obs(), (TOOLS["observe"], TOOLS["aim_at"]), ())
    request = llm.requests[0]
    assert [t["function"]["name"] for t in request["tools"]] == ["observe", "aim_at"]
    assert (request["temperature"], request["max_tokens"], request["disable_thinking"]) == (0.0, 512, True)


async def test_prompt_shows_facts_cone_status_and_rejections():
    llm = FakeLLM([reply("aim_at", {"target_id": 0})])
    history = (StepRecord(1, "attack", {"burst": 1}, False, "NO_ENEMY_IN_CONE", "aim first", 0),)
    await agent(llm).decide(obs(offset=110.0), TOOLSET, history)
    system, turn = llm.requests[0]["messages"]
    assert system["role"] == "system" and "one tool" in system["content"]
    assert "[id 0] Cacodemon" in turn["content"] and "IN AIM CONE: no" in turn["content"]
    assert "REJECTED NO_ENEMY_IN_CONE" in turn["content"]
    assert "POSITION" not in turn["content"]  # no raw map coordinates reach the model


async def test_in_cone_enemy_is_marked():
    llm = FakeLLM([reply("attack", {"burst": 1})])
    await agent(llm).decide(obs(offset=3.0), TOOLSET, ())
    assert "IN AIM CONE: yes" in llm.requests[0]["messages"][1]["content"]


async def test_text_reply_gets_one_retry_with_a_reminder():
    llm = FakeLLM([reply(content="I think I should aim."), reply("aim_at", {"target_id": 0})])
    a = agent(llm)
    assert await a.decide(obs(), TOOLSET, ()) == ToolCall("aim_at", {"target_id": 0})
    assert len(llm.requests) == 2 and "exactly one tool" in llm.requests[1]["messages"][-1]["content"]
    assert [e["event"] for e in a.drain_events()] == ["llm_call", "llm_call"]


async def test_two_text_replies_stop_with_no_tool_call():
    llm = FakeLLM([reply(content="hmm"), reply(content="still thinking")])
    with pytest.raises(AgentStop) as stop:
        await agent(llm).decide(obs(), TOOLSET, ())
    assert stop.value.outcome == "no_tool_call"


async def test_budget_stops_the_agent_before_calling():
    llm = FakeLLM([])
    with pytest.raises(AgentStop) as stop:
        await agent(llm, Budget(max_calls=0)).decide(obs(), TOOLSET, ())
    assert stop.value.outcome == "budget" and llm.requests == []


async def test_transient_error_retries_then_stops():
    llm = FakeLLM([LLMError("timeout", "slow"), LLMError("timeout", "slow")])
    with pytest.raises(AgentStop) as stop:
        await agent(llm).decide(obs(), TOOLSET, ())
    assert stop.value.outcome == "llm_error"


async def test_auth_error_is_fatal():
    llm = FakeLLM([LLMError("auth", "bad key")])
    with pytest.raises(LLMError):
        await agent(llm).decide(obs(), TOOLSET, ())


async def test_events_record_latency_and_tokens():
    llm = FakeLLM([reply("aim_at", {"target_id": 0}, tokens=380)])
    a = agent(llm)
    await a.decide(obs(), TOOLSET, ())
    (event,) = a.drain_events()
    assert event["latency_s"] == 0.5 and event["usage"]["total_tokens"] == 380
    assert event["tool_calls"] == [{"name": "aim_at", "arguments": {"target_id": 0}}]
    assert a.drain_events() == []  # drained


def test_prompt_leads_with_the_rejection_to_recover_from():
    from doomlab.agents.base import StepRecord
    from doomlab.agents.prompting import turn_prompt
    from doomlab.env.perception import Observation

    rejected = StepRecord(step=1, tool="attack", args={"burst": 1}, ok=False, code="NO_ENEMY_IN_CONE",
                          message="aim first", tics_used=0)
    prompt = turn_prompt(Observation(tic=1, facts=(), health=100.0, ammo=5.0, kills=0.0), (rejected,))
    assert prompt.splitlines()[0] == "YOUR LAST CALL WAS REJECTED: attack(burst=1) -> NO_ENEMY_IN_CONE: aim first"
    assert "1 of 3" in prompt
    ok = StepRecord(step=2, tool="observe", args={}, ok=True, code=None, message="looked around", tics_used=0)
    assert "REJECTED:" not in turn_prompt(Observation(tic=1, facts=(), health=100.0, ammo=5.0, kills=0.0), (rejected, ok))


def test_every_scored_scenario_tells_the_model_how_it_is_scored():
    from doomlab.agents.prompting import system_prompt
    from doomlab.runner import SCORES

    for scenario, (score, higher_is_better) in SCORES.items():
        prompt = system_prompt(scenario)
        assert "Score:" in prompt
        assert ("more is better" if higher_is_better else "fewer is better") in prompt, scenario


def test_attack_description_says_one_hit_usually_kills():
    assert "One hit usually kills" in TOOLS["attack"].description

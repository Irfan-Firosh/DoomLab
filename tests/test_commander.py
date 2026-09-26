import json

import pytest
from fake_llm import FakeLLM, reply
from fakes import FakeSession

from doomlab.agents.base import AgentStop, StepRecord
from doomlab.agents.commander import CommanderTeam, choose_mode_spec
from doomlab.agents.modes import FIGHT, NAVIGATE, available_modes, role_tools
from doomlab.env.perception import Fact, Observation
from doomlab.graph.router import commander_trigger, route
from doomlab.llm.budget import Budget
from doomlab.llm.preflight import Decoding
from doomlab.runner import arun_episode
from doomlab.tools.executor import Executor
from doomlab.tools.registry import TOOLS, available_tools, validate_args
from doomlab.trace import TraceWriter

DECODING = Decoding(model_id="qwen3.8:27b", temperature=0.0, max_tokens=512, disable_thinking=True)
BASIC = ("MOVE_LEFT", "MOVE_RIGHT", "ATTACK")
DEFEND = ("TURN_LEFT", "TURN_RIGHT", "ATTACK")
HEALTH = ("TURN_LEFT", "TURN_RIGHT", "MOVE_FORWARD")
ENEMY = Fact(id=0, name="Demon", kind="enemy", bearing_deg=10.0, ahead=300.0, offset=50.0, distance=304.0)


def names(specs):
    return [s.name for s in specs]


def obs(*facts, ammo=26.0):
    return Observation(tic=1, facts=facts, health=100.0, ammo=ammo, kills=0.0)


def team(llm, scenario="defend_the_center", budget=None):
    return CommanderTeam(llm, scenario=scenario, decoding=DECODING, budget=budget or Budget())


# ------------------------------------------------------------ modes and roles


def test_modes_offered_per_scenario():
    assert available_modes(available_tools(BASIC)) == (FIGHT,)
    assert available_modes(available_tools(DEFEND)) == (FIGHT, NAVIGATE)
    assert available_modes(available_tools(HEALTH)) == (NAVIGATE,)


def test_each_specialist_sees_only_its_own_tools():
    defend = available_tools(DEFEND)
    assert names(role_tools(FIGHT, defend)) == ["observe", "aim_at", "attack"]
    assert names(role_tools(NAVIGATE, defend)) == ["observe", "turn"]  # no go_to: cannot walk here
    assert names(role_tools(NAVIGATE, available_tools(HEALTH))) == ["observe", "turn", "go_to"]


def test_string_and_enum_arguments_are_checked():
    spec = choose_mode_spec(("fight", "navigate"))
    assert validate_args(spec, {"mode": "fight", "reason": "enemy spotted"}) is None
    assert validate_args(spec, {"mode": "fight", "reason": 3}) == "reason must be a string"
    assert validate_args(spec, {"mode": "dance"}) == "mode must be one of ['fight', 'navigate']"


# ------------------------------------------------------------ executor: roles


def test_out_of_role_call_is_rejected_by_the_executor():
    executor = Executor(FakeSession(buttons=DEFEND, target_y=0.0, health=100.0, timeout=2100))
    navigator = role_tools(NAVIGATE, executor.tools)
    result = executor.execute("attack", {"burst": 1}, allowed=navigator)
    assert (result.ok, result.code, result.tics_used) == (False, "OUT_OF_ROLE", 0)
    assert "navigate" not in result.message and "attack" in result.message


def test_tool_missing_from_the_scenario_is_unavailable_not_out_of_role():
    executor = Executor(FakeSession(buttons=DEFEND, target_y=None, health=100.0, timeout=2100))
    result = executor.execute("go_to", {"target_id": 0}, allowed=role_tools(NAVIGATE, executor.tools))
    assert result.code == "UNAVAILABLE_TOOL"


# ------------------------------------------------------------ triggers and router


def _step(tool, ok=True, **args):
    return StepRecord(step=1, tool=tool, args=args, ok=ok, code=None if ok else "BAD_ARGS", message="", tics_used=0)


BOTH = (FIGHT, NAVIGATE)


def test_trigger_rules():
    assert commander_trigger(None, BOTH, (), obs(), enemy_at_choice=False) == "no mode yet"
    assert commander_trigger(FIGHT, BOTH, (), obs(), enemy_at_choice=True) == "fight mode but no enemy visible"
    assert commander_trigger(FIGHT, BOTH, (), obs(ENEMY, ammo=0.0), enemy_at_choice=True) == "fight mode but out of ammo"
    assert commander_trigger(FIGHT, BOTH, (), obs(ENEMY), enemy_at_choice=True) is None
    assert commander_trigger(NAVIGATE, BOTH, (), obs(ENEMY), enemy_at_choice=False) == "enemy appeared while navigating"


def test_navigating_past_an_enemy_the_commander_already_saw_does_not_re_ask():
    assert commander_trigger(NAVIGATE, BOTH, (), obs(ENEMY), enemy_at_choice=True) is None
    assert commander_trigger(NAVIGATE, BOTH, (), obs(ENEMY, ammo=0.0), enemy_at_choice=False) is None  # cannot fight


def test_one_mode_scenarios_never_re_ask_after_the_first_choice():
    assert commander_trigger(None, (FIGHT,), (), obs(), enemy_at_choice=False) == "no mode yet"
    assert commander_trigger(FIGHT, (FIGHT,), (), obs(), enemy_at_choice=False) is None


def test_router_continues_without_a_trigger_and_plans_with_one():
    assert route((), finished=False, max_steps=9, stopped=None, team=True, trigger=None, mode=FIGHT).next == "continue"
    planned = route((), finished=False, max_steps=9, stopped=None, team=True, trigger="no mode yet", mode=None)
    assert (planned.next, planned.why) == ("plan", "no mode yet")
    rejected = (_step("attack", ok=False),)
    assert route(rejected, finished=False, max_steps=9, stopped=None, team=True, trigger="x", mode=FIGHT).next == "recover"


# ------------------------------------------------------------ commander agent


async def test_single_mode_is_chosen_without_asking_the_model():
    llm = FakeLLM([])
    choice = await team(llm, "basic").choose_mode(obs(), (FIGHT,), (), trigger="no mode yet", current=None)
    assert (choice.mode, choice.auto) == (FIGHT, True) and llm.requests == []


async def test_commander_is_offered_only_choose_mode_with_the_valid_modes():
    llm = FakeLLM([reply("choose_mode", {"mode": "navigate", "reason": "nothing visible"})])
    choice = await team(llm).choose_mode(obs(), BOTH, (), trigger="no mode yet", current=None)
    assert (choice.mode, choice.reason, choice.auto) == (NAVIGATE, "nothing visible", False)
    (tool,) = llm.requests[0]["tools"]
    assert tool["function"]["name"] == "choose_mode"
    assert tool["function"]["parameters"]["properties"]["mode"]["enum"] == ["fight", "navigate"]
    prompt = llm.requests[0]["messages"][1]["content"]
    assert "no mode yet" in prompt and "Current mode: none" in prompt


async def test_invalid_mode_is_retried_once_then_stops():
    llm = FakeLLM([reply("choose_mode", {"mode": "dance"}), reply("choose_mode", {"mode": "dance"})])
    with pytest.raises(AgentStop) as stop:
        await team(llm).choose_mode(obs(), BOTH, (), trigger="no mode yet", current=None)
    assert stop.value.outcome == "no_valid_mode" and len(llm.requests) == 2
    assert "invalid" in llm.requests[1]["messages"][-1]["content"]


async def test_specialists_have_their_own_system_prompts_and_share_one_budget():
    budget = Budget(max_calls=2)
    llm = FakeLLM([reply("choose_mode", {"mode": "fight"}), reply("aim_at", {"target_id": 0})])
    t = team(llm, budget=budget)
    await t.choose_mode(obs(ENEMY), BOTH, (), trigger="no mode yet", current=None)
    await t.specialist(FIGHT).decide(obs(ENEMY), role_tools(FIGHT, available_tools(DEFEND)), ())
    assert "Combat specialist" in llm.requests[1]["messages"][0]["content"]
    assert budget.calls == 2
    with pytest.raises(AgentStop) as stop:
        await t.specialist(NAVIGATE).decide(obs(), role_tools(NAVIGATE, available_tools(DEFEND)), ())
    assert stop.value.outcome == "budget"
    assert [e["role"] for e in t.drain_events()] == ["commander", "fight"]


# ------------------------------------------------------------ whole episodes on the fake game


async def _play(session, llm, scenario, tmp_path, budget):
    path = tmp_path / "ep.jsonl"
    with TraceWriter(path) as trace:
        result = await arun_episode(session, team(llm, scenario, budget), scenario=scenario, seed=0, trace=trace)
    return result, [json.loads(line) for line in path.read_text().splitlines()]


async def test_trace_shows_fight_then_navigate_switch(tmp_path):
    session = FakeSession(buttons=DEFEND, target_y=40.0, target_name="Demon", health=100.0, timeout=2100)
    llm = FakeLLM([
        reply("choose_mode", {"mode": "fight", "reason": "demon ahead"}),
        reply("aim_at", {"target_id": 0}),
        reply("attack", {"burst": 1}),                      # kill: the demon disappears
        reply("choose_mode", {"mode": "navigate", "reason": "look for more"}),
        reply("turn", {"degrees": 90}),
        reply("turn", {"degrees": 90}),
    ])
    result, events = await _play(session, llm, "defend_the_center", tmp_path, Budget(max_calls=6))
    assert result.kills == 1 and result.stop_reason == "budget"
    modes = [(e["mode"], e["trigger"]) for e in events if e["event"] == "mode"]
    assert modes == [
        ("fight", "no mode yet"),
        ("navigate", "fight mode but no enemy visible"),
    ]
    roles = [e["role"] for e in events if e["event"] == "llm_call"]
    assert roles == ["commander", "fight", "fight", "commander", "navigate", "navigate"]
    hops = [(e["from"], e["to"], e.get("why")) for e in events if e["event"] == "transition"]
    assert ("route", "plan", "stay in fight mode") in hops  # CONTINUE: the attack needed no commander call
    assert ("route", "commander", "fight mode but no enemy visible") in hops
    offered = [[t["function"]["name"] for t in r["tools"]] for r in llm.requests]
    assert offered[1] == ["observe", "aim_at", "attack"]
    assert offered[4] == ["observe", "turn"]
    assert [s.tool for s in result.steps][-1] == "wait_until_end"


async def test_out_of_role_call_is_recovered_by_the_same_specialist(tmp_path):
    session = FakeSession(buttons=DEFEND, target_y=None, health=100.0, timeout=2100)
    llm = FakeLLM([
        reply("choose_mode", {"mode": "navigate"}),
        reply("attack", {"burst": 1}),  # the navigator reaches for a combat tool
        reply("turn", {"degrees": 90}),
    ])
    result, events = await _play(session, llm, "defend_the_center", tmp_path, Budget(max_calls=3))
    assert [s.code for s in result.steps] == ["OUT_OF_ROLE", None, None]
    assert ("route", "recover") in [(e["from"], e["to"]) for e in events if e["event"] == "transition"]
    recovery_prompt = llm.requests[2]["messages"][1]["content"]
    assert recovery_prompt.startswith("YOUR LAST CALL WAS REJECTED: attack(burst=1) -> OUT_OF_ROLE")


async def test_basic_needs_no_commander_call(tmp_path):
    llm = FakeLLM([reply("aim_at", {"target_id": 0}), reply("attack", {"burst": 1})])
    result, events = await _play(FakeSession(target_y=40.0), llm, "basic", tmp_path, Budget())
    assert result.outcome == "success" and result.llm_calls == 2
    (mode,) = [e for e in events if e["event"] == "mode"]
    assert (mode["mode"], mode["auto"]) == ("fight", True)

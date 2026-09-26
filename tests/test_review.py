import json

import pytest
from fake_llm import FakeLLM, reply

from doomlab.review.corrections import (
    append_record, cases, check_call, context_from, expectation, load_records, meets, parse_call, record,
)
from doomlab.review.flags import episode_steps, shortlist
from doomlab.review.regress import run_regression
from doomlab.review.session import run_review
from doomlab.tools.registry import ToolCall

MEDIKIT = {"id": 12, "name": "Medikit", "kind": "item", "bearing_deg": 5.0, "ahead": 179.0, "offset": 16.0, "distance": 180.0}
DEMON = {"id": 3, "name": "Demon", "kind": "enemy", "bearing_deg": 10.0, "ahead": 300.0, "offset": 50.0, "distance": 304.0}


def observe(step, facts, health=100.0, ammo=26.0):
    return {"event": "observe", "step": step, "tic": step * 10, "ammo": ammo, "health": health, "kills": 0.0, "facts": facts}


def exe(step, tool, args, ok=True, code=None, **extra):
    return {"event": "tool_exec", "step": step, "tool": tool, "args": args, "ok": ok, "code": code,
            "message": "m", "tics": 5 if ok else 0, "buttons": [], **extra}


def write_trace(path, events, *, scenario="health_gathering_supreme", seed=3, agent="react_single",
                tools=("observe", "aim_at", "turn", "go_to"), dead=True):
    start = {"event": "episode_start", "scenario": scenario, "seed": seed, "agent": agent, "tools": list(tools),
             "buttons": ["TURN_LEFT", "TURN_RIGHT", "MOVE_FORWARD"]}
    end = {"event": "episode_end", "outcome": "died" if dead else "timeout", "dead": dead, "score": 500.0}
    path.write_text("\n".join(json.dumps(e) for e in [start, *events, end]) + "\n")
    return path


@pytest.fixture
def supreme(tmp_path):
    events = []
    for n in range(1, 9):
        health = 80.0 - 8 * n
        events += [observe(n, [MEDIKIT], health=health), exe(n, "turn", {"degrees": 90})]
    return write_trace(tmp_path / "health_gathering_supreme-s3-react_single.jsonl", events)


# ------------------------------------------------------------ rebuilding decisions and flagging them


def test_each_decision_is_rebuilt_with_what_the_agent_saw_and_its_history(supreme):
    steps, _ = episode_steps(supreme)
    assert len(steps) == 8
    fifth = steps[4]
    assert (fifth.step, fifth.call.name, fifth.observation.health) == (5, "turn", 40.0)
    assert [h.step for h in fifth.history] == [1, 2, 3, 4] and fifth.tools == ("observe", "aim_at", "turn", "go_to")


def test_shortlist_flags_ignored_medikits_and_the_steps_before_death_once_each(supreme):
    flags = shortlist([supreme])
    reasons = [(f.reason, f.step.step) for f in flags]
    assert ("medikit_ignored", 4) in reasons  # first time health fell below 50 (48) with a medikit in view
    assert [r for r in reasons if r[0] == "before_death"] == [("before_death", 6)]
    assert len({f.step.step for f in flags}) == len(flags)  # never the same step twice


def test_rejections_and_blind_shots_are_flagged(tmp_path):
    events = [observe(1, [DEMON]), exe(1, "attack", {"burst": 1}, ok=False, code="NO_ENEMY_IN_CONE"),
              observe(2, [DEMON]), exe(2, "turn", {"degrees": 90}),
              observe(3, [DEMON]), exe(3, "attack", {"burst": 3})]
    path = write_trace(tmp_path / "defend_the_center-s1-commander.jsonl", events, scenario="defend_the_center",
                       seed=1, agent="commander", tools=("observe", "aim_at", "attack", "turn"), dead=False)
    reasons = {f.reason for f in shortlist([path])}
    assert reasons == {"premature_attack", "turned_from_enemy", "wasteful_burst"}


def test_test_split_episodes_are_refused(tmp_path):
    path = write_trace(tmp_path / "basic-s1003-react_single.jsonl", [], scenario="basic", seed=1003)
    with pytest.raises(ValueError, match="test"):
        shortlist([path])


# ------------------------------------------------------------ corrections


def test_parse_and_check_a_corrected_call(supreme):
    step = episode_steps(supreme)[0][4]
    assert parse_call("go_to(target_id=12)") == ToolCall("go_to", {"target_id": 12})
    assert parse_call("observe()") == ToolCall("observe", {})
    with pytest.raises(ValueError):
        parse_call("go to the medikit")
    assert check_call(ToolCall("go_to", {"target_id": 12}), step) is None
    assert "not visible" in check_call(ToolCall("go_to", {"target_id": 99}), step)
    assert "not on this agent's menu" in check_call(ToolCall("attack", {"burst": 1}), step)


def test_expectations():
    exact = expectation("turn", ToolCall("go_to", {"target_id": 12}))
    assert meets(exact, ToolCall("go_to", {"target_id": 12})) and not meets(exact, ToolCall("go_to", {"target_id": 3}))
    assert not meets(exact, ToolCall("turn", {"degrees": 90}))
    turn_ok = expectation("attack", ToolCall("turn", {"degrees": 45}))
    assert meets(turn_ok, ToolCall("turn", {"degrees": -30}))  # untargeted tools: the tool is what matters
    one_shot = expectation("attack", ToolCall("attack", {"burst": 1}))
    assert meets(one_shot, ToolCall("attack", {"burst": 1})) and not meets(one_shot, ToolCall("attack", {"burst": 4}))
    avoid = expectation("attack", None)
    assert meets(avoid, ToolCall("aim_at", {"target_id": 3})) and not meets(avoid, ToolCall("attack", {"burst": 1}))


def test_a_record_carries_a_snapshot_that_rebuilds_the_moment_without_the_trace(supreme, tmp_path):
    flag = shortlist([supreme])[0]
    rec = record(flag, "rc-001", "missed_pickup", "take the medikit when health is low", ToolCall("go_to", {"target_id": 12}))
    supreme.unlink()  # the regression case must not need runs/
    observation, history, tools = context_from(rec["snapshot"])
    assert observation.facts[0].name == "Medikit" and [t.name for t in tools] == ["observe", "aim_at", "turn", "go_to"]
    assert len(history) == flag.step.step - 1


# ------------------------------------------------------------ the interactive session


def test_session_saves_corrections_and_skips_and_resumes_where_it_stopped(supreme, tmp_path):
    store = tmp_path / "corrections.jsonl"
    answers = iter(["c", "4", "take the medikit when health is low", "go_to(target_id=99)", "go_to(target_id=12)",
                    "s", "q"])
    out = []
    run_review(shortlist([supreme]), store, ask=lambda _: next(answers), say=out.append)
    records = load_records(store)
    assert [r["action"] for r in records] == ["corrected", "skipped"]
    first = records[0]
    assert (first["label"], first["expect"]) == ("missed_pickup", {"kind": "call", "tool": "go_to", "args": {"target_id": 12}})
    assert any("not visible" in line for line in out)  # the bad corrected call was explained and asked again
    seen, said = [], []
    run_review(shortlist([supreme]), store, ask=lambda prompt: seen.append(prompt) or "q", say=said.append)
    assert seen == [] and "nothing left" in said[-1]  # both flags were reviewed: it resumes past them
    assert [c["id"] for c in cases(store)] == ["rc-001"]


def test_ids_keep_counting_across_sessions(supreme, tmp_path):
    store = tmp_path / "corrections.jsonl"
    flag = shortlist([supreme])[0]
    append_record(store, record(flag, "rc-001", "other", "x", None))
    answers = iter(["c", "other", "y", "", "q"])
    run_review(shortlist([supreme]), store, ask=lambda _: next(answers), say=lambda _: None)
    assert [c["id"] for c in cases(store)] == ["rc-001", "rc-002"]


# ------------------------------------------------------------ regression


async def test_regression_asks_the_agent_about_each_saved_moment(supreme, tmp_path):
    flag = shortlist([supreme])[0]
    good = record(flag, "rc-001", "missed_pickup", "take it", ToolCall("go_to", {"target_id": 12}))
    bad = record(flag, "rc-002", "wrong_tool", "do not spin", None)
    llm = FakeLLM([reply("go_to", {"target_id": 12}), reply("turn", {"degrees": 90})])
    from doomlab.agents.react import ReactAgent
    from doomlab.llm.budget import Budget
    from doomlab.llm.preflight import Decoding

    decoding = Decoding("qwen3.8:27b", 0.0, 512, True)
    results = await run_regression([good, bad], lambda case: ReactAgent(llm, scenario=case["snapshot"]["scenario"],
                                                                        decoding=decoding, budget=Budget()))
    assert [(r["id"], r["passed"], r["votes"]) for r in results] == [("rc-001", True, 1), ("rc-002", False, 0)]
    assert results[1]["chose"] == "turn(degrees=90)"
    prompt = llm.requests[0]["messages"][1]["content"]
    assert "[id 12] Medikit" in prompt and "health 48" in prompt  # the saved moment, exactly as the agent saw it


def test_records_say_who_wrote_them(supreme):
    flag = shortlist([supreme])[0]
    mine = record(flag, "rc-001", "other", "x", None)
    drafted = record(flag, "rc-002", "other", "x", None, author="assistant", source="vizdoom docs")
    assert (mine["author"], mine["approved_by_human"]) == ("human", True)
    assert (drafted["author"], drafted["approved_by_human"], drafted["source"]) == ("assistant", False, "vizdoom docs")


async def test_regression_votes_over_repeated_asks(supreme):
    from doomlab.agents.react import ReactAgent
    from doomlab.llm.budget import Budget
    from doomlab.llm.preflight import Decoding

    flag = shortlist([supreme])[0]
    case = record(flag, "rc-001", "missed_pickup", "take it", ToolCall("go_to", {"target_id": 12}))
    llm = FakeLLM([reply("go_to", {"target_id": 12}), reply("turn", {"degrees": 90}), reply("go_to", {"target_id": 12})])
    agent = ReactAgent(llm, scenario="health_gathering_supreme", decoding=Decoding("qwen3.8:27b", 0.0, 512, True),
                       budget=Budget())
    (result,) = await run_regression([case], lambda _: agent, repeats=3, votes_to_pass=2)
    assert (result["votes"], result["asked"], result["passed"]) == (2, 3, True)
    assert result["chose"] == "go_to(target_id=12) | turn(degrees=90) | go_to(target_id=12)"

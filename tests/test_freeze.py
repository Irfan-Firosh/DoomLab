import json

import pytest
from fakes import FakeSession

from doomlab.agents import prompting
from doomlab.agents.scripted import ScriptedAgent
from doomlab.eval.harness import check_folder, plan, run_jobs
from doomlab.freeze import FreezeError, fingerprint, load_frozen, recipe, write_frozen
from doomlab.policy import Policy, PolicyError, load_policy

DECODING = {"model_id": "qwen3.8:27b", "temperature": 0.0, "max_tokens": 512, "thinking": "off"}
V0 = Policy(version="v0", lessons=())


def test_recipe_holds_everything_that_shapes_an_llm_agent():
    r = recipe(DECODING, V0)
    assert r["model"] == DECODING
    assert r["rate"]["requests_per_minute"] == 18
    assert r["budgets"]["calls"] == {"basic": 20, "defend_the_center": 150, "health_gathering": 80,
                                     "health_gathering_supreme": 80}
    assert set(r["prompts"]["system"]) >= {"basic", "defend_the_center", "health_gathering_supreme"}
    assert "Combat specialist" in r["prompts"]["specialist"]["defend_the_center"]["fight"]
    assert "YOUR LAST CALL WAS REJECTED" in r["prompts"]["turn_example"]
    assert [t["function"]["name"] for t in r["tools"]] == ["observe", "aim_at", "attack", "turn", "go_to", "choose_mode"]
    assert r["harness"]["max_consecutive_rejections"] == 3
    assert "src/doomlab/tools/executor.py" in r["code"]
    assert r["policy"] == {"version": "v0", "lessons": []}


def test_fingerprint_is_stable_and_changes_with_any_prompt_or_lesson(monkeypatch):
    base = fingerprint(recipe(DECODING, V0))
    assert base == fingerprint(recipe(DECODING, V0)) and len(base) == 64
    assert fingerprint(recipe(DECODING, Policy("v1", ("Aim before you shoot.",)))) != base
    assert fingerprint(recipe({**DECODING, "temperature": 0.2}, V0)) != base
    monkeypatch.setitem(prompting.GOALS, "basic", "Kill it.")
    assert fingerprint(recipe(DECODING, V0)) != base


def test_frozen_file_round_trip(tmp_path):
    path = tmp_path / "frozen.json"
    written = write_frozen(recipe(DECODING, V0), path, name="frozen-v0")
    loaded = load_frozen(path)
    assert loaded["name"] == "frozen-v0" and loaded["hash"] == written["hash"] == fingerprint(loaded["recipe"])


def test_a_tampered_frozen_file_is_refused(tmp_path):
    path = tmp_path / "frozen.json"
    write_frozen(recipe(DECODING, V0), path, name="frozen-v0")
    data = json.loads(path.read_text())
    data["recipe"]["budgets"]["calls"]["basic"] = 999
    path.write_text(json.dumps(data))
    with pytest.raises(FreezeError, match="does not match"):
        load_frozen(path)


# ------------------------------------------------------------ policy (lessons)


def test_policy_lessons_reach_every_system_prompt(tmp_path):
    lessons = ("Aim before you shoot.",)
    assert prompting.system_prompt("basic", lessons=lessons).endswith("Lessons from earlier games:\n- Aim before you shoot.")
    assert "Aim before you shoot." in prompting.system_prompt("defend_the_center", "fight", lessons=lessons)
    assert "Aim before you shoot." in prompting.commander_system_prompt("defend_the_center", lessons=lessons)
    assert "Lessons" not in prompting.system_prompt("basic")  # v0: prompts unchanged


def test_policy_file_limits(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"version": "v1", "lessons": ["a" * 301]}))
    with pytest.raises(PolicyError, match="300"):
        load_policy(path)
    path.write_text(json.dumps({"version": "v1", "lessons": ["a", "b", "c", "d"]}))
    with pytest.raises(PolicyError, match="3"):
        load_policy(path)
    path.write_text(json.dumps({"version": "v1", "lessons": ["Aim first."]}))
    assert load_policy(path) == Policy("v1", ("Aim first.",))


def test_the_committed_v0_policy_has_no_lessons():
    assert load_policy() == V0


# ------------------------------------------------------------ fingerprints in traces and folders


def fake_session(scenario, seed):
    return FakeSession(target_y=20.0)


async def test_every_trace_records_the_recipe_fingerprint_and_folders_never_mix(tmp_path):
    jobs = plan((0,), ("basic",), ("scripted",))
    await run_jobs(jobs, tmp_path, lambda v, s, seed: ScriptedAgent(), make_session=fake_session,
                   progress=lambda _: None, config_hash="aaa")
    start = json.loads((tmp_path / jobs[0].trace_name).read_text().splitlines()[0])
    assert start["config_hash"] == "aaa"
    check_folder(tmp_path, "aaa")  # same recipe: fine to resume
    with pytest.raises(FreezeError, match="another recipe"):
        check_folder(tmp_path, "bbb")

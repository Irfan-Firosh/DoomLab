import json

import pytest
from fake_llm import FakeLLM, reply
from fakes import FakeSession

from doomlab.agents.scripted import ScriptedAgent
from doomlab.improve.analyst import AnalystError, analyst_prompt, check_lessons, propose
from doomlab.improve.gate import GateRules
from doomlab.improve.trial import record_decision, run_trial
from doomlab.llm.budget import Budget
from doomlab.llm.preflight import Decoding
from doomlab.policy import Policy, load_policy
from doomlab.policy_registry import active_policy_path

DECODING = Decoding("qwen3.8:27b", 0.0, 512, True)
REPORT = {"episodes": 30, "decisions": 1705, "signatures": [
    {"name": "needless_observe", "meaning": "called observe, which shows nothing new", "occurrences": 322,
     "episodes": 20, "by_variant": {"react_single": 184}, "examples": ["x.jsonl#4"]},
    {"name": "medikit_ignored", "meaning": "did not go to a visible medikit", "occurrences": 16, "episodes": 3,
     "by_variant": {"react_single": 13}, "examples": ["y.jsonl#26"]},
]}
CASES = [
    {"id": "rc-001", "author": "human", "label": "missed_pickup", "fix": "pick up closest medkit at low health",
     "original": {"tool": "turn", "args": {"degrees": -90}}, "expect": {"kind": "call", "tool": "go_to", "args": {"target_id": 33}},
     "snapshot": {"scenario": "health_gathering_supreme"}},
    {"id": "rc-004", "author": "assistant", "label": "wrong_tool", "fix": "turn instead of observe",
     "original": {"tool": "observe", "args": {}}, "expect": {"kind": "call", "tool": "turn", "args": {}},
     "snapshot": {"scenario": "health_gathering_supreme"}},
]
GOOD = [{"text": "Never call observe: the facts you are given are already current. Act instead.",
         "evidence": ["needless_observe", "rc-004"]},
        {"text": "When health is below 50 and a medikit is visible, go_to the nearest medikit.",
         "evidence": ["medikit_ignored", "rc-001"]}]


# ------------------------------------------------------------ analyst


def test_prompt_carries_counts_and_corrections_but_says_who_wrote_them():
    prompt = analyst_prompt(REPORT, CASES, scenario="health_gathering_supreme", variant="react_single")
    assert "needless_observe" in prompt and "322" in prompt and "20/30" in prompt
    assert "rc-001 (human)" in prompt and "rc-004 (AI-drafted)" in prompt and "pick up closest medkit" in prompt


def test_lessons_are_checked_before_they_become_a_policy():
    known = {"needless_observe", "medikit_ignored", "rc-001", "rc-004"}
    assert check_lessons(GOOD, known) is None
    assert "at most 3" in check_lessons(GOOD * 2, known)
    assert "300" in check_lessons([{"text": "x" * 301, "evidence": ["rc-001"]}], known)
    assert "unknown evidence" in check_lessons([{"text": "Aim first.", "evidence": ["rc-999"]}], known)
    assert "cite" in check_lessons([{"text": "Aim first.", "evidence": []}], known)
    assert "object id" in check_lessons([{"text": "Go to target_id 33 first.", "evidence": ["rc-001"]}], known)


async def test_analyst_retries_once_then_writes_a_policy_with_provenance(tmp_path):
    bad = [{"text": "Aim first.", "evidence": ["rc-999"]}]
    llm = FakeLLM([reply("propose_lessons", {"lessons": bad}), reply("propose_lessons", {"lessons": GOOD})])
    path = tmp_path / "v1.json"
    policy = await propose(llm, DECODING, Budget(), REPORT, CASES, scenario="health_gathering_supreme",
                           variant="react_single", parent=Policy("v0"), out=path)
    assert policy == Policy("v1", tuple(lesson["text"] for lesson in GOOD))
    saved = json.loads(path.read_text())
    assert saved["parent"] == "v0" and saved["evidence"] == [lesson["evidence"] for lesson in GOOD]
    assert "unknown evidence" in llm.requests[1]["messages"][-1]["content"]
    assert load_policy(path) == policy


async def test_analyst_gives_up_after_two_bad_proposals(tmp_path):
    bad = {"lessons": [{"text": "x" * 400, "evidence": ["rc-001"]}]}
    llm = FakeLLM([reply("propose_lessons", bad), reply("propose_lessons", bad)])
    with pytest.raises(AnalystError):
        await propose(llm, DECODING, Budget(), REPORT, CASES, scenario="health_gathering_supreme",
                      variant="react_single", parent=Policy("v0"), out=tmp_path / "v1.json")


# ------------------------------------------------------------ the trial, end to end on the fake game


async def test_trial_alternates_seeds_scores_both_policies_and_gates(tmp_path):
    played = []

    def make_session(scenario, seed):
        return FakeSession(target_y=20.0 + seed % 10)

    def make_agent(policy, variant, scenario, seed):
        played.append((policy.version, seed))
        return ScriptedAgent()

    async def regress(policy):
        passed = policy.version == "v1"
        return [{"id": "rc-001", "votes": 3 if passed else 0, "asked": 3, "passed": passed}]

    result = await run_trial(
        parent=Policy("v0"), candidate=Policy("v1", ("Aim first.",)), scenario="basic", variant="react_single",
        seeds=(100, 101), rules=GateRules(), rules_fingerprint="f" * 64, corrections=CASES, out_dir=tmp_path,
        make_agent=make_agent, make_session=make_session, regress=regress, decoding=None, progress=lambda _: None)
    assert played == [("v0", 100), ("v1", 100), ("v0", 101), ("v1", 101)]
    assert result["verdict"] in {"promote", "reject", "inconclusive"}
    assert result["regression"]["passed"] == {"v0": 0, "v1": 1}
    assert result["corrections"] == {"total": 2, "human": 1, "assistant_drafted": 1, "approved_by_human": 1}
    assert result["human_decision"] is None and result["candidate"]["lessons"] == ["Aim first."]
    assert (tmp_path / "gate_result.json").exists()
    assert json.loads((tmp_path / "ab" / "v1" / "basic-s100-react_single.jsonl").read_text().splitlines()[0])["config_hash"]


# ------------------------------------------------------------ your decision and the registry


def _gate(tmp_path, verdict):
    path = tmp_path / "gate_result.json"
    path.write_text(json.dumps({"verdict": verdict, "candidate": {"policy": "v1", "file": "v1.json"},
                                "human_decision": None}))
    return path


def test_approving_a_promoted_policy_points_new_runs_at_it(tmp_path):
    active = tmp_path / "active.json"
    record_decision(_gate(tmp_path, "promote"), "approve", note="fewer wasted calls", active=active)
    decided = json.loads((tmp_path / "gate_result.json").read_text())["human_decision"]
    assert decided["decision"] == "approve" and decided["note"] == "fewer wasted calls"
    assert json.loads(active.read_text())["active"] == "v1.json"


def test_rejecting_leaves_the_registry_alone(tmp_path):
    active = tmp_path / "active.json"
    record_decision(_gate(tmp_path, "promote"), "reject", note="", active=active)
    assert not active.exists()


def test_approving_against_the_gate_needs_an_explicit_override(tmp_path):
    with pytest.raises(ValueError, match="override"):
        record_decision(_gate(tmp_path, "inconclusive"), "approve", note="", active=tmp_path / "active.json")
    record_decision(_gate(tmp_path, "inconclusive"), "approve", note="I accept the risk", active=tmp_path / "a.json",
                    override=True)


def test_without_a_registry_the_active_policy_is_v0(tmp_path):
    assert active_policy_path(tmp_path / "missing.json").name == "v0.json"

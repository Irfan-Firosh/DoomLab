import json

import pytest

from doomlab.eval.scorers import EpisodeMetrics
from doomlab.improve.gate import GateRules, decide, load_rules, passed_by_votes
from doomlab.improve.miner import mine
from doomlab.review.flags import turned_away

MEDIKIT = {"id": 12, "name": "Medikit", "kind": "item", "bearing_deg": 5.0, "ahead": 179.0, "offset": 16.0, "distance": 180.0}
DEMON_LEFT = {"id": 3, "name": "Demon", "kind": "enemy", "bearing_deg": 30.0, "ahead": 260.0, "offset": 150.0, "distance": 300.0}


def observe(step, facts, health=100.0, ammo=26.0):
    return {"event": "observe", "step": step, "tic": step * 10, "ammo": ammo, "health": health, "kills": 0.0, "facts": facts}


def exe(step, tool, args, ok=True, code=None):
    return {"event": "tool_exec", "step": step, "tool": tool, "args": args, "ok": ok, "code": code,
            "message": "m", "tics": 5 if ok else 0, "buttons": []}


def trace(path, events, *, scenario="defend_the_center", seed=0, agent="react_single", dead=True, tics=900,
          stop_reason=None, tools=("observe", "aim_at", "attack", "turn")):
    start = {"event": "episode_start", "scenario": scenario, "seed": seed, "agent": agent, "tools": list(tools)}
    end = {"event": "episode_end", "outcome": "died" if dead else "timeout", "dead": dead, "tics": tics,
           "score": float(tics), "stop_reason": stop_reason}
    path.write_text("\n".join(json.dumps(e) for e in [start, *events, end]) + "\n")
    return path


# ------------------------------------------------------------ miner


def test_turning_toward_an_enemy_is_not_turning_away():
    from doomlab.review.flags import episode_steps

    def step_for(degrees, tmp):
        return episode_steps(trace(tmp, [observe(1, [DEMON_LEFT]), exe(1, "turn", {"degrees": degrees})]))[0][0]

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        assert not turned_away(step_for(30, Path(d) / "a-s0-react_single.jsonl"))  # enemy 30° left: turning left 30 is aiming
        assert turned_away(step_for(-45, Path(d) / "b-s0-react_single.jsonl"))
        assert turned_away(step_for(90, Path(d) / "c-s0-react_single.jsonl"))  # overshoots far past it


def test_miner_counts_signatures_with_evidence(tmp_path):
    a = trace(tmp_path / "defend_the_center-s0-react_single.jsonl", [
        observe(1, [DEMON_LEFT]), exe(1, "observe", {}),
        observe(2, [DEMON_LEFT]), exe(2, "observe", {}, ok=False, code="NOTHING_CHANGED"),
        observe(3, [DEMON_LEFT]), exe(3, "attack", {"burst": 1}, ok=False, code="NO_ENEMY_IN_CONE"),
        observe(4, [DEMON_LEFT]), exe(4, "turn", {"degrees": -90}),
    ], tics=400, stop_reason="budget")
    b = trace(tmp_path / "health_gathering_supreme-s1-commander.jsonl", [
        observe(1, [MEDIKIT], health=30.0), exe(1, "turn", {"degrees": 90}),
    ], scenario="health_gathering_supreme", seed=1, agent="commander", tools=("observe", "turn", "go_to"), tics=1500)
    report = mine([a, b])
    sig = {s["name"]: s for s in report["signatures"]}
    assert (sig["needless_observe"]["occurrences"], sig["needless_observe"]["episodes"]) == (2, 1)
    assert sig["blind_attack"]["occurrences"] == 1 and sig["turned_from_enemy"]["occurrences"] == 1
    assert sig["medikit_ignored"]["by_variant"] == {"commander": 1}
    assert sig["budget_exhausted"]["episodes"] == 1 and sig["early_death"]["episodes"] == 1
    assert sig["needless_observe"]["examples"][0] == "defend_the_center-s0-react_single.jsonl#1"
    assert report["episodes"] == 2 and report["decisions"] == 5
    assert [s["occurrences"] for s in report["signatures"]] == sorted((s["occurrences"] for s in report["signatures"]), reverse=True)


def test_miner_refuses_test_split_traces(tmp_path):
    with pytest.raises(ValueError, match="test"):
        mine([trace(tmp_path / "basic-s1004-random.jsonl", [], scenario="basic", seed=1004)])


def test_miner_report_is_deterministic(tmp_path):
    a = trace(tmp_path / "defend_the_center-s0-react_single.jsonl", [observe(1, []), exe(1, "observe", {})])
    assert json.dumps(mine([a]), sort_keys=True) == json.dumps(mine([a]), sort_keys=True)


# ------------------------------------------------------------ gate


def ep(seed, score, success=False, calls=50, tokens=50_000, latency=0.6):
    return EpisodeMetrics(
        scenario="health_gathering_supreme", seed=seed, variant="react_single", outcome="success" if success else "died",
        success=success, score_name="survived_tics", score=float(score), stop_reason=None, tics=int(score), kills=0,
        steps=calls, rejected=0, rejected_codes={}, played_out=False, shots=None, wasted_shots=None, recoveries=0,
        recovered=0, llm_calls=calls, tokens=tokens, llm_seconds=calls * latency, latencies=(latency,) * calls)


PARENT = [ep(100, 1000), ep(101, 1200), ep(102, 2100, True), ep(103, 900), ep(104, 1100)]
REG_PARENT = {"rc-001": True, "rc-002": False, "rc-003": False}


def verdict(candidate, reg_candidate, parent=PARENT, rules=GateRules()):
    return decide(rules, REG_PARENT, reg_candidate, parent, candidate)


def test_clear_win_is_promoted():
    candidate = [ep(100, 1400), ep(101, 2100, True), ep(102, 2100, True), ep(103, 1300), ep(104, 1500)]
    result = verdict(candidate, {"rc-001": True, "rc-002": True, "rc-003": False})
    assert result["verdict"] == "promote", result["checks"]


def test_losing_a_case_the_parent_passed_is_rejected():
    candidate = [ep(100, 1400), ep(101, 2100, True), ep(102, 2100, True), ep(103, 1300), ep(104, 1500)]
    result = verdict(candidate, {"rc-001": False, "rc-002": True, "rc-003": True})
    assert result["verdict"] == "reject" and "regression_kept" in result["failed"]


def test_losing_a_seed_the_parent_won_is_rejected():
    candidate = [ep(100, 1400), ep(101, 2100, True), ep(102, 1800), ep(103, 1300), ep(104, 1500)]
    result = verdict(candidate, {"rc-001": True, "rc-002": True, "rc-003": False})
    assert result["verdict"] == "reject" and "no_seed_lost" in result["failed"]


def test_costlier_per_tic_is_rejected_but_living_longer_is_not_penalised():
    longer = [ep(s.seed, s.score * 1.3, s.success, calls=int(s.llm_calls * 1.3)) for s in PARENT]
    assert "calls_per_tic" not in verdict(longer, {"rc-001": True, "rc-002": True, "rc-003": False})["failed"]
    pricier = [ep(s.seed, s.score, s.success, calls=int(s.llm_calls * 1.5)) for s in PARENT]
    result = verdict(pricier, {"rc-001": True, "rc-002": True, "rc-003": False})
    assert result["verdict"] == "reject" and "calls_per_tic" in result["failed"]


def test_small_differences_are_inconclusive():
    candidate = [ep(100, 1020), ep(101, 1180), ep(102, 2100, True), ep(103, 950), ep(104, 1100)]
    assert verdict(candidate, {"rc-001": True, "rc-002": True, "rc-003": False})["verdict"] == "inconclusive"


def test_better_play_without_fixing_a_corrected_mistake_is_not_promoted():
    candidate = [ep(100, 1400), ep(101, 2100, True), ep(102, 2100, True), ep(103, 1300), ep(104, 1500)]
    assert verdict(candidate, dict(REG_PARENT))["verdict"] == "inconclusive"


def test_unknown_tokens_make_it_inconclusive():
    candidate = [ep(s, 2100, True, tokens=None) for s in range(100, 105)]
    result = verdict(candidate, {"rc-001": True, "rc-002": True, "rc-003": True})
    assert result["verdict"] == "inconclusive" and "tokens_per_tic" in result["unknown"]


def test_paired_score_route_promotes_without_new_successes():
    candidate = [ep(100, 1300), ep(101, 1500), ep(102, 2100, True), ep(103, 1150), ep(104, 1400)]
    assert verdict(candidate, {"rc-001": True, "rc-002": True, "rc-003": False})["verdict"] == "promote"


def test_votes_decide_a_regression_pass():
    results = [{"id": "rc-001", "votes": 2, "asked": 3}, {"id": "rc-002", "votes": 1, "asked": 3}]
    assert passed_by_votes(results, GateRules()) == {"rc-001": True, "rc-002": False}


def test_committed_rules_load_with_a_fingerprint():
    rules, fingerprint = load_rules()
    assert rules == GateRules() and len(fingerprint) == 64


def test_the_automatic_play_out_is_not_counted_as_a_decision(tmp_path):
    a = trace(tmp_path / "defend_the_center-s0-react_single.jsonl", [
        observe(1, []), exe(1, "turn", {"degrees": 90}),
        observe(2, []), exe(2, "wait_until_end", {}),
    ], stop_reason="budget")
    assert mine([a])["decisions"] == 1

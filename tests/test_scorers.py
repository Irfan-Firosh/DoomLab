import pytest

from doomlab.eval.scorers import score_trace, summarize, wilson

DEFEND = ["TURN_LEFT", "TURN_RIGHT", "ATTACK"]
SHOT = [[0, 0, 1]] + [[0, 0, 0]] * 13


def start(agent="react_single", scenario="defend_the_center", seed=0, buttons=DEFEND):
    return {"event": "episode_start", "scenario": scenario, "seed": seed, "agent": agent, "buttons": buttons}


def exe(tool, ok=True, code=None, buttons=(), **extra):
    return {"event": "tool_exec", "tool": tool, "ok": ok, "code": code, "buttons": list(buttons), **extra}


def llm(latency=0.5, tokens=100, role=None):
    usage = {"total_tokens": tokens} if tokens is not None else None
    return {"event": "llm_call", "latency_s": latency, "usage": usage, **({"role": role} if role else {})}


def end(outcome="died", score=600.0, kills=1, tics=600, llm_calls=0, tokens=0, stop_reason=None):
    return {"event": "episode_end", "outcome": outcome, "score": score, "kills": kills, "tics": tics,
            "llm_calls": llm_calls, "tokens": tokens, "llm_seconds": 0.0, "stop_reason": stop_reason}


# ------------------------------------------------------------ wilson


@pytest.mark.parametrize(("k", "n", "low", "high"), [(5, 5, 0.566, 1.0), (4, 5, 0.376, 0.964), (0, 5, 0.0, 0.434)])
def test_wilson_95_interval(k, n, low, high):
    lo, hi = wilson(k, n)
    assert (round(lo, 3), round(hi, 3)) == (low, high)


def test_wilson_of_nothing_is_undefined():
    assert wilson(0, 0) == (None, None)


# ------------------------------------------------------------ one episode


def test_shots_and_wasted_shots_come_from_button_presses():
    events = [start(), exe("attack", buttons=SHOT * 5), end(kills=1)]
    m = score_trace(events)
    assert (m.shots, m.wasted_shots) == (5, 4)


def test_no_weapon_means_no_shot_metrics():
    m = score_trace([start(scenario="health_gathering_supreme", buttons=["TURN_LEFT", "TURN_RIGHT", "MOVE_FORWARD"]),
                     exe("turn", buttons=[[1, 0, 0]] * 10), end(kills=0)])
    assert (m.shots, m.wasted_shots) == (None, None)


def test_steps_exclude_the_play_out_and_rejections_are_counted_by_code():
    events = [
        start(),
        exe("attack", ok=False, code="NO_ENEMY_IN_CONE"),
        exe("aim_at"),
        exe("attack", ok=False, code="NO_ENEMY_IN_CONE"),
        exe("observe", ok=False, code="NOTHING_CHANGED"),
        exe("wait_until_end", reason="budget"),
        end(stop_reason="budget"),
    ]
    m = score_trace(events)
    assert (m.steps, m.rejected, m.played_out) == (4, 3, True)
    assert m.rejected_codes == {"NO_ENEMY_IN_CONE": 2, "NOTHING_CHANGED": 1}


def test_recoveries_count_rejection_streaks_and_whether_they_ended_well():
    ok, bad = exe("aim_at"), exe("attack", ok=False, code="NO_ENEMY_IN_CONE")
    m = score_trace([start(), bad, ok, bad, bad, ok, bad, bad, bad, end(stop_reason="recovery_exhausted")])
    assert (m.recoveries, m.recovered) == (3, 2)


def test_llm_cost_and_unknown_tokens_stay_unknown():
    m = score_trace([start(), llm(0.4), llm(0.6), exe("aim_at"), end(llm_calls=2, tokens=None)])
    assert (m.llm_calls, m.tokens, m.latencies) == (2, None, (0.4, 0.6))
    assert m.score_per_llm_call == 300.0


def test_outcome_score_and_score_name():
    m = score_trace([start(agent="scripted", scenario="basic", buttons=["MOVE_LEFT", "MOVE_RIGHT", "ATTACK"]),
                     exe("attack", buttons=SHOT[:1]), end(outcome="success", score=27.0, tics=27)])
    assert (m.variant, m.success, m.score_name, m.score, m.score_per_llm_call) == ("scripted", True, "tics", 27.0, None)


def test_commander_metrics():
    events = [
        start(agent="commander"),
        {"event": "transition", "from": "route", "to": "commander", "why": "no mode yet"},
        llm(role="commander"),
        {"event": "mode", "mode": "fight", "previous": None, "auto": False, "trigger": "no mode yet"},
        {"event": "transition", "from": "route", "to": "plan", "why": "stay in fight mode"},
        {"event": "transition", "from": "route", "to": "plan", "why": "stay in fight mode"},
        {"event": "transition", "from": "route", "to": "commander", "why": "fight mode but no enemy visible"},
        llm(role="commander"),
        {"event": "mode", "mode": "navigate", "previous": "fight", "auto": False, "trigger": "fight mode but no enemy visible"},
        {"event": "transition", "from": "route", "to": "commander", "why": "navigate specialist reported back: x"},
        llm(role="commander"),
        {"event": "mode", "mode": "navigate", "previous": "navigate", "auto": False,
         "trigger": "navigate specialist reported back: x"},
        end(),
    ]
    m = score_trace(events)
    assert (m.commander_calls, m.mode_switches) == (3, 1)
    assert m.triggers == {"start": 1, "no_enemy": 1, "report_back": 1}
    assert m.continue_share == pytest.approx(2 / 5)


def test_single_agents_have_no_commander_metrics():
    m = score_trace([start(), exe("aim_at"), end()])
    assert (m.commander_calls, m.mode_switches, m.triggers, m.continue_share) == (None, None, None, None)


def test_a_trace_without_an_end_is_refused():
    with pytest.raises(ValueError, match="unfinished"):
        score_trace([start(), exe("aim_at")])


# ------------------------------------------------------------ groups


def _episode(variant, seed, outcome, score, **kw):
    return score_trace([start(agent=variant, seed=seed), llm(0.2 * (seed + 1)), exe("aim_at"),
                        end(outcome=outcome, score=score, llm_calls=1, tokens=100, **kw)])


def test_summary_groups_by_scenario_and_variant_with_intervals_and_pairs():
    episodes = [_episode("react_single", s, "success" if s < 4 else "died", 1000.0 + s) for s in range(5)]
    episodes += [_episode("scripted", s, "died", 500.0) for s in range(5)]
    summary = summarize(episodes)
    group = summary["groups"]["defend_the_center"]["react_single"]
    assert (group["n"], group["successes"], group["success_ci95"]) == (5, 4, [0.376, 0.964])
    assert group["score"]["median"] == 1002.0 and group["score"]["name"] == "survived_tics"
    assert group["latency_s"] == {"n": 5, "p50": 0.6, "p95": 0.96}
    assert summary["paired"]["defend_the_center"]["3"] == {"react_single": 1003.0, "scripted": 500.0}


def test_infrastructure_failures_are_reported_but_not_scored():
    episodes = [_episode("react_single", 0, "success", 2100.0), _episode("react_single", 1, "llm_error", 50.0)]
    group = summarize(episodes)["groups"]["defend_the_center"]["react_single"]
    assert (group["n"], group["successes"], group["infra_failures"]) == (1, 1, 1)

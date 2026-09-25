import json

import pytest

from doomlab.config import ConfigError
from doomlab.llm.budget import Budget, BudgetExhausted
from doomlab.llm.preflight import load_frozen_decoding
from doomlab.trace import TraceWriter


def test_budget_counts_calls_and_tokens():
    b = Budget(max_calls=2, max_tokens=150)
    b.check()
    b.record(tokens=100)
    b.check()
    b.record(tokens=100)
    with pytest.raises(BudgetExhausted) as exc:
        b.check()
    assert "calls" in str(exc.value) or "tokens" in str(exc.value)


def test_budget_unknown_tokens_do_not_count_as_zero_spend():
    b = Budget(max_calls=5, max_tokens=10)
    b.record(tokens=None)
    assert b.tokens_known is False
    b.check()  # unknown usage can't trip the token cap; calls still count


def write_preflight(tmp_path, **overrides):
    report = {"ok": True, "model_id": "qwen3.8:27b", "decoding_frozen": {"temperature": 0.0, "max_tokens": 512, "thinking": "off"}}
    report.update(overrides)
    path = tmp_path / "preflight.json"
    path.write_text(json.dumps(report))
    return path


def test_frozen_decoding_loads_from_preflight(tmp_path):
    d = load_frozen_decoding(write_preflight(tmp_path), "qwen3.8:27b")
    assert (d.temperature, d.max_tokens, d.disable_thinking) == (0.0, 512, True)


@pytest.mark.parametrize("overrides", [{"ok": False}, {"model_id": "qwen3.6:27b"}])
def test_frozen_decoding_refuses_failed_or_mismatched_preflight(tmp_path, overrides):
    with pytest.raises(ConfigError):
        load_frozen_decoding(write_preflight(tmp_path, **overrides), "qwen3.8:27b")


def test_frozen_decoding_requires_preflight_file(tmp_path):
    with pytest.raises(ConfigError, match="preflight"):
        load_frozen_decoding(tmp_path / "missing.json", "qwen3.8:27b")


def test_trace_writes_one_json_object_per_line(tmp_path):
    path = tmp_path / "run" / "ep.jsonl"
    with TraceWriter(path) as trace:
        trace.write("episode_start", seed=0, buttons=("MOVE_LEFT", "ATTACK"))
        trace.write("episode_end", outcome="success")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [l["event"] for l in lines] == ["episode_start", "episode_end"]
    assert lines[0]["buttons"] == ["MOVE_LEFT", "ATTACK"] and "t" in lines[0]


def test_budgets_are_sized_per_scenario_and_the_call_cap_binds_first():
    from doomlab.llm.budget import budget_for

    calls = {s: budget_for(s).max_calls for s in ("basic", "defend_the_center", "health_gathering_supreme")}
    assert calls == {"basic": 20, "defend_the_center": 150, "health_gathering_supreme": 80}
    defend = budget_for("defend_the_center")
    assert defend.max_seconds == 675.0 and defend.max_tokens == 225_000
    assert defend.max_seconds / defend.max_calls > 60 / 18  # time cap never binds before the call cap at 18/min

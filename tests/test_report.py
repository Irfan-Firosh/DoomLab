import json
import tarfile
import xml.etree.ElementTree as ET

import pytest
from fakes import FakeSession

from doomlab.agents.random_agent import RandomAgent
from doomlab.agents.scripted import ScriptedAgent
from doomlab.eval.harness import plan, run_jobs
from doomlab.report.build import ReportError, build_report
from doomlab.report.charts import bars_with_intervals, dot_plot, paired_lines, standalone


def fake_session(scenario, seed):
    return FakeSession(target_y=20.0 + seed % 7)


def make_agent(variant, scenario, seed):
    return RandomAgent(seed) if variant == "random" else ScriptedAgent()


async def _traces(folder, seeds, config_hash="h" * 64):
    jobs = plan(seeds, ("basic",), ("random", "scripted"))
    await run_jobs(jobs, folder, make_agent, make_session=fake_session, progress=lambda _: None, config_hash=config_hash)


# ------------------------------------------------------------ charts


def test_charts_are_valid_svg_with_one_mark_per_value():
    svg = dot_plot({"basic": {"random": [27.0, 51.0], "scripted": [27.0, 43.0]}}, title="t", higher_is_better=False)
    root = ET.fromstring(standalone(svg))
    assert root.tag.endswith("svg")
    assert len([c for c in root.iter() if c.tag.endswith("circle")]) == 4
    bars = bars_with_intervals({"basic": {"scripted": (0.8, 0.44, 0.97)}}, title="success")
    assert "0.44" not in bars and "44%" in bars  # interval shown as percentages
    lines = paired_lines({100: (704, 448), 101: (1088, 416)}, labels=("v0", "v1"), title="trial")
    assert lines.count("<line") >= 2


def test_standalone_svg_carries_light_and_dark_styles():
    svg = standalone(dot_plot({"basic": {"random": [1.0]}}, title="t", higher_is_better=True))
    assert "prefers-color-scheme: dark" in svg and "<rect" in svg


# ------------------------------------------------------------ the report


async def test_report_is_built_from_traces_alone(tmp_path):
    await _traces(tmp_path / "test", (1000, 1001, 1002))
    await _traces(tmp_path / "dev", (0, 1))
    out = tmp_path / "results"
    summary = build_report(tmp_path / "test", tmp_path / "dev", out, frozen={"name": "frozen-v0", "hash": "h" * 64},
                           trial=None, corrections=[])
    assert summary["test"]["episodes"] == 6 and summary["dev"]["episodes"] == 4
    assert summary["provenance"]["test_recipe_hashes"] == ["h" * 64] and summary["provenance"]["matches_frozen"]
    metrics = (out / "metrics.md").read_text()
    assert "basic" in metrics and "scripted" in metrics and "3/10" not in metrics  # n is 3 here, and said so
    per_seed = (out / "per_seed.md").read_text()
    assert "basic-s1000-scripted" in per_seed  # every number sits next to its episode id
    assert {p.name for p in (out / "charts").iterdir()} >= {"scores_test.svg", "success_test.svg"}
    with tarfile.open(out / "traces" / "eval-test.tar.gz") as tar:
        assert "basic-s1001-random.jsonl" in {m.name for m in tar.getmembers()}


async def test_report_refuses_test_traces_from_mixed_recipes(tmp_path):
    await _traces(tmp_path / "test", (1000,), config_hash="a" * 64)
    await _traces(tmp_path / "test", (1001,), config_hash="b" * 64)
    with pytest.raises(ReportError, match="recipe"):
        build_report(tmp_path / "test", None, tmp_path / "results", frozen={"name": "frozen-v0", "hash": "a" * 64},
                     trial=None, corrections=[])


async def test_report_is_deterministic(tmp_path):
    await _traces(tmp_path / "test", (1000, 1001))
    kwargs = dict(frozen={"name": "frozen-v0", "hash": "h" * 64}, trial=None, corrections=[])
    build_report(tmp_path / "test", None, tmp_path / "a", **kwargs)
    build_report(tmp_path / "test", None, tmp_path / "b", **kwargs)
    for name in ("metrics.md", "per_seed.md", "charts/scores_test.svg"):
        assert (tmp_path / "a" / name).read_text() == (tmp_path / "b" / name).read_text()
    a, b = (json.loads((tmp_path / d / "summary.json").read_text()) for d in "ab")
    assert a == b


def test_slope_chart_labels_never_overlap():
    import re

    svg = paired_lines({100: (704, 448), 101: (1088, 416), 102: (1438, 736), 103: (992, 2100), 104: (1041, 960)},
                       labels=("v0", "v1"), title="trial")
    ys = sorted(float(y) for y in re.findall(r'<text class="muted small" x="510.0" y="([\d.]+)"', svg))
    assert len(ys) == 5 and all(b - a >= 14.9 for a, b in zip(ys, ys[1:]))

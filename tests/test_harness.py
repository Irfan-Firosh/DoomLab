import csv
import json

from fakes import FakeSession

from doomlab.agents.random_agent import RandomAgent
from doomlab.agents.scripted import ScriptedAgent
from doomlab.eval.harness import BENCHMARK, SPLITS, Job, format_table, plan, run_jobs, score_jobs, write_results


def fake_session(scenario, seed):
    return FakeSession(target_y=20.0 + 10 * seed)  # a different monster position per seed, like the real game


def make_agent(variant, scenario, seed):
    return RandomAgent(seed) if variant == "random" else ScriptedAgent()


def test_splits_and_benchmark_match_the_spec():
    assert SPLITS["dev"] == (0, 1, 2, 3, 4)
    assert SPLITS["validation"] == (100, 101, 102, 103, 104)
    assert SPLITS["test"] == tuple(range(1000, 1010))
    assert BENCHMARK == ("basic", "defend_the_center", "health_gathering_supreme")


def test_plan_plays_free_variants_first_whatever_order_is_asked():
    jobs = plan((0, 1), ("basic",), ("commander", "scripted"))
    assert [j.variant for j in jobs] == ["scripted", "scripted", "commander", "commander"]
    assert jobs[0].trace_name == "basic-s0-scripted.jsonl"


async def test_runs_every_job_then_skips_finished_ones(tmp_path):
    jobs = plan((0, 1, 2), ("basic",), ("random", "scripted"))
    lines = []
    played, skipped = await run_jobs(jobs, tmp_path, make_agent, make_session=fake_session, progress=lines.append)
    assert (played, skipped) == (6, 0) and len(lines) == 6
    played, skipped = await run_jobs(jobs, tmp_path, make_agent, make_session=fake_session, progress=lines.append)
    assert (played, skipped) == (0, 6)
    assert "done earlier" in lines[-1]


async def test_unfinished_or_infrastructure_failed_episodes_are_played_again(tmp_path):
    jobs = plan((0, 1), ("basic",), ("scripted",))
    await run_jobs(jobs, tmp_path, make_agent, make_session=fake_session, progress=lambda _: None)
    crashed = tmp_path / jobs[0].trace_name
    crashed.write_text(crashed.read_text().splitlines()[0] + "\n")  # only episode_start survived a crash
    failed = tmp_path / jobs[1].trace_name
    failed.write_text(failed.read_text().replace('"outcome": "success"', '"outcome": "llm_error"'))
    played, skipped = await run_jobs(jobs, tmp_path, make_agent, make_session=fake_session, progress=lambda _: None)
    assert (played, skipped) == (2, 0)
    assert sum('"episode_start"' in line for line in crashed.read_text().splitlines()) == 1  # replaced, not appended


async def test_results_files_come_from_the_traces(tmp_path):
    jobs = plan((0, 1, 2), ("basic",), ("random", "scripted"))
    await run_jobs(jobs, tmp_path, make_agent, make_session=fake_session, progress=lambda _: None)
    episodes = score_jobs(jobs, tmp_path)
    csv_path, json_path = write_results(tmp_path, episodes, {"split": "dev"})
    rows = list(csv.DictReader(csv_path.open()))
    assert len(rows) == 6 and {r["variant"] for r in rows} == {"random", "scripted"}
    summary = json.loads(json_path.read_text())
    assert summary["meta"]["split"] == "dev"
    scripted = summary["groups"]["basic"]["scripted"]
    assert scripted["n"] == 3 and scripted["successes"] == 3 and scripted["steps"]["median"] == 2.0
    assert set(summary["paired"]["basic"]["0"]) == {"random", "scripted"}


async def test_table_names_the_score_and_shows_every_variant(tmp_path):
    jobs = plan((0, 1), ("basic",), ("random", "scripted"))
    await run_jobs(jobs, tmp_path, make_agent, make_session=fake_session, progress=lambda _: None)
    from doomlab.eval.scorers import summarize

    table = format_table(summarize(score_jobs(jobs, tmp_path)))
    assert "basic" in table and "tics to kill (lower is better)" in table
    assert "random" in table and "scripted" in table and "per seed" in table


def test_missing_traces_are_left_out_of_scoring(tmp_path):
    assert score_jobs([Job("basic", 0, "scripted")], tmp_path) == []

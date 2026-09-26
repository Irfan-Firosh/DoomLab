"""`doomlab eval`: play a scenario x seed x variant matrix, resumably, then score it from the traces alone.

Resuming: an episode counts as done when its trace has an `episode_end` that is not an infrastructure failure
(llm_error). Anything else (a crash mid-episode, a rate-limit failure) is deleted and played again.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doomlab.env.doom import DoomSession
from doomlab.eval.scorers import INFRA_OUTCOMES, EpisodeMetrics, csv_row, score_trace, summarize
from doomlab.freeze import FreezeError
from doomlab.runner import SCORES, arun_episode
from doomlab.tools.executor import Session
from doomlab.trace import TraceWriter
from doomlab.variants import VARIANTS, AgentMaker

SPLITS: dict[str, tuple[int, ...]] = {
    "dev": tuple(range(0, 5)),
    "validation": tuple(range(100, 105)),
    "test": tuple(range(1000, 1010)),  # frozen until the final comparison
}
BENCHMARK = ("basic", "defend_the_center", "health_gathering_supreme")


@dataclass(frozen=True)
class Job:
    scenario: str
    seed: int
    variant: str

    @property
    def trace_name(self) -> str:
        return f"{self.scenario}-s{self.seed}-{self.variant}.jsonl"


def plan(seeds: tuple[int, ...], scenarios: tuple[str, ...], variants: tuple[str, ...]) -> list[Job]:
    """Every combination, free variants first so the cheap part finishes before any LLM spending."""
    ordered = [v for v in VARIANTS if v in variants]
    return [Job(s, seed, v) for v in ordered for s in scenarios for seed in seeds]


def load_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _is_done(path: Path) -> bool:
    if not path.exists():
        return False
    end = next((e for e in load_events(path) if e["event"] == "episode_end"), None)
    return end is not None and end["outcome"] not in INFRA_OUTCOMES


async def run_jobs(
    jobs: list[Job],
    out_dir: Path,
    make_agent: AgentMaker,
    *,
    make_session: Callable[[str, int], Session] = DoomSession,
    progress: Callable[[str], None] = print,
    config_hash: str | None = None,
) -> tuple[int, int]:
    """Play every job that is not done yet. Returns (played, skipped)."""
    played = skipped = 0
    for i, job in enumerate(jobs, start=1):
        label = f"[{i}/{len(jobs)}] {job.scenario:<25} seed {job.seed:<5} {job.variant:<13}"
        path = out_dir / job.trace_name
        if _is_done(path):
            skipped += 1
            progress(f"{label} done earlier")
            continue
        path.unlink(missing_ok=True)  # a partial or failed trace: start clean (traces append)
        session = make_session(job.scenario, job.seed)
        try:
            with TraceWriter(path) as trace:
                agent = make_agent(job.variant, job.scenario, job.seed)
                result = await arun_episode(session, agent, scenario=job.scenario, seed=job.seed, trace=trace,
                                            config_hash=config_hash)
        finally:
            close = getattr(session, "close", None)
            if close:
                close()
        played += 1
        progress(f"{label} {result.outcome:<8} score {result.score:g}  llm calls {result.llm_calls}")
    return played, skipped


def check_folder(out_dir: Path, config_hash: str) -> None:
    """Refuse to add episodes to a folder whose traces came from a different recipe (or from before the freeze)."""
    for path in sorted(out_dir.glob("*.jsonl")):
        first = path.read_text().split("\n", 1)[0]
        found = json.loads(first).get("config_hash") if first.strip() else None
        if found != config_hash:
            raise FreezeError(f"{out_dir} holds traces from another recipe ({path.name}: {found or 'no hash'}); "
                              f"use --out for a new folder")


def score_jobs(jobs: list[Job], out_dir: Path) -> list[EpisodeMetrics]:
    """Metrics for every planned job that has a finished trace (from the trace files only)."""
    episodes = []
    for job in jobs:
        path = out_dir / job.trace_name
        if path.exists():
            events = load_events(path)
            if any(e["event"] == "episode_end" for e in events):
                episodes.append(score_trace(events))
    return episodes


def write_results(out_dir: Path, episodes: list[EpisodeMetrics], meta: dict[str, Any]) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path, json_path = out_dir / "episodes.csv", out_dir / "summary.json"
    rows = [csv_row(m) for m in episodes]
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["scenario"])
        writer.writeheader()
        writer.writerows(rows)
    summary = {"meta": {**meta, "episodes": len(episodes), "written": datetime.now(timezone.utc).isoformat()},
               **summarize(episodes)}
    json_path.write_text(json.dumps(summary, indent=2))
    return csv_path, json_path


# ------------------------------------------------------------------ terminal table

SCORE_TEXT = {"tics": "tics to kill", "survived_tics": "tics survived"}


def format_table(summary: dict[str, Any]) -> str:
    lines = []
    for scenario, groups in summary["groups"].items():
        name, higher = SCORES.get(scenario, ("tics", False))
        lines.append(f"\n{scenario}: score = {SCORE_TEXT.get(name, name)} ({'higher' if higher else 'lower'} is better)")
        lines.append(f"  {'variant':<13}{'n':>3}  {'success':<8}{'95% CI':<12}{'score median [q1-q3]':<23}"
                     f"{'steps':>6}{'rejected':>11}{'wasted shots':>14}{'llm calls':>11}{'tokens':>8}{'latency p50/p95':>17}")
        for variant, g in groups.items():
            lines.append("  " + _row(variant, g))
            if "commander" in g:
                c = g["commander"]
                lines.append(f"  {'':<13}   commander calls {_n(c['commander_calls']['median'])}, "
                             f"mode switches {_n(c['mode_switches']['median'])}, "
                             f"continue share {_pct(c['continue_share']['median'])}, triggers {c['triggers']}")
        lines.append(_paired(summary["paired"].get(scenario, {}), list(groups)))
    return "\n".join(lines)


def _row(variant: str, g: dict[str, Any]) -> str:
    ci = "-" if g["success_ci95"] is None else f"{g['success_ci95'][0]:.2f}-{g['success_ci95'][1]:.2f}"
    s = g["score"]
    score = "-" if s["median"] is None else f"{s['median']:g} [{s['q1']:g}-{s['q3']:g}]"
    rejected = f"{g['rejected']} ({_pct(g['rejection_rate'])})"
    latency = "-" if g["latency_s"]["p50"] is None else f"{g['latency_s']['p50']:.2f}/{g['latency_s']['p95']:.2f}s"
    infra = f"  +{g['infra_failures']} llm_error" if g["infra_failures"] else ""
    return (f"{variant:<13}{g['n']:>3}  {g['successes']}/{g['n']:<6}{ci:<12}{score:<23}{_n(g['steps']['median']):>6}"
            f"{rejected:>11}{_n(g['wasted_shots']['median']):>14}{_n(g['llm_calls']['median']):>11}"
            f"{_n(g['tokens']['median']):>8}{latency:>17}{infra}")


def _paired(seeds: dict[str, dict[str, float]], variants: list[str]) -> str:
    header = f"  {'per seed':<10}" + "".join(f"{v:>14}" for v in variants)
    rows = [f"  {seed:<10}" + "".join(f"{_n(scores.get(v)):>14}" for v in variants) for seed, scores in seeds.items()]
    return "\n".join([header, *rows])


def _n(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.0f}%"

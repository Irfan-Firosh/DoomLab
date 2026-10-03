"""`doomlab report`: rebuild every published number from the trace files, and archive those traces.

Reads the test and dev eval folders (reporting only: nothing here feeds back into tuning), the improvement
trial's gate result and the corrections file. Writes results/: summary.json, episodes_*.csv, metrics.md (the
website block), per_seed.md (every score next to its episode id), charts/*.svg and traces/*.tar.gz. Output is
deterministic: the same traces always give the same files.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import tarfile
from collections import Counter
from pathlib import Path
from typing import Any

from doomlab.eval.harness import BENCHMARK, load_events
from doomlab.eval.scorers import EpisodeMetrics, csv_row, score_trace, summarize
from doomlab.report.charts import bars_with_intervals, dot_plot, paired_lines, standalone
from doomlab.runner import SCORES
from doomlab.variants import LLM_VARIANTS, VARIANTS

SCORE_TEXT = {"tics": "tics to kill", "survived_tics": "tics survived"}


class ReportError(RuntimeError):
    """The traces cannot support a single consistent report (e.g. mixed recipes)."""


def build_report(test_dir: Path, dev_dir: Path | None, out: Path, *, frozen: dict[str, Any] | None,
                 trial: dict[str, Any] | None, corrections: list[dict[str, Any]]) -> dict[str, Any]:
    test = _load(test_dir)
    dev = _load(dev_dir) if dev_dir else None
    hashes = sorted({e["hash"] or "none" for e in test})
    if len(hashes) > 1:
        raise ReportError(f"test traces come from more than one recipe {[h[:12] for h in hashes]}; report one recipe")
    summary = {
        "test": _split_summary(test),
        "dev": _split_summary(dev) if dev else None,
        "trial": _trial_summary(trial) if trial else None,
        "corrections": _corrections(corrections),
        "provenance": {
            "test_recipe_hashes": hashes,
            "frozen": {"name": frozen["name"], "hash": frozen["hash"]} if frozen else None,
            "matches_frozen": bool(frozen) and hashes == [frozen["hash"]],
            "traces": {"test": "traces/eval-test.tar.gz", **({"dev": "traces/eval-dev.tar.gz"} if dev else {})},
        },
    }
    (out / "charts").mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    _write_csv(out / "episodes_test.csv", test)
    _archive(test_dir, out / "traces" / "eval-test.tar.gz")
    if dev:
        _write_csv(out / "episodes_dev.csv", dev)
        _archive(dev_dir, out / "traces" / "eval-dev.tar.gz")
    _write_charts(out / "charts", test, summary, trial)
    (out / "metrics.md").write_text(_metrics_md(summary, test))
    (out / "per_seed.md").write_text(_per_seed_md(test, "test"))
    return summary


# ------------------------------------------------------------------ loading


def _load(folder: Path) -> list[dict[str, Any]]:
    episodes = []
    for path in sorted(folder.glob("*.jsonl")):
        events = load_events(path)
        if not any(e["event"] == "episode_end" for e in events):
            continue  # an unfinished episode is never scored
        start = events[0]
        decisions = [e for e in events if e["event"] == "tool_exec" and e["tool"] != "wait_until_end"]
        episodes.append({"id": path.stem, "metrics": score_trace(events), "hash": start.get("config_hash"),
                         "observe": sum(e["tool"] == "observe" for e in decisions), "decisions": len(decisions)})
    return episodes


def _metrics(episodes: list[dict[str, Any]]) -> list[EpisodeMetrics]:
    return [e["metrics"] for e in episodes]


def _split_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = _metrics(episodes)
    observe: dict[str, dict[str, int]] = {}
    for e in episodes:
        v = observe.setdefault(e["metrics"].variant, {"observe": 0, "decisions": 0})
        v["observe"] += e["observe"]
        v["decisions"] += e["decisions"]
    return {
        "episodes": len(episodes),
        "seeds": sorted({m.seed for m in metrics}),
        **summarize(metrics),
        "needless_observe": {v: {**c, "share": round(c["observe"] / c["decisions"], 3) if c["decisions"] else None}
                             for v, c in sorted(observe.items()) if v in LLM_VARIANTS},
    }


def _trial_summary(trial: dict[str, Any]) -> dict[str, Any]:
    parent, candidate = trial["parent"]["policy"], trial["candidate"]["policy"]
    pairs = list(zip(trial["ab"][parent], trial["ab"][candidate]))
    return {
        "scenario": trial["scenario"], "variant": trial["variant"], "seeds": trial["seeds"],
        "parent": parent, "candidate": candidate, "lessons": trial["candidate"]["lessons"],
        "regression_passed": trial["regression"]["passed"], "cases": trial["corrections"]["total"],
        "ab": [{"seed": a["seed"], parent: a["score"], candidate: b["score"]} for a, b in pairs],
        "worse_seeds": sum(b["score"] < a["score"] for a, b in pairs),
        "gate_verdict": trial["verdict"],
        "human_decision": (trial.get("human_decision") or {}).get("decision"),
        "human_note": (trial.get("human_decision") or {}).get("note"),
    }


def _corrections(cases: list[dict[str, Any]]) -> dict[str, int]:
    human = sum(c.get("author", "human") == "human" for c in cases)
    reviewed = sum(c.get("approved_by_human", c.get("author", "human") == "human") for c in cases)
    return {"total": len(cases), "human": human, "assistant_drafted": len(cases) - human, "reviewed_by_human": reviewed}


# ------------------------------------------------------------------ files


def _write_csv(path: Path, episodes: list[dict[str, Any]]) -> None:
    rows = [{"episode_id": e["id"], **csv_row(e["metrics"]), "observe_calls": e["observe"]} for e in episodes]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["episode_id"])
        writer.writeheader()
        writer.writerows(rows)


def _archive(folder: Path, target: Path) -> None:
    """A byte-for-byte reproducible .tar.gz of the traces (fixed timestamps and owners)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for path in sorted(folder.glob("*.jsonl")):
            data = path.read_bytes()
            info = tarfile.TarInfo(path.name)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tar.addfile(info, io.BytesIO(data))
    with target.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        gz.write(buffer.getvalue())


def _variants_in(groups: dict[str, Any]) -> list[str]:
    return [v for v in VARIANTS if v in groups]


def _scenarios(groups: dict[str, Any]) -> list[str]:
    return [s for s in BENCHMARK if s in groups] + sorted(s for s in groups if s not in BENCHMARK)


def _write_charts(folder: Path, test: list[dict[str, Any]], summary: dict[str, Any], trial: dict[str, Any] | None) -> None:
    groups = summary["test"]["groups"]
    scores = {s: {v: [e["metrics"].score for e in test if (e["metrics"].scenario, e["metrics"].variant) == (s, v)]
                  for v in _variants_in(groups[s])} for s in _scenarios(groups)}
    n = len(summary["test"]["seeds"])
    higher = {s: SCORES.get(s, ("tics", False))[1] for s in scores}
    units = {s: SCORE_TEXT.get(SCORES.get(s, ("tics", False))[0], "tics") for s in scores}
    (folder / "scores_test.svg").write_text(standalone(dot_plot(
        scores, title=f"Test split: score per seed ({n} unseen seeds), tick = median", higher_is_better=higher,
        unit=units)))
    success = {s: {v: (g["successes"] / g["n"], *g["success_ci95"]) for v, g in groups[s].items() if g["n"]}
               for s in _scenarios(groups)}
    (folder / "success_test.svg").write_text(standalone(bars_with_intervals(
        {s: {v: success[s][v] for v in _variants_in(success[s])} for s in success},
        title=f"Test split: success rate with 95% interval (n = {n} per bar)")))
    if trial:
        t = summary["trial"]
        pairs = {row["seed"]: (row[t["parent"]], row[t["candidate"]]) for row in t["ab"]}
        (folder / f"trial_{t['candidate']}.svg").write_text(standalone(paired_lines(
            pairs, labels=(f"{t['parent']} (no lessons)", f"{t['candidate']} (3 lessons)"),
            title=f"Improvement trial: {t['variant']} on {t['scenario']}, validation seeds")))


# ------------------------------------------------------------------ markdown


def _n(value: float | None) -> str:
    """Whole numbers without decimals; anything else (a median of 1,330.5) keeps one."""
    if value is None:
        return "–"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"


def _metrics_md(summary: dict[str, Any], test: list[dict[str, Any]]) -> str:
    t = summary["test"]
    groups = t["groups"]
    prov = summary["provenance"]
    recipe = (f"recipe `{prov['frozen']['name']}` (`{prov['frozen']['hash'][:12]}`)" if prov["frozen"] else "recipe unknown")
    seeds = t["seeds"]
    lines = [
        "# DoomLab metrics",
        "",
        f"Generated by `doomlab report` from {t['episodes']} test-split episode traces "
        f"(seeds {seeds[0]}–{seeds[-1]}, never used for tuning), {recipe}. "
        f"Every number below can be recomputed from `traces/eval-test.tar.gz`; `per_seed.md` lists each score with its episode id.",
        "",
        "## Headline: median score (successes / episodes)",
        "",
    ]
    variants = [v for v in VARIANTS if any(v in groups[s] for s in groups)]
    lines += ["| Scenario | Score | " + " | ".join(variants) + " |", "|---|---|" + "---|" * len(variants)]
    for s in _scenarios(groups):
        name, higher = SCORES.get(s, ("tics", False))
        cells = []
        for v in variants:
            g = groups[s].get(v)
            cells.append("–" if not g else f"{_n(g['score']['median'])} ({g['successes']}/{g['n']})")
        lines.append(f"| {s} | {SCORE_TEXT.get(name, name)}, {'higher' if higher else 'lower'} is better | " + " | ".join(cells) + " |")
    lines += ["", "## Success rate with 95% interval (Wilson)", "",
              "| Scenario | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    for s in _scenarios(groups):
        cells = []
        for v in variants:
            g = groups[s].get(v)
            ci = g and g["success_ci95"]
            cells.append("–" if not ci else f"{g['successes']}/{g['n']} ({ci[0]:.0%}–{ci[1]:.0%})")
        lines.append(f"| {s} | " + " | ".join(cells) + " |")
    lines += ["", "## LLM agents: validity, waste and cost (all test scenarios)", "",
              "| Agent | Decisions | Rejected calls | Needless `observe` | Blind attacks | Wasted shots | LLM calls / ep (median) | Tokens / ep (median) | Latency p50 / p95 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for v in [v for v in variants if v in LLM_VARIANTS]:
        eps = [e["metrics"] for e in test if e["metrics"].variant == v]
        decisions = sum(m.steps for m in eps)
        rejected = sum(m.rejected for m in eps)
        codes = Counter()
        for m in eps:
            codes.update(m.rejected_codes)
        top = ", ".join(f"{c} {k}" for c, k in codes.most_common(2))
        obs = t["needless_observe"].get(v, {})
        wasted = sum(m.wasted_shots or 0 for m in eps)
        shots = sum(m.shots or 0 for m in eps)
        calls = sorted(m.llm_calls for m in eps)
        tokens = sorted(m.tokens for m in eps if m.tokens is not None)
        lat = sorted(x for m in eps for x in m.latencies)
        lines.append(
            f"| {v} | {decisions:,} | {rejected} ({rejected / decisions:.1%}): {top} | "
            f"{obs.get('observe', 0)} ({obs.get('share') or 0:.1%}) | {codes.get('NO_ENEMY_IN_CONE', 0)} | "
            f"{wasted} of {shots} shots | {_median(calls):,.0f} | {_median(tokens):,.0f} | "
            f"{_pct(lat, 50):.2f} s / {_pct(lat, 95):.2f} s |")
    if summary["trial"]:
        tr, c = summary["trial"], summary["corrections"]
        lines += ["", "## Improvement trial", "",
                  f"- **Corrections:** {c['total']} regression cases. {_authorship(c)}",
                  f"- **Candidate {tr['candidate']}:** {len(tr['lessons'])} lessons proposed by an Analyst LLM from mined failure patterns.",
                  f"- **Offline:** correction cases passed {tr['regression_passed'][tr['parent']]}/{tr['cases']} ({tr['parent']}) → "
                  f"{tr['regression_passed'][tr['candidate']]}/{tr['cases']} ({tr['candidate']}).",
                  f"- **In play** ({tr['variant']}, {tr['scenario']}, validation seeds): {tr['candidate']} survived shorter on "
                  f"{tr['worse_seeds']} of {len(tr['ab'])} seeds.",
                  f"- **Gate:** {tr['gate_verdict'].upper()}. **Human decision:** {(tr['human_decision'] or 'pending').upper()}"
                  + (f": \"{tr['human_note']}\"" if tr["human_note"] else "")]
    lines += ["", "## Findings", "",
              "- [One LLM call in five was spent looking at a paused game](../findings/2026-09-27-needless-observe.md)",
              "- [The lesson fixed the metric, not the game](../findings/2026-09-27-fixed-the-metric-not-the-game.md)",
              "", "## Provenance", "",
              f"- Test traces carry recipe hash(es): {', '.join(f'`{h[:12]}`' for h in prov['test_recipe_hashes'])}"
              f" ({'matches' if prov['matches_frozen'] else 'does NOT match'} the frozen recipe).",
              "- Reproduce: `uv run doomlab eval --split test` (needs the frozen recipe and a Purdue key), then `uv run doomlab report`.",
              ""]
    return "\n".join(lines)


def _authorship(c: dict[str, int]) -> str:
    if c["reviewed_by_human"] == c["total"]:
        return (f"I reviewed all {c['total']} corrections: I wrote {c['human']}, and AI drafted the other "
                f"{c['assistant_drafted']} from the ViZDoom scenario docs.")
    return (f"I wrote {c['human']} and reviewed {c['reviewed_by_human']} of {c['total']}. AI drafted "
            f"{c['assistant_drafted']} from the ViZDoom scenario docs.")


def _per_seed_md(episodes: list[dict[str, Any]], split: str) -> str:
    lines = [f"# Per-seed results ({split} split)", "",
             f"Each row is one episode; its id names the trace inside `traces/eval-{split}.tar.gz`.", ""]
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for e in episodes:
        by_scenario.setdefault(e["metrics"].scenario, []).append(e)
    for s in [s for s in BENCHMARK if s in by_scenario] + sorted(set(by_scenario) - set(BENCHMARK)):
        name, _ = SCORES.get(s, ("tics", False))
        lines += [f"## {s} ({SCORE_TEXT.get(name, name)})", "",
                  "| Seed | Agent | Outcome | Score | LLM calls | Rejected | Episode id |", "|---|---|---|---|---|---|---|"]
        rows = sorted(by_scenario[s], key=lambda e: (e["metrics"].seed, VARIANTS.index(e["metrics"].variant)
                                                     if e["metrics"].variant in VARIANTS else 99))
        for e in rows:
            m = e["metrics"]
            lines.append(f"| {m.seed} | {m.variant} | {m.outcome} | {_n(m.score)} | {m.llm_calls} | {m.rejected} | `{e['id']}` |")
        lines.append("")
    return "\n".join(lines)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    import numpy as np

    return float(np.percentile(values, q))

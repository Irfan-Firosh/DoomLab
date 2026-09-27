"""The promotion gate: may a candidate policy (v1) replace its parent (v0)? Rules are frozen before v1 exists.

Guards (any failure -> REJECT, any unknown -> INCONCLUSIVE):
  regression_kept   v1 passes every correction case v0 passes
  no_seed_lost      no validation seed v0 won is lost by v1
  calls_per_tic     LLM calls per tic survived <= 110% of v0  (per tic: living longer must not count as cost)
  tokens_per_tic    tokens per tic <= 125% of v0              (unknown usage -> inconclusive)
  latency_p50       median call latency <= 125% of v0
Improvement (all guards pass, then both needed -> PROMOTE, else INCONCLUSIVE):
  regression_gain   v1 passes at least 1 more correction case than v0
  better_play       >= 1 more success, or >= 15% fewer calls on common successes,
                    or higher score on >= 4 of 5 paired seeds with a median gain >= 10%
Regression cases are asked `regression_repeats` times; a case passes with `regression_votes_to_pass` votes,
because the hosted model is not fully repeatable even at temperature 0.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from statistics import median
from typing import Any

from doomlab.config import REPO_ROOT
from doomlab.eval.scorers import EpisodeMetrics
from doomlab.freeze import fingerprint

RULES_PATH = REPO_ROOT / "improve" / "gate_rules.json"
GUARDS = ("regression_kept", "no_seed_lost", "calls_per_tic", "tokens_per_tic", "latency_p50")


@dataclass(frozen=True)
class GateRules:
    regression_repeats: int = 3
    regression_votes_to_pass: int = 2
    min_extra_regression_passes: int = 1
    min_extra_successes: int = 1
    min_call_reduction: float = 0.15
    min_paired_wins: int = 4
    min_median_gain: float = 0.10
    max_calls_per_tic_ratio: float = 1.10
    max_tokens_per_tic_ratio: float = 1.25
    max_latency_p50_ratio: float = 1.25


def load_rules(path: Path = RULES_PATH) -> tuple[GateRules, str]:
    data = json.loads(path.read_text())
    rules = GateRules(**{f.name: data["rules"][f.name] for f in fields(GateRules)})
    return rules, fingerprint(asdict(rules))


def passed_by_votes(results: list[dict[str, Any]], rules: GateRules) -> dict[str, bool]:
    return {r["id"]: r["votes"] >= rules.regression_votes_to_pass for r in results}


def decide(rules: GateRules, reg_parent: dict[str, bool], reg_candidate: dict[str, bool],
           ab_parent: list[EpisodeMetrics], ab_candidate: list[EpisodeMetrics]) -> dict[str, Any]:
    parent = {m.seed: m for m in ab_parent}
    candidate = {m.seed: m for m in ab_candidate}
    seeds = sorted(set(parent) & set(candidate))
    checks = [
        _regression_kept(reg_parent, reg_candidate),
        _no_seed_lost(parent, candidate, seeds),
        _ratio("calls_per_tic", _per_tic(ab_candidate, "llm_calls"), _per_tic(ab_parent, "llm_calls"),
               rules.max_calls_per_tic_ratio),
        _ratio("tokens_per_tic", _per_tic(ab_candidate, "tokens"), _per_tic(ab_parent, "tokens"),
               rules.max_tokens_per_tic_ratio),
        _ratio("latency_p50", _latency(ab_candidate), _latency(ab_parent), rules.max_latency_p50_ratio),
        _regression_gain(reg_parent, reg_candidate, rules),
        _better_play(parent, candidate, seeds, rules),
    ]
    failed = [c["name"] for c in checks if c["passed"] is False]
    unknown = [c["name"] for c in checks if c["passed"] is None]
    if any(name in GUARDS for name in failed):
        verdict = "reject"
    elif unknown or failed:
        verdict = "inconclusive"
    else:
        verdict = "promote"
    return {"verdict": verdict, "checks": checks, "failed": failed, "unknown": unknown, "seeds": seeds,
            "rules": asdict(rules)}


def _check(name: str, passed: bool | None, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}


def _regression_kept(parent: dict[str, bool], candidate: dict[str, bool]) -> dict[str, Any]:
    lost = sorted(case for case, ok in parent.items() if ok and not candidate.get(case, False))
    return _check("regression_kept", not lost, f"cases v0 passed but v1 failed: {lost or 'none'}")


def _regression_gain(parent: dict[str, bool], candidate: dict[str, bool], rules: GateRules) -> dict[str, Any]:
    before, after = sum(parent.values()), sum(candidate.values())
    return _check("regression_gain", after - before >= rules.min_extra_regression_passes,
                  f"correction cases passed: v0 {before}/{len(parent)}, v1 {after}/{len(candidate)}")


def _no_seed_lost(parent: dict[int, EpisodeMetrics], candidate: dict[int, EpisodeMetrics], seeds: list[int]) -> dict[str, Any]:
    lost = [s for s in seeds if parent[s].success and not candidate[s].success]
    return _check("no_seed_lost", not lost, f"seeds v0 won and v1 lost: {lost or 'none'}")


def _better_play(parent: dict[int, EpisodeMetrics], candidate: dict[int, EpisodeMetrics], seeds: list[int],
                 rules: GateRules) -> dict[str, Any]:
    extra = sum(candidate[s].success for s in seeds) - sum(parent[s].success for s in seeds)
    common = [s for s in seeds if parent[s].success and candidate[s].success]
    parent_calls = sum(parent[s].llm_calls for s in common)
    reduction = 1 - sum(candidate[s].llm_calls for s in common) / parent_calls if parent_calls else 0.0
    wins = sum(candidate[s].score > parent[s].score for s in seeds)
    gains = [(candidate[s].score - parent[s].score) / parent[s].score for s in seeds if parent[s].score]
    gain = median(gains) if gains else 0.0
    routes = {
        "more successes": extra >= rules.min_extra_successes,
        "fewer calls": bool(common) and reduction >= rules.min_call_reduction,
        "paired scores": wins >= rules.min_paired_wins and gain >= rules.min_median_gain,
    }
    met = [name for name, ok in routes.items() if ok]
    detail = (f"successes {extra:+d}; calls on common successes {-reduction:+.0%}; "
              f"higher score on {wins}/{len(seeds)} seeds, median gain {gain:+.0%}; met: {met or 'none'}")
    return _check("better_play", bool(met), detail)


def _ratio(name: str, candidate: float | None, parent: float | None, limit: float) -> dict[str, Any]:
    if candidate is None or parent is None or parent == 0:
        return _check(name, None, "not measurable (missing usage or zero baseline)")
    ratio = candidate / parent
    return _check(name, ratio <= limit, f"v1/v0 = {ratio:.2f} (limit {limit:.2f})")


def _per_tic(episodes: list[EpisodeMetrics], field: str) -> float | None:
    values = [getattr(m, field) for m in episodes]
    tics = sum(m.tics for m in episodes)
    if any(v is None for v in values) or not tics:
        return None
    return sum(values) / tics


def _latency(episodes: list[EpisodeMetrics]) -> float | None:
    values = [x for m in episodes for x in m.latencies]
    return median(values) if values else None

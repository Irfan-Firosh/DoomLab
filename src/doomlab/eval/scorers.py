"""Deterministic metrics computed from trace events only, so every number can be re-checked from the files.

One episode -> `EpisodeMetrics` (`score_trace`). Many episodes -> per scenario x variant groups plus a
per-seed paired table (`summarize`). Unknown values stay None, never 0 (e.g. tokens the endpoint did not report).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Any

import numpy as np

from doomlab.runner import SCORES

PLAY_OUT_TOOL = "wait_until_end"
INFRA_OUTCOMES = frozenset({"llm_error"})  # the endpoint failed, not the agent: reported, never scored
Z95 = 1.959964
TRIGGERS = (  # commander trigger text -> short key
    ("no mode yet", "start"),
    ("reported back", "report_back"),
    ("no enemy visible", "no_enemy"),
    ("out of ammo", "no_ammo"),
    ("enemy appeared", "enemy_appeared"),
)


@dataclass(frozen=True)
class EpisodeMetrics:
    scenario: str
    seed: int
    variant: str
    outcome: str
    success: bool
    score_name: str
    score: float
    stop_reason: str | None
    tics: int
    kills: int
    steps: int  # the agent's own tool calls (the automatic play-out is not a decision)
    rejected: int
    rejected_codes: dict[str, int]
    played_out: bool  # the agent stopped early and the rest was played standing still
    shots: int | None  # None when the scenario has no weapon
    wasted_shots: int | None  # shots that killed nothing: one hit usually kills
    recoveries: int  # rejection streaks
    recovered: int  # ... that ended in an accepted call
    llm_calls: int
    tokens: int | None
    llm_seconds: float
    commander_calls: int | None = None
    mode_switches: int | None = None
    triggers: dict[str, int] | None = None
    continue_share: float | None = None  # share of specialist turns that skipped the commander
    latencies: tuple[float, ...] = field(default=(), repr=False)

    @property
    def infra_failure(self) -> bool:
        return self.outcome in INFRA_OUTCOMES

    @property
    def score_per_llm_call(self) -> float | None:
        return self.score / self.llm_calls if self.llm_calls else None


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float | None, float | None]:
    """Wilson score interval: honest bounds on a success rate from few trials."""
    if n == 0:
        return None, None
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


# ------------------------------------------------------------------ one episode


def score_trace(events: list[dict[str, Any]]) -> EpisodeMetrics:
    start = next(e for e in events if e["event"] == "episode_start")
    end = next((e for e in events if e["event"] == "episode_end"), None)
    if end is None:
        raise ValueError(f"unfinished trace: {start['scenario']} seed {start['seed']} {start['agent']}")
    execs = [e for e in events if e["event"] == "tool_exec"]
    decisions = [e for e in execs if e["tool"] != PLAY_OUT_TOOL]
    rejected = [e for e in decisions if not e["ok"]]
    shots = _shots(start["buttons"], execs)
    kills = int(end["kills"])
    recoveries, recovered = _recoveries(decisions)
    return EpisodeMetrics(
        scenario=start["scenario"], seed=start["seed"], variant=start["agent"],
        outcome=end["outcome"], success=end["outcome"] == "success",
        score_name=SCORES.get(start["scenario"], ("tics", False))[0], score=float(end["score"]),
        stop_reason=end.get("stop_reason"), tics=int(end["tics"]), kills=kills,
        steps=len(decisions), rejected=len(rejected), rejected_codes=dict(Counter(e["code"] for e in rejected)),
        played_out=len(execs) > len(decisions),
        shots=shots, wasted_shots=None if shots is None else max(shots - kills, 0),
        recoveries=recoveries, recovered=recovered,
        llm_calls=int(end["llm_calls"]), tokens=end["tokens"], llm_seconds=float(end.get("llm_seconds", 0.0)),
        latencies=tuple(e["latency_s"] for e in events if e["event"] == "llm_call"),
        **_commander_metrics(events),
    )


def _shots(buttons: list[str], execs: list[dict[str, Any]]) -> int | None:
    if "ATTACK" not in buttons:
        return None
    index = buttons.index("ATTACK")
    return sum(tic[index] for e in execs for tic in e["buttons"])


def _recoveries(decisions: list[dict[str, Any]]) -> tuple[int, int]:
    streaks = recovered = 0
    in_streak = False
    for e in decisions:
        if not e["ok"] and not in_streak:
            streaks, in_streak = streaks + 1, True
        elif e["ok"] and in_streak:
            recovered, in_streak = recovered + 1, False
    return streaks, recovered


def _commander_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    modes = [e for e in events if e["event"] == "mode"]
    if not modes:
        return {}
    routed = [e["to"] for e in events if e["event"] == "transition" and e["from"] == "route"]
    continues, commands = routed.count("plan"), routed.count("commander")
    triggers = Counter(_trigger_key(e["trigger"]) for e in modes if not e.get("auto"))
    return {
        "commander_calls": sum(1 for e in events if e["event"] == "llm_call" and e.get("role") == "commander"),
        "mode_switches": sum(1 for e in modes if e["previous"] is not None and e["mode"] != e["previous"]),
        "triggers": dict(triggers),
        "continue_share": continues / (continues + commands) if continues + commands else None,
    }


def _trigger_key(text: str) -> str:
    return next((key for fragment, key in TRIGGERS if fragment in text), "other")


# ------------------------------------------------------------------ many episodes


def summarize(episodes: list[EpisodeMetrics]) -> dict[str, Any]:
    """Groups per scenario x variant, and each scenario's scores seed by seed across variants."""
    groups: dict[str, dict[str, Any]] = {}
    for scenario, variant in sorted({(m.scenario, m.variant) for m in episodes}):
        members = [m for m in episodes if (m.scenario, m.variant) == (scenario, variant)]
        groups.setdefault(scenario, {})[variant] = _group(members)
    paired: dict[str, dict[str, dict[str, float]]] = {}
    for m in sorted(episodes, key=lambda m: (m.scenario, m.seed, m.variant)):
        if not m.infra_failure:
            paired.setdefault(m.scenario, {}).setdefault(str(m.seed), {})[m.variant] = m.score
    return {"groups": groups, "paired": paired}


def _group(members: list[EpisodeMetrics]) -> dict[str, Any]:
    scored = [m for m in members if not m.infra_failure]
    n, successes = len(scored), sum(m.success for m in scored)
    low, high = wilson(successes, n)
    steps = sum(m.steps for m in scored)
    latencies = [x for m in scored for x in m.latencies]
    tokens = [m.tokens for m in scored]
    group: dict[str, Any] = {
        "n": n,
        "infra_failures": len(members) - n,
        "successes": successes,
        "success_ci95": None if low is None else [round(low, 3), round(high, 3)],
        "score": {"name": scored[0].score_name if scored else None, **_spread([m.score for m in scored])},
        "kills": _spread([m.kills for m in scored]),
        "steps": _spread([m.steps for m in scored]),
        "rejected": sum(m.rejected for m in scored),
        "rejection_rate": round(sum(m.rejected for m in scored) / steps, 3) if steps else None,
        "rejected_codes": dict(sum((Counter(m.rejected_codes) for m in scored), Counter())),
        "wasted_shots": _spread([m.wasted_shots for m in scored if m.wasted_shots is not None]),
        "recoveries": sum(m.recoveries for m in scored),
        "recovered": sum(m.recovered for m in scored),
        "stop_reasons": dict(Counter(m.stop_reason or "-" for m in scored)),
        "llm_calls": _spread([m.llm_calls for m in scored]),
        "tokens": _spread([t for t in tokens if t is not None]) | {"unknown": tokens.count(None)},
        "latency_s": {"n": len(latencies), "p50": _pct(latencies, 50), "p95": _pct(latencies, 95)},
        "score_per_llm_call": _spread([m.score_per_llm_call for m in scored if m.score_per_llm_call is not None]),
    }
    team = [m for m in scored if m.commander_calls is not None]
    if team:
        group["commander"] = {
            "commander_calls": _spread([m.commander_calls for m in team]),
            "mode_switches": _spread([m.mode_switches for m in team]),
            "triggers": dict(sum((Counter(m.triggers) for m in team), Counter())),
            "continue_share": _spread([m.continue_share for m in team if m.continue_share is not None]),
        }
    return group


def _spread(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "q1": None, "q3": None, "min": None, "max": None}
    q1, q3 = np.percentile(values, [25, 75])
    return {"median": float(median(values)), "q1": float(q1), "q3": float(q3),
            "min": float(min(values)), "max": float(max(values))}


def _pct(values: list[float], q: float) -> float | None:
    return round(float(np.percentile(values, q)), 3) if values else None


def csv_row(m: EpisodeMetrics) -> dict[str, Any]:
    """One flat CSV row: dict fields as `key:count;...`, raw latencies left to summary.json."""
    row = {k: v for k, v in asdict(m).items() if k != "latencies"}
    for key in ("rejected_codes", "triggers"):
        row[key] = "" if row[key] is None else ";".join(f"{k}:{v}" for k, v in sorted(row[key].items()))
    row["score_per_llm_call"] = m.score_per_llm_call
    return row

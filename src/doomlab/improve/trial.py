"""One improvement trial: regression + paired A/B of parent vs candidate policy, then the gate, then a human.

A/B episodes alternate policies seed by seed (v0 s100, v1 s100, v0 s101, ...), so a slow or drifting endpoint
affects both policies alike. Each policy's traces go in their own folder with that policy's recipe hash.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doomlab.agents.base import Agent
from doomlab.env.doom import DoomSession
from doomlab.eval.harness import Job, check_folder, run_jobs, score_jobs
from doomlab.freeze import fingerprint, recipe
from doomlab.improve.gate import GateRules, decide, passed_by_votes
from doomlab.policy import Policy
from doomlab.policy_registry import ACTIVE
from doomlab.tools.executor import Session

PolicyAgentMaker = Callable[[Policy, str, str, int], Agent]  # (policy, variant, scenario, seed)


async def run_trial(
    *,
    parent: Policy,
    candidate: Policy,
    scenario: str,
    variant: str,
    seeds: tuple[int, ...],
    rules: GateRules,
    rules_fingerprint: str,
    corrections: list[dict[str, Any]],
    out_dir: Path,
    make_agent: PolicyAgentMaker,
    regress: Callable[[Policy], Awaitable[list[dict[str, Any]]]],
    decoding: dict[str, Any] | None,
    traces_dir: Path | None = None,
    make_session: Callable[[str, int], Session] = DoomSession,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    traces = traces_dir or out_dir / "ab"
    hashes = {p.version: fingerprint(recipe(decoding, p)) for p in (parent, candidate)}

    progress(f"regression: {len(corrections)} cases, {rules.regression_repeats} asks each, for {parent.version} and {candidate.version}")
    regression = {p.version: await regress(p) for p in (parent, candidate)}
    passed = {v: passed_by_votes(r, rules) for v, r in regression.items()}
    progress(f"  passed: {parent.version} {sum(passed[parent.version].values())}/{len(corrections)}, "
             f"{candidate.version} {sum(passed[candidate.version].values())}/{len(corrections)}")

    for policy in (parent, candidate):
        folder = traces / policy.version
        if folder.exists():
            check_folder(folder, hashes[policy.version])
    for seed in seeds:
        for policy in (parent, candidate):
            job = Job(scenario, seed, variant)
            await run_jobs([job], traces / policy.version,
                           lambda v, s, sd, policy=policy: make_agent(policy, v, s, sd), make_session=make_session,
                           progress=lambda line, policy=policy: progress(f"  A/B {policy.version}: {line.split('] ', 1)[-1]}"),
                           config_hash=hashes[policy.version])
    jobs = [Job(scenario, seed, variant) for seed in seeds]
    ab = {p.version: score_jobs(jobs, traces / p.version) for p in (parent, candidate)}

    gate = decide(rules, passed[parent.version], passed[candidate.version], ab[parent.version], ab[candidate.version])
    result = {
        "trial": candidate.version,
        "scenario": scenario, "variant": variant, "seeds": list(seeds),
        "parent": {"policy": parent.version, "lessons": list(parent.lessons), "recipe_hash": hashes[parent.version]},
        "candidate": {"policy": candidate.version, "file": f"{candidate.version}.json", "lessons": list(candidate.lessons),
                      "recipe_hash": hashes[candidate.version]},
        "gate_rules_fingerprint": rules_fingerprint,
        "corrections": _corrections_summary(corrections),
        "regression": {"passed": {v: sum(p.values()) for v, p in passed.items()}, "cases": regression},
        "ab": {v: [{"seed": m.seed, "outcome": m.outcome, "score": m.score, "llm_calls": m.llm_calls, "tokens": m.tokens,
                    "rejected": m.rejected}
                   for m in episodes] for v, episodes in ab.items()},
        **{k: gate[k] for k in ("verdict", "checks", "failed", "unknown")},
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "human_decision": None,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gate_result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def record_decision(gate_path: Path, decision: str, *, note: str, active: Path = ACTIVE, override: bool = False) -> dict[str, Any]:
    """Your call. Approving points new runs at the candidate; approving against the gate needs `override`."""
    if decision not in ("approve", "reject"):
        raise ValueError("decision must be approve or reject")
    result = json.loads(gate_path.read_text())
    if decision == "approve" and result["verdict"] != "promote" and not override:
        raise ValueError(f"the gate said {result['verdict']}; approving anyway needs --override and a note")
    result["human_decision"] = {"decision": decision, "note": note, "overrode_gate": decision == "approve"
                                and result["verdict"] != "promote", "at": datetime.now(timezone.utc).isoformat()}
    gate_path.write_text(json.dumps(result, indent=2) + "\n")
    if decision == "approve":
        active.parent.mkdir(parents=True, exist_ok=True)
        active.write_text(json.dumps({"active": result["candidate"]["file"], "promoted_at": result["human_decision"]["at"],
                                      "gate_result": gate_path.name}, indent=2) + "\n")
    return result


def _corrections_summary(cases: list[dict[str, Any]]) -> dict[str, int]:
    human = sum(c.get("author", "human") == "human" for c in cases)
    approved = sum(c.get("approved_by_human", c.get("author", "human") == "human") for c in cases)
    return {"total": len(cases), "human": human, "assistant_drafted": len(cases) - human, "approved_by_human": approved}

"""`doomlab regress`: ask a policy what it would do at each corrected moment. No game; `repeats` asks per case.

The hosted model is not fully repeatable even at temperature 0, so a case is asked several times and passes on
enough votes (the gate's rule), rather than on one lucky or unlucky answer.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from doomlab.agents.base import Agent, AgentStop
from doomlab.review.corrections import context_from, describe_expectation, meets


async def run_regression(cases: list[dict[str, Any]], make_agent: Callable[[dict[str, Any]], Agent], *,
                         repeats: int = 1, votes_to_pass: int = 1) -> list[dict[str, Any]]:
    """`make_agent(case)` returns the agent that faced that moment (react_single, or the commander's specialist)."""
    results = []
    for case in cases:
        observation, history, tools = context_from(case["snapshot"])
        answers = []
        for _ in range(repeats):
            try:
                decision = make_agent(case).decide(observation, tools, history)
                call = await decision if inspect.isawaitable(decision) else decision
                answers.append((_text(call), call is not None and meets(case["expect"], call)))
            except AgentStop as stop:
                answers.append((f"stopped: {stop.outcome}", False))
        votes = sum(ok for _, ok in answers)
        results.append({"id": case["id"], "author": case.get("author", "human"), "label": case["label"],
                        "expect": describe_expectation(case["expect"]), "chose": " | ".join(a for a, _ in answers),
                        "votes": votes, "asked": repeats, "passed": votes >= votes_to_pass})
    return results


def _text(call: Any) -> str:
    return "no call" if call is None else f"{call.name}({', '.join(f'{k}={v}' for k, v in call.arguments.items())})"

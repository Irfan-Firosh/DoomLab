"""The Analyst: an LLM that turns counted failures and corrections into at most 3 lessons (a candidate policy).

It only proposes. Code checks every lesson before it becomes a policy: at most 3, at most 300 characters,
each citing evidence that exists (a miner signature or a correction id), and no object ids or seeds, since
those belong to one moment and would not generalise. Its inputs come from dev traces only.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doomlab.agents.base import AgentStop
from doomlab.agents.prompting import system_prompt
from doomlab.agents.react import ChatClient, ReactAgent
from doomlab.llm.budget import Budget
from doomlab.llm.preflight import Decoding
from doomlab.policy import MAX_LESSON_CHARS, MAX_LESSONS, Policy, load_policy
from doomlab.tools.registry import ToolSpec

MAX_ATTEMPTS = 2
_SPECIFIC = re.compile(r"\b(target_)?id\s*[=:#]?\s*\d+|\bseed\s*\d+", re.IGNORECASE)

ANALYST_SYSTEM = """You improve an LLM agent that plays the game Doom by calling tools.
You will see counted failure patterns from its recorded games and mistakes that reviewers corrected.
Write at most 3 short lessons that will be appended to the agent's system prompt.

Rules for lessons:
- Target the most frequent and most costly failures first; the counts tell you which.
- Each lesson is one general rule of at most 300 characters. No object ids, seed numbers or coordinates.
- Each lesson cites its evidence: failure pattern names and/or correction ids from the input.
- Lessons must fit the agent's tools and rules; do not invent tools.
Call propose_lessons exactly once."""

PROPOSE = ToolSpec(
    name="propose_lessons",
    description="Propose at most 3 lessons, each with the evidence it addresses.",
    parameters={
        "type": "object",
        "properties": {
            "lessons": {
                "type": "array", "maxItems": MAX_LESSONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "maxLength": MAX_LESSON_CHARS},
                        "evidence": {"type": "array", "items": {"type": "string"},
                                     "description": "failure pattern names and/or correction ids"},
                    },
                    "required": ["text", "evidence"],
                },
            }
        },
        "required": ["lessons"],
        "additionalProperties": False,
    },
)


class AnalystError(RuntimeError):
    """The Analyst did not produce acceptable lessons within its attempts."""


def analyst_prompt(report: dict[str, Any], cases: list[dict[str, Any]], *, scenario: str, variant: str) -> str:
    lines = [f"The trial will test your lessons on `{variant}` playing `{scenario}`. Its current system prompt:",
             "---", system_prompt(scenario), "---", "",
             f"Failure patterns counted over {report['episodes']} dev episodes ({report['decisions']} decisions):"]
    for s in report["signatures"]:
        lines.append(f"- {s['name']}: {s['occurrences']} times in {s['episodes']}/{report['episodes']} episodes. {s['meaning']}")
    lines += ["", "Corrected decisions (what the agent did, and what it should have done):"]
    for c in cases:
        author = "human" if c.get("author", "human") == "human" else "AI-drafted"
        original = f"{c['original']['tool']}({', '.join(f'{k}={v}' for k, v in c['original']['args'].items())})"
        lines.append(f"- {c['id']} ({author}), {c['snapshot']['scenario']}, {c['label']}: did {original}. "
                     f"Fix: {c['fix']}")
    return "\n".join(lines)


def check_lessons(lessons: Any, known_evidence: set[str]) -> str | None:
    if not isinstance(lessons, list) or not lessons:
        return "lessons must be a non-empty list"
    if len(lessons) > MAX_LESSONS:
        return f"{len(lessons)} lessons; at most {MAX_LESSONS} allowed"
    for i, lesson in enumerate(lessons, start=1):
        text = lesson.get("text") if isinstance(lesson, dict) else None
        evidence = lesson.get("evidence") if isinstance(lesson, dict) else None
        if not isinstance(text, str) or not text.strip():
            return f"lesson {i} has no text"
        if len(text) > MAX_LESSON_CHARS:
            return f"lesson {i} is {len(text)} characters; at most {MAX_LESSON_CHARS}"
        if _SPECIFIC.search(text):
            return f"lesson {i} names a specific object id or seed; lessons must be general"
        if not isinstance(evidence, list) or not evidence:
            return f"lesson {i} must cite evidence (pattern names or correction ids)"
        unknown = sorted(set(evidence) - known_evidence)
        if unknown:
            return f"lesson {i} cites unknown evidence {unknown}"
    return None


async def propose(client: ChatClient, decoding: Decoding, budget: Budget, report: dict[str, Any],
                  cases: list[dict[str, Any]], *, scenario: str, variant: str, parent: Policy, out: Path,
                  version: str = "v1") -> Policy:
    known = {s["name"] for s in report["signatures"]} | {c["id"] for c in cases}
    analyst = ReactAgent(client, scenario=scenario, decoding=decoding, budget=budget, system=ANALYST_SYSTEM,
                         role="analyst")
    prompt = analyst_prompt(report, cases, scenario=scenario, variant=variant)
    problem = ""
    for _ in range(MAX_ATTEMPTS):
        try:
            call = await analyst.ask(prompt, (PROPOSE,))
        except AgentStop as stop:
            raise AnalystError(f"analyst stopped: {stop.outcome} {stop.message}") from stop
        lessons = call.arguments.get("lessons") if call.name == PROPOSE.name else None
        problem = check_lessons(lessons, known) if call.name == PROPOSE.name else f"called {call.name}"
        if problem is None:
            _write(out, version, parent, lessons, decoding, analyst.drain_events())
            return load_policy(out)
        prompt = f"{prompt}\n\nYour last proposal was invalid: {problem}. Call propose_lessons again, fixing it."
    raise AnalystError(f"no acceptable lessons after {MAX_ATTEMPTS} attempts: {problem}")


def _write(out: Path, version: str, parent: Policy, lessons: list[dict[str, Any]], decoding: Decoding,
           events: list[dict[str, Any]]) -> None:
    usage = [e.get("usage") or {} for e in events if e["event"] == "llm_call"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "version": version,
        "parent": parent.version,
        "lessons": [lesson["text"].strip() for lesson in lessons],
        "evidence": [lesson["evidence"] for lesson in lessons],
        "analyst": {"model": decoding.model_id, "calls": len(usage),
                    "tokens": sum(u.get("total_tokens", 0) for u in usage)},
        "created": datetime.now(timezone.utc).isoformat(),
    }, indent=2) + "\n")

"""The frozen recipe: everything that shapes how an LLM agent behaves, with one fingerprint (sha256).

`doomlab freeze` writes configs/frozen.json. Every episode records the fingerprint of the recipe it ran with
(`episode_start.config_hash`); `doomlab eval` never mixes fingerprints in one results folder, and the test
split runs only on the frozen recipe. The readable sections (model, budgets, prompts, tools) say *what* was
frozen; `code` hashes the behaviour modules so that no change can slip in unnoticed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doomlab.config import REPO_ROOT, RUNS_DIR

FROZEN_PATH = REPO_ROOT / "configs" / "frozen.json"
PACKAGE = REPO_ROOT / "src" / "doomlab"
BEHAVIOUR_CODE = ("agents", "env", "graph", "llm", "tools", "runner.py", "policy.py")  # not eval/cli: scoring may evolve


class FreezeError(RuntimeError):
    """The frozen file is missing or altered, or a results folder would mix recipes."""


def recipe(decoding: dict[str, Any] | None, policy: Any) -> dict[str, Any]:
    from doomlab.agents import prompting
    from doomlab.agents.commander import MAX_MODE_ATTEMPTS, choose_mode_spec
    from doomlab.agents.modes import FIGHT, NAVIGATE, ROLE_TOOL_NAMES
    from doomlab.agents.react import MAX_ATTEMPTS, REMINDER
    from doomlab.graph.router import MAX_CONSECUTIVE_REJECTIONS
    from doomlab.llm.budget import CALLS_BY_SCENARIO, SECONDS_PER_CALL, TOKENS_PER_CALL
    from doomlab.llm.client import MAX_CONCURRENCY, MAX_REQUESTS_PER_MINUTE
    from doomlab.runner import MAX_STEPS
    from doomlab.tools import executor
    from doomlab.tools.registry import TOOLS, to_openai

    lessons = tuple(policy.lessons)
    scenarios = sorted(prompting.GOALS)
    return {
        "model": decoding,
        "rate": {"requests_per_minute": MAX_REQUESTS_PER_MINUTE, "concurrency": MAX_CONCURRENCY},
        "budgets": {"calls": CALLS_BY_SCENARIO, "seconds_per_call": SECONDS_PER_CALL, "tokens_per_call": TOKENS_PER_CALL},
        "policy": {"version": policy.version, "lessons": list(lessons)},
        "prompts": {
            "system": {s: prompting.system_prompt(s, lessons=lessons) for s in scenarios},
            "specialist": {s: {m: prompting.system_prompt(s, m, lessons) for m in (FIGHT, NAVIGATE)} for s in scenarios},
            "commander": {s: prompting.commander_system_prompt(s, lessons) for s in scenarios},
            "turn_example": prompting.turn_prompt(*_example_turn()),
            "commander_example": prompting.commander_prompt(*_example_turn(), trigger="no mode yet", current=None),
            "reminder": REMINDER,
        },
        "tools": to_openai((*TOOLS.values(), choose_mode_spec((FIGHT, NAVIGATE)))),
        "harness": {
            "max_steps": MAX_STEPS,
            "max_consecutive_rejections": MAX_CONSECUTIVE_REJECTIONS,
            "history_turns": prompting.HISTORY_TURNS,
            "llm_attempts_per_decision": MAX_ATTEMPTS,
            "commander_attempts": MAX_MODE_ATTEMPTS,
            "role_tools": {m: list(names) for m, names in ROLE_TOOL_NAMES.items()},
            "aim_cones": {**executor.CONE_BY_ENEMY, "default": executor.DEFAULT_CONE},
        },
        "code": _code_hashes(),
    }


def fingerprint(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def current() -> tuple[dict[str, Any], str]:
    """The recipe this checkout would run with right now, and its fingerprint."""
    from doomlab.policy import load_policy
    from doomlab.policy_registry import active_policy_path

    r = recipe(preflight_decoding(), load_policy(active_policy_path()))
    return r, fingerprint(r)


def preflight_decoding(path: Path = RUNS_DIR / "preflight.json") -> dict[str, Any] | None:
    """Model and decoding from the last passing preflight, or None if there is none."""
    if not path.exists():
        return None
    report = json.loads(path.read_text())
    if not report.get("ok"):
        return None
    return {"model_id": report["model_id"], **report["decoding_frozen"]}


def write_frozen(value: dict[str, Any], path: Path = FROZEN_PATH, *, name: str) -> dict[str, Any]:
    frozen = {"name": name, "hash": fingerprint(value), "frozen_at": datetime.now(timezone.utc).isoformat(),
              "recipe": value}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(frozen, indent=2, ensure_ascii=False) + "\n")
    return frozen


def load_frozen(path: Path = FROZEN_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    frozen = json.loads(path.read_text())
    if fingerprint(frozen["recipe"]) != frozen["hash"]:
        raise FreezeError(f"{path}: recipe does not match its recorded hash (edited by hand?); run `doomlab freeze` again")
    return frozen


def _code_hashes() -> dict[str, str]:
    files = []
    for entry in BEHAVIOUR_CODE:
        target = PACKAGE / entry
        files += sorted(target.rglob("*.py")) if target.is_dir() else [target]
    return {f.relative_to(REPO_ROOT).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


def _example_turn() -> tuple[Any, Any]:
    """A fixed observation and history, so any change to how turn prompts are written changes the hash."""
    from doomlab.agents.base import StepRecord
    from doomlab.env.perception import Fact, Observation

    fact = Fact(id=3, name="Demon", kind="enemy", bearing_deg=12.0, ahead=280.0, offset=60.0, distance=286.0)
    history = (StepRecord(1, "attack", {"burst": 1}, False, "NO_ENEMY_IN_CONE", "no enemy inside its aim cone", 0),)
    return Observation(tic=70, facts=(fact,), health=100.0, ammo=25.0, kills=1.0), history

"""Failure miner: recurring failure signatures across dev traces, counted, with examples to cite.

Deterministic (same traces, same report), so the Analyst's lessons rest on counts rather than impressions.
Step signatures are counted per decision; episode signatures once per episode. Test-split traces are refused.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from doomlab.review.flags import LOW_HEALTH, TEST_SEEDS, Step, episode_steps, turned_away

MAX_EXAMPLES = 3
EARLY_DEATH_TICS = 600  # under ~17 s: dying this soon is a failure in either survival scenario


def _medikit_ignored(s: Step) -> bool:
    obs = s.observation
    has_item = any(f.kind == "item" for f in obs.facts)
    return has_item and obs.health is not None and obs.health < LOW_HEALTH and s.call.name != "go_to"


# name -> (what it means, test on one decision)
STEP_SIGNATURES: dict[str, tuple[str, Callable[[Step], bool]]] = {
    "needless_observe": ("called observe, which shows nothing new while the game is paused",
                         lambda s: s.call.name == "observe"),
    "blind_attack": ("attacked with no enemy in the aim cone (rejected)", lambda s: s.code == "NO_ENEMY_IN_CONE"),
    "turned_from_enemy": ("turned away from the nearest enemy while able to fight", turned_away),
    "medikit_ignored": (f"did not go to a visible medikit at health below {LOW_HEALTH:g}", _medikit_ignored),
    "wasteful_burst": ("fired more than one shot although one hit usually kills",
                       lambda s: s.call.name == "attack" and s.ok and s.call.arguments.get("burst", 1) > 1),
    "other_rejection": ("a call the executor refused for another reason",
                        lambda s: not s.ok and s.code not in ("NO_ENEMY_IN_CONE", "NOTHING_CHANGED")),
}
EPISODE_SIGNATURES: dict[str, tuple[str, Callable[[dict[str, Any]], bool]]] = {
    "budget_exhausted": ("ran out of LLM calls and stood still until the end", lambda end: end.get("stop_reason") == "budget"),
    "recovery_exhausted": ("three rejections in a row ended its control",
                           lambda end: end.get("stop_reason") == "recovery_exhausted"),
    "early_death": (f"died before {EARLY_DEATH_TICS} tics",
                    lambda end: bool(end.get("dead")) and end.get("tics", 0) < EARLY_DEATH_TICS),
}


def mine(paths: list[Path]) -> dict[str, Any]:
    occurrences: Counter[str] = Counter()
    episodes: defaultdict[str, set[str]] = defaultdict(set)
    by_variant: defaultdict[str, Counter[str]] = defaultdict(Counter)
    examples: defaultdict[str, list[str]] = defaultdict(list)
    decisions = 0
    for path in sorted(paths, key=lambda p: Path(p).name):
        steps, end = episode_steps(path)
        name = Path(path).name
        if (steps and steps[0].seed in TEST_SEEDS) or _named_seed(name) in TEST_SEEDS:
            raise ValueError(f"{name} is a test-split episode; the miner reads dev traces only")
        decisions += len(steps)
        for s in steps:
            for sig, (_, test) in STEP_SIGNATURES.items():
                if test(s):
                    _count(sig, name, s.variant, f"{name}#{s.step}", occurrences, episodes, by_variant, examples)
        variant = steps[0].variant if steps else name.rsplit("-", 1)[-1].removesuffix(".jsonl")
        for sig, (_, test) in EPISODE_SIGNATURES.items():
            if test(end):
                _count(sig, name, variant, name, occurrences, episodes, by_variant, examples)
    meaning = {k: v[0] for k, v in {**STEP_SIGNATURES, **EPISODE_SIGNATURES}.items()}
    signatures = [
        {"name": sig, "meaning": meaning[sig], "occurrences": occurrences[sig], "episodes": len(episodes[sig]),
         "by_variant": dict(sorted(by_variant[sig].items())), "examples": examples[sig]}
        for sig in sorted(occurrences, key=lambda k: (-occurrences[k], k))
    ]
    return {"episodes": len(paths), "decisions": decisions, "signatures": signatures}


def _count(sig: str, episode: str, variant: str, example: str, occurrences: Counter[str],
           episodes: defaultdict[str, set[str]], by_variant: defaultdict[str, Counter[str]],
           examples: defaultdict[str, list[str]]) -> None:
    occurrences[sig] += 1
    episodes[sig].add(episode)
    by_variant[sig][variant] += 1
    if len(examples[sig]) < MAX_EXAMPLES and not any(e.split("#")[0] == episode for e in examples[sig]):
        examples[sig].append(example)  # at most one example per episode, so evidence is spread out


def _named_seed(name: str) -> int | None:
    parts = name.removesuffix(".jsonl").split("-")
    seed = next((p for p in reversed(parts) if p.startswith("s") and p[1:].isdigit()), None)
    return int(seed[1:]) if seed else None

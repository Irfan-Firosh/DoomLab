"""The policy: lessons appended to every system prompt. v0 has none; an improvement trial proposes v1.

Only this file differs between a parent policy and its candidate, so an A/B compares the lessons alone.
Limits follow the spec: at most 3 lessons, each at most 300 characters.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from doomlab.config import REPO_ROOT

DEFAULT_POLICY = REPO_ROOT / "policies" / "v0.json"
MAX_LESSONS = 3
MAX_LESSON_CHARS = 300


class PolicyError(ValueError):
    """The policy file breaks the lesson limits or is malformed."""


@dataclass(frozen=True)
class Policy:
    version: str
    lessons: tuple[str, ...] = ()


def load_policy(path: Path = DEFAULT_POLICY) -> Policy:
    data = json.loads(Path(path).read_text())
    lessons = tuple(data.get("lessons", []))
    if len(lessons) > MAX_LESSONS:
        raise PolicyError(f"{path}: {len(lessons)} lessons; at most {MAX_LESSONS} allowed")
    too_long = [i for i, lesson in enumerate(lessons, 1) if not isinstance(lesson, str) or len(lesson) > MAX_LESSON_CHARS]
    if too_long:
        raise PolicyError(f"{path}: lesson(s) {too_long} must be text of at most {MAX_LESSON_CHARS} characters")
    return Policy(version=str(data["version"]), lessons=lessons)

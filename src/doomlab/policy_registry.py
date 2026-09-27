"""Which policy new runs use. Kept apart from policy.py (part of the frozen recipe's code) on purpose:
choosing a policy file is bookkeeping; the lessons it holds are what the recipe fingerprints."""

from __future__ import annotations

import json
from pathlib import Path

from doomlab.policy import DEFAULT_POLICY

ACTIVE = DEFAULT_POLICY.parent / "active.json"  # written only by a human approval (doomlab improve --decide)


def active_policy_path(active: Path = ACTIVE) -> Path:
    """The approved policy if the registry points at one, otherwise v0."""
    if not active.exists():
        return DEFAULT_POLICY
    return active.parent / json.loads(active.read_text())["active"]

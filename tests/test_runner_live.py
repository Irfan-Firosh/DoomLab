"""Scripted agent through the runner on real vizDoom (headless, no network)."""

import pytest

from doomlab.agents.scripted import ScriptedAgent
from doomlab.env.doom import DoomSession
from doomlab.runner import run_episode


@pytest.mark.parametrize("seed", range(5))
def test_scripted_wins_basic_dev_seeds(seed):
    with DoomSession("basic", seed=seed) as session:
        result = run_episode(session, ScriptedAgent(), scenario="basic", seed=seed)
    assert result.outcome == "success", result
    assert result.tics <= 300 and result.rejected == 0

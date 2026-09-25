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


@pytest.mark.parametrize("scenario", ["defend_the_center", "health_gathering", "health_gathering_supreme"])
def test_scripted_plays_new_scenarios(scenario):
    with DoomSession(scenario, seed=0) as session:
        result = run_episode(session, ScriptedAgent(), scenario=scenario, seed=0, max_steps=200)
    assert result.outcome in {"success", "died"}, result.outcome  # played to a real end, never frozen
    assert result.rejected == 0 and result.tics > 100

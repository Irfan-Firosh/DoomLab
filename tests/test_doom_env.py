"""Runs real vizDoom headless (fast, no network)."""

import pytest

from doomlab.env.doom import DoomSession
from doomlab.env.perception import perceive


def test_basic_session_reports_buttons_and_instrumented_variables():
    with DoomSession("basic", seed=0) as session:
        assert session.info.buttons == ("MOVE_LEFT", "MOVE_RIGHT", "ATTACK")
        state = session.read_state()
    for name in ("AMMO2", "POSITION_X", "POSITION_Y", "ANGLE", "KILLCOUNT"):
        assert name in state.variables
    assert state.frame is not None and state.frame.shape == (240, 320, 3)
    assert not state.finished


def test_scenarios_expose_their_own_buttons():
    with DoomSession("defend_the_center", seed=0) as s:
        assert s.info.buttons == ("TURN_LEFT", "TURN_RIGHT", "ATTACK")
    with DoomSession("health_gathering", seed=0) as s:
        assert s.info.buttons == ("TURN_LEFT", "TURN_RIGHT", "MOVE_FORWARD")


def test_unknown_scenario_rejected():
    with pytest.raises(ValueError):
        DoomSession("deathmatch_of_doom", seed=0)


def test_same_seed_gives_same_starting_facts():
    with DoomSession("basic", seed=3) as a:
        first = perceive(a.read_state()).facts
    with DoomSession("basic", seed=3) as b:
        second = perceive(b.read_state()).facts
    assert first == second and len(first) == 1


def test_left_right_agrees_with_screen_position():
    """Independent check of the sign convention: LEFT facts must be drawn left of screen centre."""
    checked = 0
    for seed in range(8):
        with DoomSession("basic", seed=seed) as session:
            state = session.read_state()
        (fact,) = perceive(state).facts
        (raw,) = [l for l in state.labels if l.object_id == fact.id]
        centre_x = raw.screen_x + raw.screen_width / 2
        if abs(fact.offset) > 8:  # skip near-centred cases where rounding could flip the sign
            assert (fact.offset > 0) == (centre_x < 160), (seed, fact, centre_x)
            checked += 1
    assert checked >= 3


def test_finished_episode_still_reports_final_variables():
    with DoomSession("basic", seed=0) as session:  # seed 0 starts 20u off: one shot kills
        session.game.make_action([0, 0, 1], 1)
        for _ in range(10):
            if session.game.is_episode_finished():
                break
            session.game.make_action([0, 0, 0], 1)
        state = session.read_state()
    assert state.finished and state.labels == ()
    assert state.variables["KILLCOUNT"] == 1.0

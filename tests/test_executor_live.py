"""Executor against real vizDoom (headless, no network)."""

import pytest

from doomlab.env.doom import DoomSession
from doomlab.tools.executor import AIM_STOP_OFFSET, Executor


@pytest.mark.parametrize("seed", [0, 1, 2, 5, 7])
def test_aim_then_attack_kills_on_basic(seed):
    with DoomSession("basic", seed=seed) as session:
        ex = Executor(session)
        target = ex.observe().facts[0].id
        aimed = ex.execute("aim_at", {"target_id": target})
        assert aimed.ok and abs(aimed.after.facts[0].offset) <= AIM_STOP_OFFSET, aimed.message
        shot = ex.execute("attack", {"burst": 1})
        assert shot.ok and shot.episode_finished and shot.kills_gained == 1


def test_rejected_attack_does_not_advance_the_game():
    with DoomSession("basic", seed=1) as session:  # seed 1 starts far off-centre
        ex = Executor(session)
        tic = session.game.get_episode_time()
        result = ex.execute("attack", {"burst": 1})
        assert result.code == "NO_ENEMY_IN_CONE"
        assert session.game.get_episode_time() == tic and result.after.ammo == result.before.ammo


def test_aim_at_turns_in_defend_the_center():
    with DoomSession("defend_the_center", seed=0) as session:
        ex = Executor(session)
        ex.execute("observe", {})
        enemies = [f for f in ex.observe().facts if f.kind == "enemy"]
        target = max(enemies, key=lambda f: abs(f.offset)) if enemies else None
        if target is None:
            pytest.skip("no enemy visible at start")
        result = ex.execute("aim_at", {"target_id": target.id})
        assert result.ok
        assert all(b[2] == 0 for b in result.buttons)  # aiming never fires


def test_turn_changes_the_real_angle():
    with DoomSession("defend_the_center", seed=0) as session:
        ex = Executor(session)
        start = session.read_state().variables["ANGLE"]
        result = ex.execute("turn", {"degrees": 90})
        end = session.read_state().variables["ANGLE"]
    assert result.ok and abs(((end - start) % 360) - 90) <= 4  # turning speeds up mid-turn; we stop within a tic


def test_go_to_picks_up_a_real_medikit():
    with DoomSession("health_gathering", seed=0) as session:  # starts at 92 health, medikit visible
        ex = Executor(session)
        medikit = next(f for f in ex.observe().facts if f.name == "Medikit")
        result = ex.execute("go_to", {"target_id": medikit.id})
    assert result.ok and "picked up" in result.message, result.message
    assert result.after.health > result.before.health

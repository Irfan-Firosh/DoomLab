from fakes import FakeSession

from doomlab.tools.executor import IN_CONE_OFFSET, Executor


def run(session, name, args):
    return Executor(session).execute(name, args)


def test_unknown_tool_rejected_no_buttons():
    s = FakeSession()
    r = run(s, "fly", {})
    assert (r.ok, r.code, r.buttons, r.tics_used) == (False, "UNKNOWN_TOOL", (), 0)
    assert s.game.actions == []


def test_unavailable_tool_rejected():
    s = FakeSession(buttons=("TURN_LEFT", "TURN_RIGHT", "MOVE_FORWARD"))
    assert run(s, "attack", {"burst": 1}).code == "UNAVAILABLE_TOOL"
    assert s.game.actions == []


def test_bad_args_rejected():
    s = FakeSession()
    r = run(s, "attack", {"burst": 99})
    assert r.code == "BAD_ARGS" and "burst" in r.message
    assert s.game.actions == []


def test_aim_at_unknown_target_rejected():
    s = FakeSession()
    assert run(s, "aim_at", {"target_id": 42}).code == "UNKNOWN_TARGET"
    assert s.game.actions == []


def test_attack_without_enemy_in_cone_rejected_and_game_time_unchanged():
    s = FakeSession(target_y=100.0)  # 100u off to the left
    r = run(s, "attack", {"burst": 1})
    assert r.code == "NO_ENEMY_IN_CONE"
    assert s.game.actions == [] and s.tic == 0 and s.ammo == 50


def test_attack_with_no_ammo_rejected():
    s = FakeSession(target_y=0.0, ammo=0)
    assert run(s, "attack", {"burst": 1}).code == "NO_AMMO"


def test_observe_presses_nothing():
    s = FakeSession()
    r = run(s, "observe", {})
    assert r.ok and r.buttons == () and r.tics_used == 0 and r.after.facts


def test_aim_at_strafes_until_centred():
    s = FakeSession(target_y=40.0)
    r = run(s, "aim_at", {"target_id": 0})
    assert r.ok
    assert abs(r.after.facts[0].offset) <= 6.0
    assert r.tics_used > 0 and all(a in ((1, 0, 0), (0, 1, 0), (0, 0, 0)) for a in r.buttons)


def test_aim_at_turns_when_scenario_has_turn_buttons():
    s = FakeSession(buttons=("TURN_LEFT", "TURN_RIGHT", "ATTACK"), target_y=-60.0)
    r = run(s, "aim_at", {"target_id": 0})
    assert r.ok and abs(r.after.facts[0].offset) <= 6.0
    assert [0, 1, 0] in [list(b) for b in r.buttons]  # turned right toward a RIGHT target


def test_aim_then_attack_kills():
    s = FakeSession(target_y=40.0)
    ex = Executor(s)
    assert ex.execute("aim_at", {"target_id": 0}).ok
    r = ex.execute("attack", {"burst": 1})
    assert r.ok and r.episode_finished
    assert (r.before.kills, r.after.kills) == (0, 1)  # final variables stay readable after the episode ends
    assert r.kills_gained == 1


def test_no_actions_after_episode_ends():
    s = FakeSession(target_y=0.0)
    ex = Executor(s)
    ex.execute("attack", {"burst": 1})
    presses = len(s.game.actions)
    r = ex.execute("aim_at", {"target_id": 0})
    assert r.code == "EPISODE_FINISHED" and len(s.game.actions) == presses


def test_in_cone_threshold_is_the_calibrated_value():
    assert IN_CONE_OFFSET == 15.0

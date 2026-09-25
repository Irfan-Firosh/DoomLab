from fakes import FakeSession

from doomlab.tools.executor import Executor


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



TURNING = ("TURN_LEFT", "TURN_RIGHT", "ATTACK")
WALKING = ("TURN_LEFT", "TURN_RIGHT", "MOVE_FORWARD")


def test_cone_is_per_enemy_from_calibration():
    from doomlab.env.perception import Fact
    from doomlab.tools.executor import cone_for, in_cone

    def enemy(name, offset):
        return Fact(0, name, "enemy", 0.0, 300.0, offset, 300.0)

    assert cone_for("Cacodemon") == 15.0 and cone_for("MarineChainsawVzd") == 9.0 and cone_for("Unknown") == 9.0
    assert in_cone(enemy("Cacodemon", 12.0)) and not in_cone(enemy("MarineChainsawVzd", 12.0))


def test_turn_reaches_requested_angle():
    s = FakeSession(buttons=TURNING)
    r = run(s, "turn", {"degrees": 90})
    assert r.ok and abs(s.angle - 90.0) <= 1.76


def test_turn_right_is_negative():
    s = FakeSession(buttons=TURNING)
    run(s, "turn", {"degrees": -45})
    assert abs(s.angle + 45.0) <= 1.76


def test_turn_rejected_in_basic():
    s = FakeSession()
    assert run(s, "turn", {"degrees": 90}).code == "UNAVAILABLE_TOOL" and s.game.actions == []


def test_go_to_picks_up_item_and_stops():
    s = FakeSession(buttons=WALKING, target_y=None, items=[(200.0, 60.0)], health=60.0)
    r = run(s, "go_to", {"target_id": 10})
    assert r.ok and "picked up" in r.message
    assert s.health > 60.0 and 10 not in s.items


def test_go_to_at_full_health_reaches_but_does_not_pick_up():
    s = FakeSession(buttons=WALKING, target_y=None, items=[(200.0, 0.0)], health=100.0)
    r = run(s, "go_to", {"target_id": 10})
    assert r.ok and "not picked up" in r.message and 10 in s.items


def test_go_to_blocked_by_wall_reports_no_effect():
    s = FakeSession(buttons=WALKING, target_y=None, items=[(300.0, 0.0)], health=60.0, wall_x=50.0)
    r = run(s, "go_to", {"target_id": 10})
    assert r.ok and r.message.startswith("no effect")
    assert r.tics_used < 60  # gives up quickly instead of burning the clock


def test_go_to_rejects_enemies():
    s = FakeSession(buttons=WALKING, target_y=0.0, health=60.0)
    assert run(s, "go_to", {"target_id": 0}).code == "NOT_AN_ITEM"


def test_aim_by_turning_stops_when_turning_cannot_get_closer():
    s = FakeSession(buttons=TURNING, target_y=-700.0)  # far off to the right; one turn tic moves the aim a lot
    r = run(s, "aim_at", {"target_id": 0})
    assert r.ok and r.tics_used < 90 and "stopped after" not in r.message


def test_observe_again_is_rejected_until_game_time_passes():
    ex = Executor(FakeSession(buttons=("TURN_LEFT", "TURN_RIGHT", "ATTACK"), target_y=None, health=100.0, timeout=2100))
    assert ex.execute("observe", {}).ok
    assert ex.execute("observe", {}).code == "NOTHING_CHANGED"
    assert ex.execute("turn", {"degrees": 45}).ok
    assert ex.execute("observe", {}).ok  # time has passed: looking is allowed again

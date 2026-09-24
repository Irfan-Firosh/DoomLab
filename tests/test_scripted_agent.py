from doomlab.agents.scripted import ScriptedAgent
from doomlab.env.perception import Fact, Observation
from doomlab.tools.registry import TOOLS, ToolCall

ALL = tuple(TOOLS.values())
NO_ATTACK = (TOOLS["observe"], TOOLS["aim_at"])


def fact(id, offset, distance=400.0, kind="enemy", name="Cacodemon"):
    return Fact(id=id, name=name, kind=kind, bearing_deg=0.0, ahead=distance, offset=offset, distance=distance)


def obs(*facts, ammo=50.0):
    return Observation(tic=14, facts=tuple(sorted(facts, key=lambda f: f.distance)), health=None, ammo=ammo, kills=0.0)


def decide(observation, tools=ALL):
    return ScriptedAgent().decide(observation, tools, ())


def test_attacks_when_enemy_in_cone():
    assert decide(obs(fact(0, offset=3.0))) == ToolCall("attack", {"burst": 1})


def test_aims_at_nearest_enemy_when_off_centre():
    far, near = fact(1, offset=80.0, distance=900.0), fact(2, offset=-60.0, distance=300.0)
    assert decide(obs(far, near)) == ToolCall("aim_at", {"target_id": 2})


def test_ignores_items_when_choosing_a_target():
    medikit = fact(5, offset=40.0, distance=100.0, kind="item", name="Medikit")
    assert decide(obs(medikit, fact(3, offset=50.0))) == ToolCall("aim_at", {"target_id": 3})


def test_does_not_attack_without_ammo():
    assert decide(obs(fact(0, offset=0.0), ammo=0.0)) is None


def test_gives_up_when_no_enemy_visible():
    assert decide(obs()) is None


def test_never_calls_a_tool_the_scenario_lacks():
    assert decide(obs(fact(0, offset=0.0)), tools=NO_ATTACK) is None

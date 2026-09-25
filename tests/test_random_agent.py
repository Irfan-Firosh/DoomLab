from fakes import FakeSession

from doomlab.agents.random_agent import RandomAgent
from doomlab.env.perception import Fact, Observation
from doomlab.runner import run_episode
from doomlab.tools.registry import TOOLS, available_tools, validate_args

ENEMY = Fact(id=3, name="Demon", kind="enemy", bearing_deg=10.0, ahead=300.0, offset=50.0, distance=304.0)
ITEM = Fact(id=7, name="Medikit", kind="item", bearing_deg=-5.0, ahead=200.0, offset=-17.0, distance=201.0)
EVERYTHING = tuple(TOOLS[n] for n in ("observe", "aim_at", "attack", "turn", "go_to"))


def obs(*facts):
    return Observation(tic=1, facts=facts, health=50.0, ammo=26.0, kills=0.0)


def draws(agent, observation, tools, n=300):
    return [agent.decide(observation, tools, ()) for _ in range(n)]


def test_every_call_is_on_the_menu_with_schema_valid_arguments():
    for call in draws(RandomAgent(seed=0), obs(ENEMY, ITEM), EVERYTHING):
        assert call.name in {t.name for t in EVERYTHING}
        assert validate_args(TOOLS[call.name], call.arguments) is None


def test_targets_are_visible_and_go_to_only_targets_items():
    calls = draws(RandomAgent(seed=1), obs(ENEMY, ITEM), EVERYTHING)
    assert {c.arguments["target_id"] for c in calls if c.name == "aim_at"} == {3, 7}
    assert {c.arguments["target_id"] for c in calls if c.name == "go_to"} == {7}


def test_tools_needing_a_target_are_skipped_when_none_is_visible():
    names = {c.name for c in draws(RandomAgent(seed=2), obs(), EVERYTHING)}
    assert names == {"observe", "attack", "turn"}
    assert "go_to" not in {c.name for c in draws(RandomAgent(seed=2), obs(ENEMY), EVERYTHING)}


def test_choices_are_roughly_uniform_over_callable_tools():
    counts = {}
    for call in draws(RandomAgent(seed=3), obs(ENEMY, ITEM), EVERYTHING, n=2000):
        counts[call.name] = counts.get(call.name, 0) + 1
    assert set(counts) == {t.name for t in EVERYTHING}
    assert all(300 < c < 500 for c in counts.values()), counts  # expected 400 each


def test_same_seed_same_choices_different_seed_different_choices():
    a, b, c = RandomAgent(seed=5), RandomAgent(seed=5), RandomAgent(seed=6)
    assert draws(a, obs(ENEMY, ITEM), EVERYTHING, 50) == draws(b, obs(ENEMY, ITEM), EVERYTHING, 50)
    assert draws(RandomAgent(seed=5), obs(ENEMY, ITEM), EVERYTHING, 50) != draws(c, obs(ENEMY, ITEM), EVERYTHING, 50)


def test_plays_whole_episodes_without_an_llm_and_repeats_exactly():
    def play():
        return run_episode(FakeSession(target_y=40.0), RandomAgent(seed=4), scenario="basic", seed=0)

    first, second = play(), play()
    assert first.llm_calls == 0 and first.outcome in {"success", "timeout"}
    assert [(s.tool, s.args, s.code) for s in first.steps] == [(s.tool, s.args, s.code) for s in second.steps]


def test_config_records_the_seed_for_the_trace():
    assert RandomAgent(seed=9).config == {"seed": 9}
    assert available_tools(("MOVE_LEFT", "MOVE_RIGHT", "ATTACK"))  # sanity: basic has a menu to draw from

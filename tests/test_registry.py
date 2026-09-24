import pytest

from doomlab.tools.registry import TOOLS, available_tools, to_openai, validate_args


def names(buttons):
    return [t.name for t in available_tools(buttons)]


def test_basic_offers_observe_aim_attack():
    assert names(("MOVE_LEFT", "MOVE_RIGHT", "ATTACK")) == ["observe", "aim_at", "attack"]


def test_defend_the_center_aims_by_turning():
    assert names(("TURN_LEFT", "TURN_RIGHT", "ATTACK")) == ["observe", "aim_at", "attack"]


def test_health_gathering_has_no_attack():
    assert names(("TURN_LEFT", "TURN_RIGHT", "MOVE_FORWARD")) == ["observe", "aim_at"]


def test_openai_tools_payload_shape():
    payload = to_openai(available_tools(("MOVE_LEFT", "MOVE_RIGHT", "ATTACK")))
    attack = next(t for t in payload if t["function"]["name"] == "attack")
    assert attack["type"] == "function"
    assert attack["function"]["parameters"]["required"] == ["burst"]
    assert attack["function"]["description"]


@pytest.mark.parametrize(
    ("tool", "args", "ok"),
    [
        ("aim_at", {"target_id": 0}, True),
        ("aim_at", {}, False),  # missing required
        ("aim_at", {"target_id": "0"}, False),  # wrong type
        ("aim_at", {"target_id": True}, False),  # bool is not an integer here
        ("aim_at", {"target_id": 0, "extra": 1}, False),  # unexpected argument
        ("attack", {"burst": 3}, True),
        ("attack", {"burst": 0}, False),  # below minimum
        ("attack", {"burst": 9}, False),  # above maximum
        ("observe", {}, True),
    ],
)
def test_validate_args(tool, args, ok):
    assert (validate_args(TOOLS[tool], args) is None) == ok

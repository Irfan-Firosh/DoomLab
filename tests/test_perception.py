import pytest

from doomlab.env.doom import RawLabel, RawState
from doomlab.env.perception import classify, describe, perceive, relative_position


def label(object_id, name, x, y, screen_x=150, width=20):
    return RawLabel(object_id=object_id, name=name, x=x, y=y, screen_x=screen_x, screen_width=width)


def state(labels, angle=0.0, px=0.0, py=0.0, **variables):
    return RawState(
        tic=14,
        labels=tuple(labels),
        variables={"POSITION_X": px, "POSITION_Y": py, "ANGLE": angle, **variables},
        finished=False,
    )


@pytest.mark.parametrize(
    ("angle", "target", "bearing"),
    [
        (0, (100, 0), 0.0),  # facing east, target east: dead ahead
        (0, (0, 100), 90.0),  # facing east, target north: 90 deg LEFT (Doom angles turn counter-clockwise)
        (0, (0, -100), -90.0),  # target south: 90 deg RIGHT
        (90, (0, 100), 0.0),  # facing north, target north: ahead
        (90, (100, 0), -90.0),  # facing north, target east: RIGHT
        (350, (100, 0), 10.0),  # angle wraps: 350 deg means target is 10 deg LEFT
    ],
)
def test_bearing_convention_positive_is_left(angle, target, bearing):
    rel = relative_position(0.0, 0.0, angle, *target)
    assert rel.bearing_deg == pytest.approx(bearing, abs=1e-6)
    assert rel.distance == pytest.approx(100.0)


def test_behind_is_plus_or_minus_180():
    rel = relative_position(0.0, 0.0, 0.0, -100.0, 0.0)
    assert abs(rel.bearing_deg) == pytest.approx(180.0)
    assert rel.ahead == pytest.approx(-100.0)


def test_ahead_and_offset_match_basic_probe():
    # Live probe of basic, seed 0: player (-384, 32) facing 0 deg, Cacodemon at (0, 52).
    rel = relative_position(-384.0, 32.0, 0.0, 0.0, 52.0)
    assert rel.ahead == pytest.approx(384.0)
    assert rel.offset == pytest.approx(20.0)  # positive = left
    assert rel.bearing_deg == pytest.approx(2.98, abs=0.01)


def test_perceive_drops_player_and_sorts_by_distance():
    obs = perceive(
        state(
            [
                label(1, "DoomPlayer", 0, 0),
                label(5, "DoomImp", 500, 0),
                label(3, "Medikit", 100, 0),
            ],
            AMMO2=26,
            HEALTH=80,
            KILLCOUNT=2,
        )
    )
    assert [f.name for f in obs.facts] == ["Medikit", "DoomImp"]
    assert (obs.ammo, obs.health, obs.kills) == (26, 80, 2)


def test_missing_variables_are_none_not_zero():
    obs = perceive(state([]))
    assert obs.health is None and obs.ammo is None and obs.kills is None


@pytest.mark.parametrize(
    ("name", "kind"),
    [("Cacodemon", "enemy"), ("MarineChainsawVzd", "enemy"), ("Medikit", "item"), ("SomethingNew", "other")],
)
def test_classify(name, kind):
    assert classify(name) == kind


def test_describe_is_readable_and_signed():
    obs = perceive(state([label(0, "Cacodemon", 384, 20)], AMMO2=50))
    text = describe(obs)
    assert "[id 0] Cacodemon (enemy)" in text
    assert "384u ahead" in text and "20u LEFT" in text
    assert "ammo 50" in text


def test_describe_with_nothing_visible():
    assert "nothing visible" in describe(perceive(state([])))

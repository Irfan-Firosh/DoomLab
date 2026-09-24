"""Perception on real label snapshots captured from vizDoom 1.3.1 (seed 0). Offline."""

import json
from pathlib import Path

import pytest

from doomlab.env.doom import RawLabel, RawState
from doomlab.env.perception import describe, perceive

FIXTURES = Path(__file__).parent / "fixtures"


def load(scenario):
    raw = json.loads((FIXTURES / f"{scenario}_seed0.json").read_text())
    return RawState(
        tic=raw["tic"],
        labels=tuple(RawLabel(**l) for l in raw["labels"]),
        variables=raw["variables"],
        finished=False,
    )


@pytest.mark.parametrize(
    ("scenario", "expected_line"),
    [
        ("basic", "[id 0] Cacodemon (enemy): 384u ahead, 20u LEFT"),
        ("defend_the_center", "[id 0] MarineChainsawVzd (enemy): 743u ahead, centred"),
        ("health_gathering", "[id 0] Medikit (item): 263u ahead, 193u LEFT"),
    ],
)
def test_real_snapshots_describe_as_expected(scenario, expected_line):
    text = describe(perceive(load(scenario)))
    assert expected_line in text
    assert "DoomPlayer" not in text  # the player's own label never reaches the LLM

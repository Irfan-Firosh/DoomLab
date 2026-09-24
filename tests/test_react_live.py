"""One real Qwen episode. Spends Purdue calls, so it only runs with DOOMLAB_LIVE=1."""

import os

import pytest

pytestmark = [pytest.mark.live, pytest.mark.skipif(os.environ.get("DOOMLAB_LIVE") != "1", reason="set DOOMLAB_LIVE=1")]


def test_qwen_wins_basic_seed_1():
    from doomlab.cli import main

    assert main(["run", "--variant", "react_single", "--scenario", "basic", "--seed", "1"]) == 0

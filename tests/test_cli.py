import pytest

from doomlab.cli import COMMANDS, build_parser, main


def test_cli_exposes_planned_commands():
    assert set(COMMANDS) == {"preflight", "run", "eval", "review", "improve", "replay", "report"}


def test_run_accepts_variant_scenario_seed():
    args = build_parser().parse_args(["run", "--variant", "react_single", "--scenario", "basic", "--seed", "0"])
    assert (args.variant, args.scenario, args.seed) == ("react_single", "basic", 0)


def test_unknown_variant_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--variant", "nope", "--scenario", "basic"])


def test_unimplemented_command_exits_2(capsys):
    assert main(["report"]) == 2
    assert "not implemented yet" in capsys.readouterr().err


@pytest.mark.parametrize(("text", "seeds"), [("3", [3]), ("0-4", [0, 1, 2, 3, 4]), ("0,2,5", [0, 2, 5]), ("0-2,7", [0, 1, 2, 7])])
def test_parse_seeds(text, seeds):
    from doomlab.cli import parse_seeds

    assert parse_seeds(text) == seeds


def test_run_scripted_prints_outcome(capsys):
    assert main(["run", "--variant", "scripted", "--scenario", "basic", "--seed", "0"]) == 0
    out = capsys.readouterr().out
    assert "attack" in out and "outcome: SUCCESS" in out


def test_run_random_variant_plays_a_real_episode(capsys):
    assert main(["run", "--variant", "random", "--scenario", "basic", "--seed", "0"]) == 0
    assert "outcome:" in capsys.readouterr().out

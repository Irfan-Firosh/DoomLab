"""Start a vizDoom scenario headless in synchronous PLAYER mode and read its state.

This module only *reads* the game. Pressing buttons (`make_action`) belongs to
`tools/executor.py`, which receives the underlying game via `DoomSession.game`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
import vizdoom as vzd

SCENARIOS = ("basic", "defend_the_center", "health_gathering", "health_gathering_supreme")

# Our own instrumentation, added on top of each scenario's built-in variables.
INSTRUMENT_VARIABLES = (
    vzd.GameVariable.POSITION_X,
    vzd.GameVariable.POSITION_Y,
    vzd.GameVariable.ANGLE,
    vzd.GameVariable.KILLCOUNT,
)


@dataclass(frozen=True)
class RawLabel:
    """One visible object from the labels buffer (world position + where it is drawn on screen)."""

    object_id: int
    name: str
    x: float
    y: float
    screen_x: int
    screen_width: int


@dataclass(frozen=True)
class RawState:
    tic: int
    labels: tuple[RawLabel, ...]
    variables: dict[str, float]
    finished: bool
    frame: np.ndarray | None = field(default=None, compare=False, repr=False)
    dead: bool = False


@dataclass(frozen=True)
class GameInfo:
    scenario: str
    seed: int
    buttons: tuple[str, ...]
    variables: tuple[str, ...]
    timeout_tics: int


class DoomSession:
    """One episode of one scenario. Use as `with DoomSession("basic", seed=0) as session:`."""

    def __init__(self, scenario: str, seed: int, *, visible: bool = False) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}; choose from {SCENARIOS}")
        game = vzd.DoomGame()
        game.load_config(os.path.join(vzd.scenarios_path, f"{scenario}.cfg"))
        game.set_window_visible(visible)
        game.set_mode(vzd.Mode.PLAYER)  # game waits for each action: LLM thinking time costs no game time
        game.set_screen_format(vzd.ScreenFormat.RGB24)  # frames as (height, width, 3) for GIFs
        game.set_labels_buffer_enabled(True)
        for variable in INSTRUMENT_VARIABLES:
            game.add_available_game_variable(variable)
        game.set_seed(seed)
        game.init()
        game.new_episode()
        self.game = game
        self.info = GameInfo(
            scenario=scenario,
            seed=seed,
            buttons=tuple(b.name for b in game.get_available_buttons()),
            variables=tuple(v.name for v in game.get_available_game_variables()),
            timeout_tics=game.get_episode_timeout(),
        )

    def __enter__(self) -> DoomSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.game.close()

    def read_state(self) -> RawState:
        game = self.game
        tic = game.get_episode_time()
        if game.is_episode_finished():
            # get_state() is None after the episode ends, but final variables stay readable (e.g. KILLCOUNT).
            final = {name: float(game.get_game_variable(getattr(vzd.GameVariable, name))) for name in self.info.variables}
            return RawState(tic=tic, labels=(), variables=final, finished=True, dead=game.is_player_dead())
        state = game.get_state()
        variables = dict(zip(self.info.variables, (float(v) for v in state.game_variables)))
        labels = tuple(
            RawLabel(
                object_id=int(label.object_id),
                name=label.object_name,
                x=float(label.object_position_x),
                y=float(label.object_position_y),
                screen_x=int(label.x),
                screen_width=int(label.width),
            )
            for label in state.labels
        )
        return RawState(
            tic=tic, labels=labels, variables=variables, finished=False, frame=state.screen_buffer, dead=game.is_player_dead()
        )

"""A tiny fake Doom for executor unit tests: player faces east at x=0; one target at x=400."""

from __future__ import annotations

from doomlab.env.doom import GameInfo, RawLabel, RawState

HIT_RADIUS = 31.0


class FakeGame:
    def __init__(self, session: "FakeSession") -> None:
        self._s = session
        self.actions: list[tuple[list[int], int]] = []

    def make_action(self, action: list[int], tics: int = 1) -> float:
        self.actions.append((list(action), tics))
        s = self._s
        pressed = {name for name, on in zip(s.info.buttons, action) if on}
        for _ in range(tics):
            if s.finished:
                break
            s.tic += 1
            push = ("MOVE_LEFT" in pressed) - ("MOVE_RIGHT" in pressed)
            if push:  # accelerate while held (measured ~0.5 u/tic^2, capped)
                s.vy = max(-s.max_speed, min(s.max_speed, s.vy + push * s.strafe_accel))
            else:  # glide: speed decays ~x0.906 per tic after release (measured)
                s.vy *= s.friction
            s.py += s.vy
            if "TURN_LEFT" in pressed:
                s.angle += s.turn_step
            if "TURN_RIGHT" in pressed:
                s.angle -= s.turn_step
            if "ATTACK" in pressed and s.ammo > 0:
                s.ammo -= 1
                if s.target_alive and abs(s.current_offset()) <= HIT_RADIUS:
                    s.target_alive, s.kills, s.finished = False, s.kills + 1, True
            if s.tic >= s.info.timeout_tics:
                s.finished = True
        return 0.0

    def is_episode_finished(self) -> bool:
        return self._s.finished

    def get_episode_time(self) -> int:
        return self._s.tic


class FakeSession:
    def __init__(self, buttons=("MOVE_LEFT", "MOVE_RIGHT", "ATTACK"), target_y=20.0, ammo=50, timeout=300):
        self.info = GameInfo("fake", 0, tuple(buttons), ("AMMO2", "POSITION_X", "POSITION_Y", "ANGLE", "KILLCOUNT"), timeout)
        self.py, self.angle, self.tic = 0.0, 0.0, 0
        self.target_y, self.ammo, self.kills = target_y, ammo, 0
        self.target_alive, self.finished = True, False
        self.vy, self.strafe_accel, self.max_speed, self.friction = 0.0, 0.5, 8.0, 0.906
        self.turn_step = 1.76  # degrees per tic, no momentum (measured)
        self.game = FakeGame(self)

    def current_offset(self) -> float:
        from doomlab.env.perception import relative_position

        return relative_position(0.0, self.py, self.angle, 400.0, self.target_y).offset

    def read_state(self) -> RawState:
        variables = {"AMMO2": float(self.ammo), "POSITION_X": 0.0, "POSITION_Y": self.py, "ANGLE": self.angle, "KILLCOUNT": float(self.kills)}
        if self.finished:
            return RawState(tic=self.tic, labels=(), variables=variables, finished=True)
        labels = (RawLabel(0, "Cacodemon", 400.0, self.target_y, 150, 20),) if self.target_alive else ()
        return RawState(tic=self.tic, labels=labels, variables=variables, finished=False)

"""A tiny fake Doom for unit tests, with the movement physics measured in the real game.

Player starts at (0, 0) facing east. One target (enemy by default) at (400, target_y).
Optional items can be picked up by walking over them (only below full health, like Doom).
"""

from __future__ import annotations

import math

from doomlab.env.doom import GameInfo, RawLabel, RawState

HIT_RADIUS = 31.0
PICKUP_RADIUS = 20.0
MEDIKIT_HEAL = 25.0


class FakeGame:
    def __init__(self, session: "FakeSession") -> None:
        self._s = session
        self.actions: list[tuple[list[int], int]] = []

    def make_action(self, action: list[int], tics: int = 1) -> float:
        self.actions.append((list(action), tics))
        pressed = {name for name, on in zip(self._s.info.buttons, action) if on}
        for _ in range(tics):
            if self._s.finished:
                break
            self._s.tick(pressed)
        return 0.0

    def is_episode_finished(self) -> bool:
        return self._s.finished

    def is_player_dead(self) -> bool:
        return self._s.dead

    def get_episode_time(self) -> int:
        return self._s.tic


class FakeSession:
    def __init__(
        self,
        buttons=("MOVE_LEFT", "MOVE_RIGHT", "ATTACK"),
        target_y=20.0,
        ammo=50,
        timeout=300,
        target_name="Cacodemon",
        items=(),
        health=None,
        drain=0.0,
        wall_x=None,
    ):
        variables = ("AMMO2", "HEALTH", "POSITION_X", "POSITION_Y", "ANGLE", "KILLCOUNT")
        self.info = GameInfo("fake", 0, tuple(buttons), variables, timeout)
        self.px, self.py, self.angle, self.tic = 0.0, 0.0, 0.0, 0
        self.target_y, self.target_name, self.ammo, self.kills = target_y, target_name, ammo, 0
        self.target_alive = target_y is not None
        self.items = {i: (x, y) for i, (x, y) in enumerate(items, start=10)}
        self.health, self.drain, self.wall_x = health, drain, wall_x
        self.finished = self.dead = False
        # measured physics: strafing and walking accelerate ~0.5 u/tic^2 and glide x0.906 per tic; turning has no momentum
        self.vy = self.vf = 0.0
        self.accel, self.max_speed, self.friction, self.turn_step = 0.5, 8.0, 0.906, 1.76
        self.game = FakeGame(self)

    # ------------------------------------------------------------ simulation

    def tick(self, pressed: set[str]) -> None:
        self.tic += 1
        push = ("MOVE_LEFT" in pressed) - ("MOVE_RIGHT" in pressed)
        self.vy = self._speed(self.vy, push)
        self.py += self.vy
        self.angle += self.turn_step * (("TURN_LEFT" in pressed) - ("TURN_RIGHT" in pressed))
        self.vf = self._speed(self.vf, int("MOVE_FORWARD" in pressed))
        rad = math.radians(self.angle)
        self.px += self.vf * math.cos(rad)
        self.py += self.vf * math.sin(rad)
        if self.wall_x is not None and self.px > self.wall_x:
            self.px, self.vf = self.wall_x, 0.0
        if "ATTACK" in pressed and self.ammo > 0:
            self.ammo -= 1
            if self.target_alive and abs(self.current_offset()) <= HIT_RADIUS:
                self.target_alive, self.kills = False, self.kills + 1
                if self.info.timeout_tics == 300 and self.health is None:  # basic-style: the kill ends the episode
                    self.finished = True
        self._pickups()
        if self.health is not None:
            self.health -= self.drain
            if self.health <= 0:
                self.dead = self.finished = True
        if self.tic >= self.info.timeout_tics:
            self.finished = True

    def _speed(self, v: float, push: int) -> float:
        return max(-self.max_speed, min(self.max_speed, v + push * self.accel)) if push else v * self.friction

    def _pickups(self) -> None:
        if self.health is None or self.health >= 100:
            return
        for item_id, (x, y) in list(self.items.items()):
            if math.dist((self.px, self.py), (x, y)) <= PICKUP_RADIUS:
                self.health = min(100.0, self.health + MEDIKIT_HEAL)
                del self.items[item_id]

    # --------------------------------------------------------------- reading

    def current_offset(self) -> float:
        from doomlab.env.perception import relative_position

        return relative_position(self.px, self.py, self.angle, 400.0, self.target_y).offset

    def read_state(self) -> RawState:
        variables = {
            "AMMO2": float(self.ammo), "POSITION_X": self.px, "POSITION_Y": self.py,
            "ANGLE": self.angle % 360.0, "KILLCOUNT": float(self.kills),
        }
        if self.health is not None:
            variables["HEALTH"] = self.health
        if self.finished:
            return RawState(tic=self.tic, labels=(), variables=variables, finished=True, dead=self.dead)
        labels = [RawLabel(0, self.target_name, 400.0, self.target_y, 150, 20)] if self.target_alive else []
        labels += [RawLabel(i, "Medikit", x, y, 150, 10) for i, (x, y) in self.items.items()]
        return RawState(tic=self.tic, labels=tuple(labels), variables=variables, finished=False, dead=self.dead)

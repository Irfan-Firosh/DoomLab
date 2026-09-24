"""Validate a tool call, then turn it into button presses. The ONLY module that calls `make_action`.

Aim thresholds come from a calibration run on `basic` (data/calibration_basic_aim.json):
single pistol shots killed 81/81 times at |offset| <= 30u, and the edge sits near 31u
(the Cacodemon's radius). We allow attacks at <= 15u and aim for <= 6u, a 2x safety margin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from doomlab.env.doom import GameInfo, RawState
from doomlab.env.perception import Fact, Observation, perceive
from doomlab.tools.registry import STRAFE, TOOLS, available_tools, validate_args

IN_CONE_OFFSET = 15.0  # |sideways offset| at which an attack is allowed
AIM_STOP_OFFSET = 6.0  # aim_at is done once the target is this close to centre and we are not sliding
STILL_SPEED = 0.3  # units/tic below which the player counts as stopped
# Strafing slides like ice: after release, speed decays ~x0.906 per tic (measured), so the player keeps
# travelling about 0.906 / (1 - 0.906) ~= 9.6x its current speed. Turning stops dead (measured), so 0.
STRAFE_GLIDE = 9.6
MAX_AIM_TICS = 90
SHOT_RECOVERY_TICS = 14  # pistol refire time; also long enough for a kill to register


class Game(Protocol):
    def make_action(self, action: list[int], tics: int = 1) -> float: ...
    def is_episode_finished(self) -> bool: ...
    def get_episode_time(self) -> int: ...


class Session(Protocol):
    info: GameInfo
    game: Game

    def read_state(self) -> RawState: ...


@dataclass(frozen=True)
class ToolResult:
    tool: str
    args: dict[str, Any]
    ok: bool
    code: str | None  # rejection code when not ok
    message: str
    buttons: tuple[tuple[int, ...], ...]  # one entry per tic actually played
    tics_used: int
    before: Observation
    after: Observation
    episode_finished: bool

    @property
    def kills_gained(self) -> int:
        return int((self.after.kills or 0) - (self.before.kills or 0))


def in_cone(fact: Fact) -> bool:
    return fact.kind == "enemy" and fact.ahead > 0 and abs(fact.offset) <= IN_CONE_OFFSET


class Executor:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._buttons = session.info.buttons
        self.tools = available_tools(self._buttons)
        self._pressed: list[tuple[int, ...]] = []

    # ----------------------------------------------------------------- public

    def observe(self) -> Observation:
        return perceive(self._session.read_state())

    def press_recorded(self, action: tuple[int, ...]) -> None:
        """Replay one recorded tic exactly as traced. Used by replay; skips validation by design."""
        if not self._session.game.is_episode_finished():
            self._session.game.make_action(list(action), 1)

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        before = self.observe()
        rejection = self._validate(name, args, before)
        if rejection:
            return self._result(name, args, before, before, ok=False, code=rejection[0], message=rejection[1])

        self._pressed = []
        message = getattr(self, f"_do_{name}")(args)
        after = self.observe()
        # Count pressed tics directly: vizDoom resets its episode clock once the episode ends.
        return self._result(name, args, before, after, ok=True, code=None, message=message, tics=len(self._pressed))

    # ------------------------------------------------------------- validation

    def _validate(self, name: str, args: dict[str, Any], obs: Observation) -> tuple[str, str] | None:
        if self._session.game.is_episode_finished():
            return "EPISODE_FINISHED", "the episode is over; no more actions"
        spec = TOOLS.get(name)
        if spec is None:
            return "UNKNOWN_TOOL", f"no tool named {name!r}; available: {[t.name for t in self.tools]}"
        if spec not in self.tools:
            return "UNAVAILABLE_TOOL", f"{name} is not possible in this scenario"
        problem = validate_args(spec, args)
        if problem:
            return "BAD_ARGS", problem
        if name == "aim_at" and not any(f.id == args["target_id"] for f in obs.facts):
            return "UNKNOWN_TARGET", f"target {args['target_id']} is not visible"
        if name == "attack":
            if not obs.ammo:
                return "NO_AMMO", "no ammunition left"
            if not any(in_cone(f) for f in obs.facts):
                return "NO_ENEMY_IN_CONE", f"no enemy within {IN_CONE_OFFSET:g}u of the crosshair; aim first"
        return None

    # --------------------------------------------------------------- actions

    def _do_observe(self, args: dict[str, Any]) -> str:
        return "looked around"

    def _do_aim_at(self, args: dict[str, Any]) -> str:
        """Steer on the *predicted* stopping point so momentum doesn't carry us past the target."""
        target_id = args["target_id"]
        strafing = STRAFE <= set(self._buttons)
        left, right = ("MOVE_LEFT", "MOVE_RIGHT") if strafing else ("TURN_LEFT", "TURN_RIGHT")
        glide = STRAFE_GLIDE if strafing else 0.0
        previous: float | None = None
        for _ in range(MAX_AIM_TICS):
            target = self._find(target_id)
            if target is None:
                return "target lost from view"
            velocity = 0.0 if previous is None else target.offset - previous
            previous = target.offset
            if abs(target.offset) <= AIM_STOP_OFFSET and abs(velocity) < STILL_SPEED:
                return "target centred"
            predicted = target.offset + velocity * glide
            if abs(predicted) <= AIM_STOP_OFFSET:
                self._press(set(), 1)  # coast: momentum alone will bring us in
            else:
                self._press({left} if predicted > 0 else {right}, 1)  # accelerate, or brake if overshooting
        return f"stopped after {MAX_AIM_TICS} tics without centring"

    def _do_attack(self, args: dict[str, Any]) -> str:
        shots = 0
        for _ in range(args["burst"]):
            if self._session.game.is_episode_finished():
                break
            self._press({"ATTACK"}, 1)
            shots += 1
            for _ in range(SHOT_RECOVERY_TICS - 1):
                if self._session.game.is_episode_finished():
                    break
                self._press(set(), 1)
        return f"fired {shots} shot(s)"

    # --------------------------------------------------------------- helpers

    def _find(self, target_id: int) -> Fact | None:
        return next((f for f in self.observe().facts if f.id == target_id), None)

    def _press(self, names: set[str], tics: int) -> None:
        action = [1 if b in names else 0 for b in self._buttons]
        for _ in range(tics):
            if self._session.game.is_episode_finished():
                return
            self._session.game.make_action(action, 1)
            self._pressed.append(tuple(action))

    def _result(self, name, args, before, after, *, ok, code, message, tics=0) -> ToolResult:
        return ToolResult(
            tool=name, args=dict(args), ok=ok, code=code, message=message,
            buttons=tuple(self._pressed) if ok else (), tics_used=tics,
            before=before, after=after, episode_finished=self._session.game.is_episode_finished(),
        )

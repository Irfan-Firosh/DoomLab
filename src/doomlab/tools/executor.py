"""Validate a tool call, then turn it into button presses. The ONLY module that calls `make_action`.

Aim cones come from calibration runs (data/calibration_*_aim.json): single pistol shots at a range
of sideways offsets. We allow attacks at about half the measured hit edge:
- basic, Cacodemon: 81/81 hits within 30u, edge ~31u (its radius)       -> cone 15u
- defend_the_center, Demon: hits out to ~36-42u                          -> cone 15u
- defend_the_center, MarineChainsawVzd: 88% within 18u, ~0% beyond 24u   -> cone 9u
Unknown enemies get the cautious 9u.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

from doomlab.env.doom import GameInfo, RawState
from doomlab.env.perception import Fact, Observation, perceive
from doomlab.tools.registry import STRAFE, TOOLS, ToolSpec, available_tools, validate_args

CONE_BY_ENEMY = {"Cacodemon": 15.0, "Demon": 15.0, "MarineChainsawVzd": 9.0}
DEFAULT_CONE = 9.0
AIM_STOP_OFFSET = 6.0  # aim_at is done once the target is this close to centre and we are not sliding
STILL_SPEED = 0.3  # units/tic below which the player counts as stopped
# Strafing and walking slide like ice: after release, speed decays ~x0.906 per tic (measured), so the player
# keeps travelling about 0.906 / (1 - 0.906) ~= 9.6x its current speed. Turning stops dead (measured), so 0.
STRAFE_GLIDE = 9.6
MAX_AIM_TICS = 90
MAX_TURN_TICS = 120
TURN_TOLERANCE_DEG = 1.0
MAX_WALK_TICS = 150
WALK_FACING_DEG = 10.0  # walk forward only when the item is within this bearing; otherwise turn first
STUCK_TICS = 8  # forward presses with no movement before go_to reports "no effect"
REACHED_DISTANCE = 40.0  # an item that vanishes this close was reached (walked over)
ON_ITEM_DISTANCE = 20.0  # standing on it: if health did not rise, it was not picked up (Doom skips pickups at full health)
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


def cone_for(enemy_name: str) -> float:
    return CONE_BY_ENEMY.get(enemy_name, DEFAULT_CONE)


def in_cone(fact: Fact) -> bool:
    return fact.kind == "enemy" and fact.ahead > 0 and abs(fact.offset) <= cone_for(fact.name)


def _angle_diff(target: float, current: float) -> float:
    """Signed smallest difference target - current, in (-180, 180]."""
    return (target - current + 180.0) % 360.0 - 180.0


class Executor:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._buttons = session.info.buttons
        self.tools = available_tools(self._buttons)
        self._pressed: list[tuple[int, ...]] = []
        self._last_look_tic: int | None = None  # tic of the last `observe` call

    # ----------------------------------------------------------------- public

    def observe(self) -> Observation:
        return perceive(self._session.read_state())

    def press_recorded(self, action: tuple[int, ...]) -> None:
        """Replay one recorded tic exactly as traced. Used by replay; skips validation by design."""
        if not self._session.game.is_episode_finished():
            self._session.game.make_action(list(action), 1)

    def play_out(self) -> ToolResult:
        """Stand still until the episode ends (time limit or death), as a player who stopped acting would."""
        before = self.observe()
        self._pressed = []
        limit = self._session.info.timeout_tics
        while not self._session.game.is_episode_finished() and len(self._pressed) < limit:
            self._press(set(), 1)
        message = "stood still until the episode ended"
        return self._result("wait_until_end", {}, before, self.observe(), ok=True, code=None, message=message,
                            tics=len(self._pressed))

    def execute(self, name: str, args: dict[str, Any], *, allowed: tuple[ToolSpec, ...] | None = None) -> ToolResult:
        """Run one call. `allowed` narrows the menu to a specialist's role (commander topology)."""
        before = self.observe()
        rejection = self._validate(name, args, before, allowed)
        if rejection:
            return self._result(name, args, before, before, ok=False, code=rejection[0], message=rejection[1])
        self._pressed = []
        message = getattr(self, f"_do_{name}")(args, before)
        after = self.observe()
        # Count pressed tics directly: vizDoom resets its episode clock once the episode ends.
        return self._result(name, args, before, after, ok=True, code=None, message=message, tics=len(self._pressed))

    # ------------------------------------------------------------- validation

    def _validate(
        self, name: str, args: dict[str, Any], obs: Observation, allowed: tuple[ToolSpec, ...] | None
    ) -> tuple[str, str] | None:
        if self._session.game.is_episode_finished():
            return "EPISODE_FINISHED", "the episode is over; no more actions"
        spec = TOOLS.get(name)
        if spec is None:
            return "UNKNOWN_TOOL", f"no tool named {name!r}; available: {[t.name for t in self.tools]}"
        if allowed is not None and spec not in allowed and spec in self.tools:
            return "OUT_OF_ROLE", f"{name} belongs to the other specialist; yours: {[t.name for t in allowed]}"
        if spec not in (allowed if allowed is not None else self.tools):
            return "UNAVAILABLE_TOOL", f"{name} is not possible in this scenario"
        problem = validate_args(spec, args)
        if problem:
            return "BAD_ARGS", problem
        target = next((f for f in obs.facts if f.id == args.get("target_id")), None)
        if name in ("aim_at", "go_to") and target is None:
            return "UNKNOWN_TARGET", f"target {args['target_id']} is not visible"
        if name == "go_to" and target.kind != "item":
            return "NOT_AN_ITEM", f"go_to only walks to items; {target.name} is a {target.kind}"
        if name == "observe" and obs.tic == self._last_look_tic:
            return "NOTHING_CHANGED", (
                "the game is paused between your calls, so looking again shows the same thing; act instead (e.g. turn)"
            )
        if name == "attack":
            if not obs.ammo:
                return "NO_AMMO", "no ammunition left"
            if not any(in_cone(f) for f in obs.facts):
                return "NO_ENEMY_IN_CONE", "no enemy inside its aim cone; aim first"
        return None

    # --------------------------------------------------------------- actions

    def _do_observe(self, args: dict[str, Any], before: Observation) -> str:
        self._last_look_tic = before.tic
        return "looked around"

    def _do_report_back(self, args: dict[str, Any], before: Observation) -> str:
        return f"handed back to the commander: {args['reason']}"

    def _do_aim_at(self, args: dict[str, Any], before: Observation) -> str:
        """Steer on the *predicted* stopping point so momentum doesn't carry us past the target."""
        target_id = args["target_id"]
        strafing = STRAFE <= set(self._buttons)
        left, right = ("MOVE_LEFT", "MOVE_RIGHT") if strafing else ("TURN_LEFT", "TURN_RIGHT")
        glide = STRAFE_GLIDE if strafing else 0.0
        previous: float | None = None
        crossings = 0
        for _ in range(MAX_AIM_TICS):
            target = self._find(target_id)
            if target is None:
                return "target lost from view"
            velocity = 0.0 if previous is None else target.offset - previous
            crossed = previous is not None and (previous > 0) != (target.offset > 0)
            crossings += crossed
            previous = target.offset
            if abs(target.offset) <= AIM_STOP_OFFSET and abs(velocity) < STILL_SPEED:
                return "target centred"
            if not strafing and crossed and in_cone(target):
                # one turn tic jumps past the centre at long range: this is as close as turning allows
                return "target centred as closely as turning allows"
            if not strafing and crossings >= 2:
                return f"cannot centre more precisely by turning at this range (offset {target.offset:+.0f}u)"
            predicted = target.offset + velocity * glide
            if abs(predicted) <= AIM_STOP_OFFSET:
                self._press(set(), 1)  # coast: momentum alone will bring us in
            else:
                self._press({left} if predicted > 0 else {right}, 1)  # accelerate, or brake if overshooting
        return f"stopped after {MAX_AIM_TICS} tics without centring"

    def _do_attack(self, args: dict[str, Any], before: Observation) -> str:
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

    def _do_turn(self, args: dict[str, Any], before: Observation) -> str:
        """Turn until the measured angle has changed by `degrees` (turn speed is not constant)."""
        start = self._angle()
        goal = start + args["degrees"]
        for _ in range(MAX_TURN_TICS):
            remaining = _angle_diff(goal, self._angle())
            if abs(remaining) <= TURN_TOLERANCE_DEG or self._session.game.is_episode_finished():
                break
            self._press({"TURN_LEFT"} if remaining > 0 else {"TURN_RIGHT"}, 1)
            if (remaining > 0) != (_angle_diff(goal, self._angle()) > 0):
                break  # overshot by less than one tic of turning: close enough
        turned = _angle_diff(self._angle(), start)
        return f"turned {turned:+.0f} degrees; now visible: {len(self.observe().facts)} object(s)"

    def _do_go_to(self, args: dict[str, Any], before: Observation) -> str:
        """Face the item, walk forward, repeat; judge a pickup by health actually rising."""
        target_id = args["target_id"]
        last_seen: Fact | None = None
        still = 0
        position = self._position()
        for _ in range(MAX_WALK_TICS):
            if self._session.game.is_episode_finished():
                return "episode ended while walking"
            target = self._find(target_id)
            if target is None:
                return self._walk_ending(before, last_seen)
            last_seen = target
            if target.distance <= ON_ITEM_DISTANCE:
                return self._walk_ending(before, last_seen)
            if abs(target.bearing_deg) > WALK_FACING_DEG:
                self._press({"TURN_LEFT"} if target.bearing_deg > 0 else {"TURN_RIGHT"}, 1)
                continue
            self._press({"MOVE_FORWARD"}, 1)
            now = self._position()
            still = still + 1 if math.dist(now, position) < 0.1 else 0
            position = now
            if still >= STUCK_TICS:
                return f"no effect: blocked after walking toward {target.name}"
        return f"stopped after {MAX_WALK_TICS} tics without reaching the item"

    def _walk_ending(self, before: Observation, last_seen: Fact | None) -> str:
        health_before, health_now = before.health or 0.0, self.observe().health or 0.0
        if health_now > health_before:
            return f"picked up the item: health {health_before:g} -> {health_now:g}"
        if last_seen is not None and last_seen.distance <= REACHED_DISTANCE:
            return "reached the item but it was not picked up (health already full)"
        return "item lost from view"

    # --------------------------------------------------------------- helpers

    def _find(self, target_id: int) -> Fact | None:
        return next((f for f in self.observe().facts if f.id == target_id), None)

    def _angle(self) -> float:
        return self._session.read_state().variables.get("ANGLE", 0.0)

    def _position(self) -> tuple[float, float]:
        v = self._session.read_state().variables
        return v.get("POSITION_X", 0.0), v.get("POSITION_Y", 0.0)

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

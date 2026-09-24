"""Turn raw vizDoom state into facts the agent can read. Pure functions: no game access.

Conventions (tested): Doom angles are degrees, 0 = east, increasing counter-clockwise.
Bearing is relative to where the player faces, in (-180, 180], positive = LEFT.
`ahead` is distance along the facing direction; `offset` is sideways distance, positive = LEFT.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from doomlab.env.doom import RawState

PLAYER_LABEL = "DoomPlayer"

ENEMIES = frozenset(
    {
        "Cacodemon", "DoomImp", "Zombieman", "ShotgunGuy", "ChaingunGuy", "Demon", "Spectre",
        "LostSoul", "HellKnight", "BaronOfHell", "Revenant", "Fatso", "Arachnotron",
        "MarineChainsawVzd", "MarineShotgunVzd", "MarinePistolVzd",
    }
)
ITEMS = frozenset(
    {"Medikit", "Stimpack", "HealthBonus", "ArmorBonus", "GreenArmor", "BlueArmor", "Clip", "ClipBox", "Shell", "ShellBox"}
)
CENTRED_OFFSET = 4.0  # units; below this a fact reads as CENTER rather than LEFT/RIGHT


@dataclass(frozen=True)
class RelativePosition:
    bearing_deg: float
    ahead: float
    offset: float
    distance: float


@dataclass(frozen=True)
class Fact:
    id: int
    name: str
    kind: str
    bearing_deg: float
    ahead: float
    offset: float
    distance: float

    @property
    def side(self) -> str:
        if abs(self.offset) < CENTRED_OFFSET:
            return "CENTER"
        return "LEFT" if self.offset > 0 else "RIGHT"


@dataclass(frozen=True)
class Observation:
    tic: int
    facts: tuple[Fact, ...]
    health: float | None
    ammo: float | None
    kills: float | None


def classify(name: str) -> str:
    if name in ENEMIES:
        return "enemy"
    if name in ITEMS:
        return "item"
    return "other"


def relative_position(px: float, py: float, angle_deg: float, ox: float, oy: float) -> RelativePosition:
    dx, dy = ox - px, oy - py
    distance = math.hypot(dx, dy)
    bearing = math.degrees(math.atan2(dy, dx)) - angle_deg
    bearing = (bearing + 180.0) % 360.0 - 180.0  # normalise to [-180, 180)
    rad = math.radians(bearing)
    return RelativePosition(
        bearing_deg=bearing,
        ahead=distance * math.cos(rad),
        offset=distance * math.sin(rad),
        distance=distance,
    )


def perceive(state: RawState) -> Observation:
    v = state.variables
    px, py, angle = v.get("POSITION_X", 0.0), v.get("POSITION_Y", 0.0), v.get("ANGLE", 0.0)
    facts = []
    for label in state.labels:
        if label.name == PLAYER_LABEL:
            continue
        rel = relative_position(px, py, angle, label.x, label.y)
        facts.append(
            Fact(
                id=label.object_id,
                name=label.name,
                kind=classify(label.name),
                bearing_deg=rel.bearing_deg,
                ahead=rel.ahead,
                offset=rel.offset,
                distance=rel.distance,
            )
        )
    return Observation(
        tic=state.tic,
        facts=tuple(sorted(facts, key=lambda f: (f.distance, f.id))),
        health=v.get("HEALTH"),
        ammo=v.get("AMMO2"),
        kills=v.get("KILLCOUNT"),
    )


def describe(obs: Observation) -> str:
    """The text the LLM sees. Only visible objects; numbers rounded for readability."""
    status = [f"tic {obs.tic}"]
    for name, value in (("health", obs.health), ("ammo", obs.ammo), ("kills", obs.kills)):
        if value is not None:
            status.append(f"{name} {value:g}")
    lines = [", ".join(status)]
    if not obs.facts:
        lines.append("Visible: nothing visible")
    for f in obs.facts:
        side = "centred" if f.side == "CENTER" else f"{abs(f.offset):.0f}u {f.side}"
        lines.append(
            f"[id {f.id}] {f.name} ({f.kind}): {f.ahead:.0f}u ahead, {side}, "
            f"bearing {f.bearing_deg:+.0f}°, distance {f.distance:.0f}u"
        )
    return "\n".join(lines)

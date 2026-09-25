"""The tools the agent may call. One definition feeds the LLM payload, argument checks and availability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STRAFE = frozenset({"MOVE_LEFT", "MOVE_RIGHT"})
TURN = frozenset({"TURN_LEFT", "TURN_RIGHT"})
WALK = frozenset({"TURN_LEFT", "TURN_RIGHT", "MOVE_FORWARD"})


@dataclass(frozen=True)
class ToolCall:
    """A request to run one tool: produced by any agent (scripted rules or an LLM)."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object, as sent to the LLM
    needs_any: tuple[frozenset[str], ...] = ()  # usable if the scenario has ANY one of these button sets

    def available(self, buttons: tuple[str, ...] | frozenset[str]) -> bool:
        have = set(buttons)
        return not self.needs_any or any(required <= have for required in self.needs_any)


def _object(properties: dict[str, Any] | None = None, required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": list(required),
        "additionalProperties": False,
    }


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="observe",
            description=(
                "Look again. Uses no game time, and the game is paused between your calls, "
                "so the facts you were just given are already current."
            ),
            parameters=_object(),
        ),
        ToolSpec(
            name="aim_at",
            description=(
                "Line up a visible target (by its id) in the crosshair by turning or strafing. "
                "Stops when the target is centred, lost from view, or a time cap is reached."
            ),
            parameters=_object({"target_id": {"type": "integer", "description": "id from the visible list"}}, ("target_id",)),
            needs_any=(STRAFE, TURN),
        ),
        ToolSpec(
            name="attack",
            description=(
                "Fire the weapon `burst` times. One hit usually kills an enemy. Each shot uses one bullet and "
                "about 14 tics during which you stand still. Only allowed when an enemy is in the aim cone."
            ),
            parameters=_object({"burst": {"type": "integer", "minimum": 1, "maximum": 5}}, ("burst",)),
            needs_any=(frozenset({"ATTACK"}),),
        ),
        ToolSpec(
            name="turn",
            description="Turn in place to look around: positive degrees = left, negative = right. Use it when nothing useful is visible.",
            parameters=_object(
                {"degrees": {"type": "integer", "minimum": -180, "maximum": 180, "not": {"const": 0}}}, ("degrees",)
            ),
            needs_any=(TURN,),
        ),
        ToolSpec(
            name="go_to",
            description=(
                "Walk to a visible item (by its id), e.g. a medikit, to pick it up. "
                "Stops when it is picked up, reached, lost from view, or you are blocked."
            ),
            parameters=_object({"target_id": {"type": "integer", "description": "id of a visible item"}}, ("target_id",)),
            needs_any=(WALK,),
        ),
    )
}


def available_tools(buttons: tuple[str, ...]) -> tuple[ToolSpec, ...]:
    return tuple(spec for spec in TOOLS.values() if spec.available(buttons))


def to_openai(specs: tuple[ToolSpec, ...]) -> list[dict[str, Any]]:
    """The `tools` payload for a native tool-calling request."""
    return [
        {"type": "function", "function": {"name": s.name, "description": s.description, "parameters": s.parameters}}
        for s in specs
    ]


def validate_args(spec: ToolSpec, args: dict[str, Any]) -> str | None:
    """Check args against the spec's schema. Returns an error message, or None when valid."""
    if not isinstance(args, dict):
        return "arguments must be an object"
    properties = spec.parameters["properties"]
    unexpected = sorted(set(args) - set(properties))
    if unexpected:
        return f"unexpected argument(s): {', '.join(unexpected)}"
    for name in spec.parameters["required"]:
        if name not in args:
            return f"missing required argument: {name}"
    for name, value in args.items():
        rule = properties[name]
        if rule.get("type") == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            return f"{name} must be an integer"
        if rule.get("type") == "string" and not isinstance(value, str):
            return f"{name} must be a string"
        if "enum" in rule and value not in rule["enum"]:
            return f"{name} must be one of {rule['enum']}"
        if "minimum" in rule and value < rule["minimum"]:
            return f"{name} must be >= {rule['minimum']}"
        if "maximum" in rule and value > rule["maximum"]:
            return f"{name} must be <= {rule['maximum']}"
        if "not" in rule and value == rule["not"].get("const"):
            return f"{name} must not be {rule['not']['const']}"
    return None

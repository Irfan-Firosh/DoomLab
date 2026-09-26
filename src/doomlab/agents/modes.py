"""The commander topology's two jobs, and which tools each specialist may use."""

from __future__ import annotations

from doomlab.tools.registry import ToolSpec

FIGHT, NAVIGATE = "fight", "navigate"
ROLE_TOOL_NAMES = {FIGHT: ("observe", "aim_at", "attack"), NAVIGATE: ("observe", "turn", "go_to")}


def available_modes(tools: tuple[ToolSpec, ...]) -> tuple[str, ...]:
    """Modes worth choosing in this scenario: fight needs a weapon; navigate needs a way to turn or walk."""
    names = {t.name for t in tools}
    return tuple(m for m, possible in ((FIGHT, "attack" in names), (NAVIGATE, bool(names & {"turn", "go_to"}))) if possible)


def role_tools(mode: str, tools: tuple[ToolSpec, ...]) -> tuple[ToolSpec, ...]:
    """The specialist's menu: its role's tools that this scenario supports."""
    return tuple(t for t in tools if t.name in ROLE_TOOL_NAMES[mode])

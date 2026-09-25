"""The four players, built one way for both `doomlab run` and `doomlab eval`."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack

from doomlab.agents.base import Agent

VARIANTS = ("random", "scripted", "react_single", "commander")  # also the order an eval plays them: free ones first
LLM_VARIANTS = frozenset({"react_single", "commander"})

AgentMaker = Callable[[str, str, int], Agent]  # (variant, scenario, seed) -> a fresh agent for one episode


async def open_agent_maker(stack: AsyncExitStack, variants: tuple[str, ...]) -> AgentMaker:
    """Opens the LLM client only when an LLM variant is requested, so free runs need no key or network."""
    from doomlab.agents.random_agent import RandomAgent
    from doomlab.agents.scripted import ScriptedAgent

    unknown = sorted(set(variants) - set(VARIANTS))
    if unknown:
        raise ValueError(f"unknown variant(s) {unknown}; choose from {list(VARIANTS)}")
    llm_maker = await _open_llm(stack) if LLM_VARIANTS & set(variants) else None

    def make(variant: str, scenario: str, seed: int) -> Agent:
        if variant == "random":
            return RandomAgent(seed)
        if variant == "scripted":
            return ScriptedAgent()
        return llm_maker(variant, scenario)

    return make


async def _open_llm(stack: AsyncExitStack) -> Callable[[str, str], Agent]:
    from doomlab.agents.commander import CommanderTeam
    from doomlab.agents.react import ReactAgent
    from doomlab.config import RUNS_DIR, load_settings
    from doomlab.llm.budget import Budget
    from doomlab.llm.client import RCACClient
    from doomlab.llm.preflight import load_frozen_decoding

    settings = load_settings()
    decoding = load_frozen_decoding(RUNS_DIR / "preflight.json", settings.model_id)
    client = await stack.enter_async_context(RCACClient(settings))

    def make(variant: str, scenario: str) -> Agent:
        agent_class = CommanderTeam if variant == "commander" else ReactAgent
        return agent_class(client, scenario=scenario, decoding=decoding, budget=Budget())  # a fresh budget per episode

    return make

"""The four players, built one way for both `doomlab run` and `doomlab eval`."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import Any

from doomlab.agents.base import Agent
from doomlab.policy import Policy, load_policy
from doomlab.policy_registry import active_policy_path

VARIANTS = ("random", "scripted", "react_single", "commander")  # also the order an eval plays them: free ones first
LLM_VARIANTS = frozenset({"react_single", "commander"})

AgentMaker = Callable[[str, str, int], Agent]  # (variant, scenario, seed) -> a fresh agent for one episode


async def open_agent_maker(stack: AsyncExitStack, variants: tuple[str, ...], policy: Policy | None = None) -> AgentMaker:
    """Opens the LLM client only when an LLM variant is requested, so free runs need no key or network."""
    from doomlab.agents.random_agent import RandomAgent
    from doomlab.agents.scripted import ScriptedAgent

    unknown = sorted(set(variants) - set(VARIANTS))
    if unknown:
        raise ValueError(f"unknown variant(s) {unknown}; choose from {list(VARIANTS)}")
    policy = policy or load_policy(active_policy_path())
    llm_maker = await open_llm_maker(stack, policy) if LLM_VARIANTS & set(variants) else None

    def make(variant: str, scenario: str, seed: int) -> Agent:
        if variant == "random":
            return RandomAgent(seed)
        if variant == "scripted":
            return ScriptedAgent()
        return llm_maker(variant, scenario)

    return make


async def open_llm_maker(stack: AsyncExitStack, policy: Policy) -> Callable[[str, str], Agent]:
    """(variant, scenario) -> a fresh react_single agent or commander team, with the policy's lessons."""
    client, decoding = await open_llm_client(stack)
    return llm_maker(client, decoding, policy)


async def open_llm_client(stack: AsyncExitStack) -> tuple[Any, Any]:
    """One paced client for everything in this process: two clients would each pace separately and together
    exceed the endpoint's shared per-user limit."""
    from doomlab.config import RUNS_DIR, load_settings
    from doomlab.llm.client import RCACClient
    from doomlab.llm.preflight import load_frozen_decoding

    settings = load_settings()
    decoding = load_frozen_decoding(RUNS_DIR / "preflight.json", settings.model_id)
    return await stack.enter_async_context(RCACClient(settings)), decoding


def llm_maker(client: Any, decoding: Any, policy: Policy) -> Callable[[str, str], Agent]:
    from doomlab.agents.commander import CommanderTeam
    from doomlab.agents.react import ReactAgent
    from doomlab.llm.budget import budget_for

    def make(variant: str, scenario: str) -> Agent:
        agent_class = CommanderTeam if variant == "commander" else ReactAgent
        return agent_class(client, scenario=scenario, decoding=decoding, budget=budget_for(scenario),  # fresh per episode
                           lessons=policy.lessons)

    return make

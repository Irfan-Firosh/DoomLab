"""A minimal state graph: named nodes, one way out of each (fixed edge or branch), and a transition cap.

Nodes take the state and return a new one (sync or async); the engine never mutates state itself.
Wiring mistakes fail when the graph is built, and a branch choosing an undeclared target fails at run time,
so every path the graph can take is visible in the code that builds it.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from typing import Generic, TypeVar

S = TypeVar("S")
Node = Callable[[S], "S | Awaitable[S]"]
END = "__end__"


class GraphError(Exception):
    """The graph was wired wrongly, or ran past its transition cap."""


class Graph(Generic[S]):
    def __init__(self, *, max_transitions: int) -> None:
        self._max = max_transitions
        self._nodes: dict[str, Node] = {}
        self._exits: dict[str, tuple[Callable[[S], str], frozenset[str]]] = {}

    def node(self, name: str, fn: Node) -> None:
        if name in self._nodes or name == END:
            raise GraphError(f"node {name!r} already exists")
        self._nodes[name] = fn

    def edge(self, src: str, dst: str) -> None:
        self.branch(src, lambda state: dst, targets=(dst,))

    def branch(self, src: str, choose: Callable[[S], str], *, targets: Iterable[str]) -> None:
        targets = frozenset(targets)
        unknown = [t for t in [src, *targets] if t not in self._nodes and t != END]
        if unknown:
            raise GraphError(f"edge from {src!r} names unknown node(s) {sorted(unknown)}")
        if src in self._exits:
            raise GraphError(f"node {src!r} already has a way out")
        self._exits[src] = (choose, targets)

    async def run(self, entry: str, state: S, *, on_transition: Callable[[str, str, S], None] | None = None) -> S:
        if entry not in self._nodes:
            raise GraphError(f"unknown entry node {entry!r}")
        current = entry
        for _ in range(self._max):
            result = self._nodes[current](state)
            state = await result if inspect.isawaitable(result) else result
            if current not in self._exits:
                raise GraphError(f"node {current!r} has no outgoing edge")
            choose, targets = self._exits[current]
            nxt = choose(state)
            if nxt not in targets:
                raise GraphError(f"node {current!r} chose undeclared target {nxt!r}")
            if on_transition:
                on_transition(current, nxt, state)
            if nxt == END:
                return state
            current = nxt
        raise GraphError(f"graph did not finish within {self._max} transitions")

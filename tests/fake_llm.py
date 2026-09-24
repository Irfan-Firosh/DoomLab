"""A fake Qwen: returns queued ChatResults (or raises queued errors) and records every request."""

from __future__ import annotations

from doomlab.llm.client import ChatResult, LLMError
from doomlab.tools.registry import ToolCall


def reply(tool=None, args=None, content="", tokens=100):
    calls = (ToolCall(tool, args or {}),) if tool else ()
    usage = {"prompt_tokens": tokens - 20, "completion_tokens": 20, "total_tokens": tokens} if tokens else None
    return ChatResult(tool_calls=calls, content=content, reasoning_present=False, usage=usage, started=0.0, finished=0.5)


class FakeLLM:
    def __init__(self, replies):
        self._replies = list(replies)
        self.requests: list[dict] = []

    async def chat(self, messages, **kwargs):
        self.requests.append({"messages": messages, **kwargs})
        item = self._replies.pop(0)
        if isinstance(item, LLMError):
            raise item
        return item

"""Purdue RCAC chat client. The only module in DoomLab that talks HTTP."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from doomlab.config import Settings
from doomlab.llm.pacer import RequestPacer
from doomlab.tools.registry import ToolCall

DEFAULT_TIMEOUT_S = 60.0
MAX_CONCURRENCY = 2
MAX_REQUESTS_PER_MINUTE = 20
RATE_LIMIT_TEXT = "rate limit"  # Purdue answers HTTP 400 with this in the body when rate limiting


class LLMError(Exception):
    """A typed failure. `kind` is one of: auth, rate_limited, http, bad_response, timeout."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind


@dataclass(frozen=True)
class ChatResult:
    tool_calls: tuple[ToolCall, ...]
    content: str
    reasoning_present: bool
    usage: dict[str, int] | None
    started: float
    finished: float

    @property
    def latency_s(self) -> float:
        return self.finished - self.started


class RCACClient:
    """Async client with a concurrency cap. Use as `async with RCACClient(settings) as client`."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_concurrency: int = MAX_CONCURRENCY,
        requests_per_minute: float | None = MAX_REQUESTS_PER_MINUTE,
    ) -> None:
        self._settings = settings
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {settings.api_key}"},
        )
        self._slots = asyncio.Semaphore(max_concurrency)
        self.requests_per_minute = requests_per_minute
        self._pacer = RequestPacer(requests_per_minute) if requests_per_minute else None

    async def __aenter__(self) -> RCACClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    async def list_models(self) -> list[str]:
        await self._pace()
        body = await self._request("GET", self._settings.models_url)
        return [m["id"] for m in body.get("data", []) if isinstance(m, dict) and "id" in m]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.0,
        max_tokens: int = 512,
        disable_thinking: bool = False,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self._settings.model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        if disable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        async with self._slots:
            await self._pace()  # before the clock starts: latency measures the model, not our own pacing
            started = time.monotonic()
            body = await self._request("POST", self._settings.chat_url, payload)
            finished = time.monotonic()
        return _parse_completion(body, started, finished)

    async def _pace(self) -> None:
        if self._pacer:
            await self._pacer.wait()

    async def _request(self, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = await self._http.request(method, url, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError("timeout", f"no response within the timeout ({url})") from exc
        except httpx.HTTPError as exc:
            raise LLMError("http", f"{type(exc).__name__} calling {url}") from exc

        if response.status_code in (401, 403):
            raise LLMError("auth", f"HTTP {response.status_code}: check RCAC_API_KEY")
        if response.status_code == 429:
            raise LLMError("rate_limited", "HTTP 429 from the endpoint")
        if response.status_code >= 400:
            detail = _server_detail(response)
            if RATE_LIMIT_TEXT in detail.lower():
                raise LLMError("rate_limited", f"HTTP {response.status_code}: {detail}")
            raise LLMError("http", f"HTTP {response.status_code} from {url}: {detail}")
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMError("bad_response", f"non-JSON response from {url} (check RCAC_BASE_URL)") from exc
        if body is None:  # Purdue documents a JSON `null` body when rate limited
            raise LLMError("rate_limited", "endpoint returned null")
        if not isinstance(body, dict):
            raise LLMError("bad_response", f"unexpected {type(body).__name__} body from {url}")
        return body


def _server_detail(response: httpx.Response, limit: int = 200) -> str:
    """Short, human-readable reason from an error body (FastAPI-style `detail` when present)."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:limit].strip() or "no details"
    if isinstance(body, dict) and isinstance(body.get("detail"), str):
        return body["detail"][:limit]
    return str(body)[:limit]


def _parse_completion(body: dict[str, Any], started: float, finished: float) -> ChatResult:
    choices = body.get("choices")
    if not choices or not isinstance(choices[0], dict) or "message" not in choices[0]:
        raise LLMError("bad_response", "completion has no choices[0].message")
    message = choices[0]["message"] or {}
    return ChatResult(
        tool_calls=tuple(_parse_tool_call(c) for c in message.get("tool_calls") or ()),
        content=message.get("content") or "",
        reasoning_present=bool(message.get("reasoning_content") or message.get("reasoning")),
        usage=body.get("usage") or None,
        started=started,
        finished=finished,
    )


def _parse_tool_call(raw: dict[str, Any]) -> ToolCall:
    function = raw.get("function") or {}
    name = function.get("name")
    arguments = function.get("arguments") or "{}"
    if not name:
        raise LLMError("bad_response", "tool call without a function name")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise LLMError("bad_response", f"tool call {name!r} has non-JSON arguments") from exc
    if not isinstance(arguments, dict):
        raise LLMError("bad_response", f"tool call {name!r} arguments are not an object")
    return ToolCall(name=name, arguments=arguments)

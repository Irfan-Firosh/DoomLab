import json

import httpx
import pytest

from doomlab.config import Settings
from doomlab.llm.client import LLMError, RCACClient

SETTINGS = Settings(base_url="https://rcac.test", model_id="qwen3.8:27b", api_key="SECRET-KEY-123")
TOOLS = [{"type": "function", "function": {"name": "attack", "parameters": {"type": "object", "properties": {}}}}]


def completion(tool_calls=None, content="", usage=None, reasoning=None):
    message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    body = {"choices": [{"message": message}]}
    if usage is not None:
        body["usage"] = usage
    return body


def client_with(handler):
    return RCACClient(SETTINGS, transport=httpx.MockTransport(handler))


async def test_list_models_returns_ids_and_sends_bearer():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"data": [{"id": "qwen3.8:27b"}, {"id": "other"}]})

    async with client_with(handler) as client:
        assert await client.list_models() == ["qwen3.8:27b", "other"]
    assert seen == {"auth": "Bearer SECRET-KEY-123", "url": "https://rcac.test/api/models"}


async def test_chat_parses_tool_call_usage_and_reasoning():
    call = {"id": "c1", "type": "function", "function": {"name": "turn_to", "arguments": json.dumps({"target_id": 7})}}
    usage = {"prompt_tokens": 359, "completion_tokens": 252, "total_tokens": 611}

    def handler(request):
        return httpx.Response(200, json=completion([call], usage=usage, reasoning="thinking..."))

    async with client_with(handler) as client:
        result = await client.chat([{"role": "user", "content": "hi"}], tools=TOOLS)
    assert result.tool_calls[0].name == "turn_to"
    assert result.tool_calls[0].arguments == {"target_id": 7}
    assert result.usage == usage
    assert result.reasoning_present is True
    assert result.finished >= result.started and result.latency_s >= 0


async def test_chat_sends_model_tools_and_thinking_switch():
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json=completion(content="ok"))

    async with client_with(handler) as client:
        await client.chat([{"role": "user", "content": "hi"}], tools=TOOLS, disable_thinking=True, max_tokens=64)
    assert sent["model"] == "qwen3.8:27b"
    assert sent["tools"] == TOOLS
    assert sent["max_tokens"] == 64
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}


async def test_missing_usage_is_none_not_zero():
    async with client_with(lambda r: httpx.Response(200, json=completion(content="hi"))) as client:
        result = await client.chat([{"role": "user", "content": "hi"}])
    assert result.usage is None and result.tool_calls == ()


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (httpx.Response(401, json={"detail": "bad key"}), "auth"),
        (httpx.Response(429, json={"detail": "slow down"}), "rate_limited"),
        (httpx.Response(200, content=b"null"), "rate_limited"),
        (httpx.Response(200, text="<!doctype html>"), "bad_response"),
        (httpx.Response(500, text="boom"), "http"),
    ],
)
async def test_errors_are_typed(response, kind):
    async with client_with(lambda r: response) as client:
        with pytest.raises(LLMError) as err:
            await client.chat([{"role": "user", "content": "hi"}])
    assert err.value.kind == kind
    assert "SECRET-KEY-123" not in str(err.value)


async def test_malformed_tool_arguments_are_typed_error():
    call = {"id": "c1", "type": "function", "function": {"name": "attack", "arguments": "{not json"}}
    async with client_with(lambda r: httpx.Response(200, json=completion([call]))) as client:
        with pytest.raises(LLMError) as err:
            await client.chat([{"role": "user", "content": "hi"}], tools=TOOLS)
    assert err.value.kind == "bad_response"


async def test_error_includes_server_detail():
    response = httpx.Response(400, json={"detail": "Model not found"})
    async with client_with(lambda r: response) as client:
        with pytest.raises(LLMError) as err:
            await client.chat([{"role": "user", "content": "hi"}])
    assert err.value.kind == "http" and "Model not found" in str(err.value)

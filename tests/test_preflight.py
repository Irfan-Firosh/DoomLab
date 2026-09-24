import json

import httpx

from doomlab.config import Settings
from doomlab.llm.client import RCACClient
from doomlab.llm.preflight import interval_overlap, run_preflight

SETTINGS = Settings(base_url="https://rcac.test", model_id="qwen3.8:27b", api_key="SECRET-KEY-123")


def test_interval_overlap():
    assert interval_overlap((0.0, 2.0), (1.0, 3.0)) == 1.0
    assert interval_overlap((0.0, 1.0), (2.0, 3.0)) == 0.0


def fake_rcac(thinking_switch_works=True, listed=True):
    def handler(request):
        if request.url.path.endswith("/models"):
            ids = ["qwen3.8:27b"] if listed else ["other"]
            return httpx.Response(200, json={"data": [{"id": i} for i in ids]})
        body = json.loads(request.content)
        off = body.get("chat_template_kwargs") == {"enable_thinking": False} and thinking_switch_works
        call = {"id": "c", "type": "function", "function": {"name": "turn_to", "arguments": '{"target_id": 7}'}}
        message = {"role": "assistant", "content": "", "tool_calls": [call]}
        if not off:
            message["reasoning_content"] = "let me think"
        usage = {"prompt_tokens": 300, "completion_tokens": 40 if off else 250, "total_tokens": 340 if off else 550}
        return httpx.Response(200, json={"choices": [{"message": message}], "usage": usage})

    return RCACClient(SETTINGS, transport=httpx.MockTransport(handler))


async def test_preflight_report_all_checks_pass(tmp_path):
    out = tmp_path / "preflight.json"
    async with fake_rcac() as client:
        report = await run_preflight(client, SETTINGS, out)
    saved = json.loads(out.read_text())
    assert saved == report
    assert report["ok"] is True
    assert report["model_listed"] is True
    assert report["tool_calling"]["ok"] is True
    assert report["tool_calling"]["example_call"] == {"name": "turn_to", "arguments": {"target_id": 7}}
    assert report["thinking"]["disabled"] is True
    assert report["usage_reported"] is True
    assert report["decoding_frozen"]["thinking"] == "off"
    assert "overlap_s" in report["overlap_probe"]
    assert "SECRET-KEY-123" not in out.read_text()


async def test_preflight_keeps_thinking_on_when_switch_is_ignored(tmp_path):
    async with fake_rcac(thinking_switch_works=False) as client:
        report = await run_preflight(client, SETTINGS, tmp_path / "p.json")
    assert report["thinking"]["disabled"] is False
    assert report["decoding_frozen"]["thinking"] == "on"
    assert report["ok"] is True


async def test_preflight_stops_early_when_model_missing(tmp_path):
    async with fake_rcac(listed=False) as client:
        report = await run_preflight(client, SETTINGS, tmp_path / "p.json")
    assert report["ok"] is False
    assert report["model_listed"] is False
    assert report["error"]["kind"] == "model_not_listed"
    assert "other" in report["error"]["message"]  # lists what is available
    assert "tool_calling" not in report  # no wasted chat calls

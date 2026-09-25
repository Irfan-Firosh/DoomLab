import json

import numpy as np
from fakes import FakeSession

from doomlab.agents.scripted import ScriptedAgent
from doomlab.replay import load_trace, replay, write_gif
from doomlab.runner import arun_episode
from doomlab.trace import TraceWriter


async def record(tmp_path, target_y=40.0):
    path = tmp_path / "ep.jsonl"
    with TraceWriter(path) as trace:
        await arun_episode(FakeSession(target_y=target_y), ScriptedAgent(), scenario="basic", seed=0, trace=trace)
    return path


def fake_factory(target_y=40.0):
    return lambda scenario, seed: FakeSession(target_y=target_y)


async def test_load_trace_extracts_steps_and_buttons(tmp_path):
    trace = load_trace(await record(tmp_path))
    assert (trace.scenario, trace.seed, trace.agent) == ("basic", 0, "scripted")
    assert [s.tool for s in trace.steps] == ["aim_at", "attack"]
    assert sum(len(s.buttons) for s in trace.steps) == trace.end["tics"]


async def test_replay_of_a_faithful_trace_matches(tmp_path):
    report = replay(load_trace(await record(tmp_path)), session_factory=fake_factory())
    assert report.matches, report.mismatches
    assert report.tics == load_trace(await record(tmp_path / "again")).end["tics"]


async def test_tampered_trace_is_caught(tmp_path):
    path = await record(tmp_path)
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    aim = next(l for l in lines if l["event"] == "tool_exec" and l["tool"] == "aim_at")
    aim["buttons"][0] = [0, 1, 0]  # flip the first strafe from LEFT to RIGHT
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    report = replay(load_trace(path), session_factory=fake_factory())
    assert not report.matches and report.mismatches


async def test_rejected_steps_press_nothing(tmp_path):
    from fake_llm import FakeLLM, reply

    from doomlab.agents.react import ReactAgent
    from doomlab.llm.budget import Budget
    from doomlab.llm.preflight import Decoding

    llm = FakeLLM([reply("attack", {"burst": 1}), reply("aim_at", {"target_id": 0}), reply("attack", {"burst": 1})])
    agent = ReactAgent(llm, scenario="basic", decoding=Decoding("qwen3.8:27b", 0.0, 512, True), budget=Budget())
    path = tmp_path / "react.jsonl"
    with TraceWriter(path) as trace:
        await arun_episode(FakeSession(target_y=40.0), agent, scenario="basic", seed=0, trace=trace)
    loaded = load_trace(path)
    assert loaded.steps[0].ok is False and loaded.steps[0].buttons == ()
    assert replay(loaded, session_factory=fake_factory()).matches


def test_write_gif_makes_a_valid_animation(tmp_path):
    import imageio.v3 as iio

    frames = [np.full((240, 320, 3), i * 20, dtype=np.uint8) for i in range(6)]
    path = tmp_path / "ep.gif"
    write_gif(frames, [f"step {i}" for i in range(6)], path, every=2)
    gif = iio.imread(path, index=None)
    assert gif.shape[0] == 4 and gif.shape[1] > 240  # frames 0, 2, 4 + the final frame; caption bar adds height

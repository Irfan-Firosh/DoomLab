"""Record a real scripted episode, then replay it in a fresh vizDoom (local, no network)."""

import json

import pytest

from doomlab.agents.scripted import ScriptedAgent
from doomlab.env.doom import DoomSession
from doomlab.replay import load_trace, replay, write_gif
from doomlab.runner import arun_episode
from doomlab.trace import TraceWriter


async def record(tmp_path, seed):
    path = tmp_path / f"basic-s{seed}.jsonl"
    with DoomSession("basic", seed=seed) as session, TraceWriter(path) as trace:
        await arun_episode(session, ScriptedAgent(), scenario="basic", seed=seed, trace=trace)
    return path


@pytest.mark.parametrize("seed", [1, 4])
async def test_real_replay_matches_and_makes_a_gif(tmp_path, seed):
    report = replay(load_trace(await record(tmp_path, seed)))
    assert report.matches, report.mismatches
    assert len(report.frames) == report.tics + 1  # start frame + one per tic
    gif = tmp_path / "ep.gif"
    write_gif(report.frames, report.captions, gif)
    assert gif.stat().st_size > 10_000


async def test_real_tampered_replay_is_caught(tmp_path):
    path = await record(tmp_path, 1)
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    aim = next(l for l in lines if l["event"] == "tool_exec" and l["tool"] == "aim_at")
    aim["buttons"] = aim["buttons"][:-10]  # drop the last 10 strafe tics
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    assert not replay(load_trace(path)).matches

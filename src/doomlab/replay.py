"""Rebuild an episode from its trace (seed + recorded button presses), verify it, and export a GIF.

Verification compares the replay with the trace at every recorded observation (tic, ammo, kills,
each visible object's offset) and at the end. A faithful trace of a deterministic game must match.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from doomlab.env.doom import DoomSession
from doomlab.env.perception import Observation
from doomlab.tools.executor import Executor, Session

OFFSET_TOLERANCE = 0.5  # units; replayed geometry must agree this closely
CAPTION_HEIGHT = 22
GIF_EVERY = 2  # keep every 2nd tic: ~17 frames per second, real-time speed
GAME_TICS_PER_SECOND = 35


@dataclass(frozen=True)
class TracedStep:
    step: int
    tool: str
    args: dict[str, Any]
    ok: bool
    buttons: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class Trace:
    scenario: str
    seed: int
    agent: str
    steps: tuple[TracedStep, ...]
    observations: dict[int, dict[str, Any]]  # observe event recorded before step N's decision
    end: dict[str, Any]


@dataclass(frozen=True)
class ReplayReport:
    matches: bool
    mismatches: tuple[str, ...]
    tics: int
    frames: list[np.ndarray] = field(repr=False)
    captions: list[str] = field(repr=False)


def load_trace(path: Path) -> Trace:
    events = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    start = next(e for e in events if e["event"] == "episode_start")
    end = next((e for e in events if e["event"] == "episode_end"), {})
    steps = tuple(
        TracedStep(e["step"], e["tool"], e["args"], e["ok"], tuple(tuple(b) for b in e["buttons"]))
        for e in events
        if e["event"] == "tool_exec"
    )
    observations = {e["step"]: e for e in events if e["event"] == "observe"}
    return Trace(start["scenario"], start["seed"], start["agent"], steps, observations, end)


def replay(trace: Trace, session_factory: Callable[[str, int], Session] = DoomSession) -> ReplayReport:
    session = session_factory(trace.scenario, trace.seed)
    try:
        return _replay(trace, session)
    finally:
        close = getattr(session, "close", None)
        if close:
            close()


def _replay(trace: Trace, session: Session) -> ReplayReport:
    executor = Executor(session)
    mismatches: list[str] = []
    frames: list[np.ndarray] = []
    captions: list[str] = []
    _capture(session, frames, captions, "start")
    tics = 0
    for step in trace.steps:
        expected = trace.observations.get(step.step)
        if expected:
            mismatches += _compare(step.step, expected, executor.observe())
        caption = f"step {step.step} · {step.tool}({', '.join(f'{k}={v}' for k, v in step.args.items())})"
        if not step.ok:
            caption += " · rejected"
        for action in step.buttons:
            executor.press_recorded(action)
            tics += 1
            _capture(session, frames, captions, caption)
    final = executor.observe()
    if trace.end:
        if tics != trace.end.get("tics"):
            mismatches.append(f"end: tics expected {trace.end.get('tics')} got {tics}")
        if int(final.kills or 0) != trace.end.get("kills"):
            mismatches.append(f"end: kills expected {trace.end.get('kills')} got {int(final.kills or 0)}")
    return ReplayReport(not mismatches, tuple(mismatches), tics, frames, captions)


def _compare(step: int, expected: dict[str, Any], actual: Observation) -> list[str]:
    problems = []
    for name in ("tic", "ammo", "kills"):
        if expected.get(name) != getattr(actual, name):
            problems.append(f"step {step}: {name} expected {expected.get(name)} got {getattr(actual, name)}")
    want = {f["id"]: f["offset"] for f in expected.get("facts", [])}
    got = {f.id: f.offset for f in actual.facts}
    if set(want) != set(got):
        problems.append(f"step {step}: visible ids expected {sorted(want)} got {sorted(got)}")
    for fid in set(want) & set(got):
        if abs(want[fid] - got[fid]) > OFFSET_TOLERANCE:
            problems.append(f"step {step}: offset of id {fid} expected {want[fid]:.1f} got {got[fid]:.1f}")
    return problems


def _capture(session: Session, frames: list[np.ndarray], captions: list[str], caption: str) -> None:
    frame = session.read_state().frame
    if frame is None and frames:
        frame = frames[-1]  # after the episode ends vizDoom has no screen: hold the last image
    if frame is not None:
        frames.append(frame)
        captions.append(caption)


def write_gif(frames: list[np.ndarray], captions: list[str], path: Path, *, every: int = GIF_EVERY) -> Path:
    """Animated GIF at real-time speed with a caption bar naming the agent's current decision."""
    import imageio.v3 as iio

    kept = [(f, c) for i, (f, c) in enumerate(zip(frames, captions)) if i % every == 0 or i == len(frames) - 1]
    images = [_with_caption(frame, caption) for frame, caption in kept]
    duration_ms = round(1000 * every / GAME_TICS_PER_SECOND)
    path.parent.mkdir(parents=True, exist_ok=True)
    iio.imwrite(path, np.stack(images), duration=duration_ms, loop=0)
    return path


def _with_caption(frame: np.ndarray, caption: str) -> np.ndarray:
    height, width = frame.shape[:2]
    canvas = Image.new("RGB", (width, height + CAPTION_HEIGHT), (16, 21, 28))
    canvas.paste(Image.fromarray(frame), (0, 0))
    ImageDraw.Draw(canvas).text((6, height + 5), caption, fill=(232, 237, 243))
    return np.asarray(canvas)

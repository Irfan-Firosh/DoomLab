"""Build the static portfolio page from the committed experiment evidence.

Run from any directory: python3 demo/build.py
Only files within demo/ are written. No model or ViZDoom execution is needed.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
import shutil
import tarfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AGENTS = ("random", "scripted", "react_single", "commander")
AGENT_LABELS = {
    "random": "Random",
    "scripted": "Hand-written rules",
    "react_single": "Single agent",
    "commander": "Multi-agent team",
}
SCENARIO_LABELS = {
    "basic": "Target practice",
    "defend_the_center": "Hold the center",
    "health_gathering_supreme": "Find medikits",
}
COLORS = {
    "random": "#75716b",
    "scripted": "#34332e",
    "react_single": "#75716b",
    "commander": "#75716b",
}
DESCRIPTIONS = {
    "random": "Picks any allowed tool at random.",
    "scripted": "Four hand-written rules.",
    "react_single": "One Qwen agent, one action per turn.",
    "commander": "Qwen coordinator assigns Combat or Navigation.",
}
# These display intervals are the ones published in results/metrics.md.
INTERVALS = {0: "0–28%", 1: "2–40%", 2: "6–51%", 9: "60–98%", 10: "72–100%"}


def number(value: float) -> str:
    """Keep all recorded decimal places, including half-tic medians."""
    return f"{int(value):,}" if value == int(value) else f"{value:,}"


def load_trace(agent: str) -> tuple[bytes, list[dict]]:
    name = f"defend_the_center-s1000-{agent}.jsonl"
    # The committed archive is the deployable source of truth; runs/ is ignored.
    with tarfile.open(ROOT / "results/traces/eval-test.tar.gz") as archive:
        source = archive.extractfile(name)
        if source is None:
            raise ValueError(f"Missing trace: {name}")
        raw = source.read()
    return raw, [json.loads(line) for line in raw.splitlines() if line.strip()]


def agent_cards(traces: dict[str, list[dict]]) -> str:
    cards = []
    for agent in AGENTS:
        end = next(event for event in traces[agent] if event["event"] == "episode_end")
        score, kills = end["score"], end["kills"]
        best = agent == "react_single"
        asset = f"assets/defend_the_center-s1000-{agent}"
        note = '<small>Best on this level.</small>' if best else ''
        cards.append(f'''<figure class="agent-replay" aria-label="{AGENT_LABELS[agent]} replay and episode score">
          <h3>{AGENT_LABELS[agent]}</h3>
          <div class="replay-screen"><video muted playsinline autoplay loop preload="auto" poster="{asset}-poster.webp" aria-label="{AGENT_LABELS[agent]} recorded replay, Hold the center seed 1000, at twice real time" data-agent="{agent}" data-replay-group="held-out" tabindex="0" role="button"><source src="{asset}.mp4" type="video/mp4"><img src="{asset}.webp" alt="{AGENT_LABELS[agent]} replay with recorded tool-call captions" loading="lazy" width="320" height="262"></video></div>
          <figcaption><span class="episode-score">{number(score)} tics · {number(kills)} kills</span><span class="agent-description">{DESCRIPTIONS[agent]}</span>{note}</figcaption>
        </figure>''')
    return "\n".join(cards)


def score_rows(groups: dict) -> str:
    rows = []
    for scenario in ("defend_the_center", "health_gathering_supreme"):  # target practice is a smoke test, left out
        lower = scenario == "basic"
        medians = [groups[scenario][agent]["score"]["median"] for agent in AGENTS]
        best = min(medians) if lower else max(medians)
        direction = "tics to kill · lower is better" if lower else "tics survived · higher is better"
        cells = []
        for agent, median in zip(AGENTS, medians):
            item = groups[scenario][agent]
            if item["n"] != 10:
                raise ValueError("Review the published Wilson interval labels for the new sample size.")
            classes = []
            if median == best:
                classes.append("best-score")
            cells.append(f'<td class="{" ".join(classes)}"><span class="score-number">{number(median)}</span>'
                         f'<span class="success-cell"><strong>{item["successes"]}/{item["n"]}</strong> · {INTERVALS[item["successes"]]}</span></td>')
        rows.append(f'<tr><th scope="row">{SCENARIO_LABELS[scenario]}<small>{direction}</small></th>{"".join(cells)}</tr>')
    return "\n".join(rows)


def distribution(summary: dict, scenario: str, slug: str, maximum: int, ticks: list[int]) -> str:
    left, right, width, height = 120, 645, 760, 218
    scale = (right - left) / maximum
    direction = "lower" if scenario == "basic" else "higher"
    unit = "tics to kill" if scenario == "basic" else "tics survived"
    svg = [f'<svg class="distribution-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="group" aria-label="Per-seed scores for {SCENARIO_LABELS[scenario]}: {unit}, {direction} is better">']
    svg.append('<text x="752" y="17" text-anchor="end">median</text>')
    for tick in ticks:
        x = left + tick * scale
        svg.append(f'<line class="chart-grid" x1="{x}" x2="{x}" y1="28" y2="178"/><text x="{x}" y="207" text-anchor="middle">{number(tick)}</text>')
    for row, agent in enumerate(AGENTS):
        y = 42 + row * 40
        color = COLORS[agent]
        median = summary["test"]["groups"][scenario][agent]["score"]["median"]
        svg.append(f'<text class="chart-agent-name" x="0" y="{y + 4}">{AGENT_LABELS[agent]}</text>')
        for index, (seed, values) in enumerate(summary["test"]["paired"][scenario].items()):
            value = values[agent]
            # A small deterministic offset separates overlapping seeds, never x-values.
            offset = (-5, 0, 5)[index % 3]
            label = f"Seed {seed} · {AGENT_LABELS[agent]} · {number(value)} {unit} · {direction} is better"
            svg.append(f'<circle class="seed-dot agent-{agent}" data-seed="{seed}" data-label="{escape(label)}" cx="{left + value * scale:.5f}" cy="{y + offset}" r="3.5" fill="{color}" tabindex="0" role="img" aria-label="{escape(label)}"><title>{escape(label)}</title></circle>')
        x = left + median * scale
        svg.append(f'<line class="median-marker agent-{agent}" x1="{x:.5f}" x2="{x:.5f}" y1="{y - 11}" y2="{y + 11}" stroke="{color}" pointer-events="none"/>')
        svg.append(f'<text class="chart-median-label" x="752" y="{y + 5}" text-anchor="end">{number(median)}</text>')
    svg.append('</svg>')
    return f'<div class="distribution-plot" id="chart-{slug}"><h3 class="plot-heading">{SCENARIO_LABELS[scenario]}<span>{unit.capitalize()} · {direction} is better · n = 10 per agent</span></h3><div class="plot-scroll" tabindex="0" role="region" aria-label="{SCENARIO_LABELS[scenario]} per-seed distribution">{"".join(svg)}<div class="plot-tooltip" role="status" hidden></div></div></div>'


def trial_pairs(trial: dict) -> str:
    rows = []
    for item in trial["ab"]:
        rows.append(f'<tr><th scope="row">{item["seed"]}</th><td>{number(item["v0"])}</td><td>{number(item["v1"])}</td></tr>')
    return "\n".join(rows)


def timeline(events: list[dict]) -> str:
    tics = {event["step"]: event["tic"] for event in events if event["event"] == "observe"}
    end = next(event for event in events if event["event"] == "episode_end")["tics"]
    modes = [(tics.get(event["step"], 0), event["mode"]) for event in events if event["event"] == "mode"]
    kills = [tics[event["step"]] + event["tics"] for event in events
             if event["event"] == "tool_exec" and event.get("kills_gained") and event["step"] in tics]
    assert len(modes) == 24 and len(kills) == 24 and end == 1413
    assert sum(a[1] != b[1] for a, b in zip(modes, modes[1:])) == 23
    left, right = 12, 1010
    scale = (right - left) / end
    parts = ['<svg class="timeline-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1030 115" role="img" aria-labelledby="timeline-title timeline-description"><title id="timeline-title">Commander modes over game time</title><desc id="timeline-description">24 mode choices and 23 switches between Combat and Navigator, with 24 recorded kills. The episode ends at tic 1,413.</desc>']
    for tick in (0, 250, 500, 750, 1000, 1250):
        x = left + tick * scale
        parts.append(f'<line class="timeline-grid" x1="{x}" x2="{x}" y1="13" y2="75"/><text x="{x}" y="98" text-anchor="{"start" if tick == 0 else "middle"}">{number(tick)}</text>')
    for index, (start, mode) in enumerate(modes):
        stop = modes[index + 1][0] if index + 1 < len(modes) else end
        name = "Combat" if mode == "fight" else "Navigator"
        parts.append(f'<rect class="mode-{mode}" x="{left + start * scale:.5f}" y="40" width="{(stop - start) * scale:.5f}" height="26" rx="1"><title>{name}: tics {number(start)}–{number(stop)}</title></rect>')
    for kill in kills:
        x = left + kill * scale
        parts.append(f'<line class="timeline-kill" x1="{x:.5f}" x2="{x:.5f}" y1="23" y2="33"><title>Kill at tic {number(kill)}</title></line>')
    parts.append(f'<text class="timeline-end" x="{right}" y="98" text-anchor="end">1,413</text></svg>')
    return "".join(parts)


def main() -> None:
    summary = json.loads((ROOT / "results/summary.json").read_text())
    gate = json.loads((ROOT / "improve/trial-v1/gate_result.json").read_text())
    assert summary["test"]["episodes"] == 120
    assert summary["provenance"]["frozen"]["hash"].startswith("af2ab05f5f7c")
    assert summary["trial"]["lessons"] == gate["candidate"]["lessons"]
    data_dir = HERE / "data"
    data_dir.mkdir(exist_ok=True)
    traces = {}
    for agent in AGENTS:
        raw, traces[agent] = load_trace(agent)
        if agent == "commander":
            (data_dir / "commander-trace.jsonl").write_bytes(raw)
    shutil.copyfile(ROOT / "results/summary.json", data_dir / "summary.json")
    rejected = [json.loads(line) for line in (data_dir / "rejected-action-trace.jsonl").read_text().splitlines() if line.strip()]
    failed_call = next(event for event in rejected if event.get("event") == "tool_exec" and event.get("step") == 8)
    next_call = next(event for event in rejected if event.get("event") == "tool_exec" and event.get("step") == 9)
    assert failed_call["code"] == "NO_ENEMY_IN_CONE" and next_call["tool"] == "aim_at"
    rejection = f'<div class="trace-call"><p>Test seed 1001, decision 8</p><pre tabindex="0" role="region" aria-label="Rejected tool call and validation response"><code>{escape(failed_call["tool"])}(burst={failed_call["args"]["burst"]}) → {escape(failed_call["code"])}: “{escape(failed_call["message"])}”</code></pre><p>No game time passed ({failed_call["tics"]} tics). Next call: <code>{escape(next_call["tool"])}(target_id={next_call["args"]["target_id"]})</code> → {escape(next_call["message"])}.</p></div>'
    fields = {
        "AGENT_CARDS": agent_cards(traces),
        "REJECTION_EXAMPLE": rejection,
        "SCORE_ROWS": score_rows(summary["test"]["groups"]),
        "DISTRIBUTIONS": "\n".join([
            distribution(summary, "defend_the_center", "defend", 2000, [0, 500, 1000, 1500, 2000]),
            distribution(summary, "health_gathering_supreme", "supreme", 2100, [0, 500, 1000, 1500, 2100]),
        ]),
        "LESSONS": "\n".join(f"<li><q>{escape(lesson)}</q></li>" for lesson in summary["trial"]["lessons"]),
        "TRIAL_PAIRS": trial_pairs(summary["trial"]),
        "HUMAN_NOTE": escape(summary["trial"]["human_note"]),
        "TIMELINE": timeline(traces["commander"]),
    }
    page = (HERE / "template.html").read_text()
    for key, value in fields.items():
        placeholder = f"__{key}__"
        assert placeholder in page, f"Missing placeholder: {key}"
        page = page.replace(placeholder, value)
    (HERE / "index.html").write_text(page)
    # Preserve the original embed entry point, with identical current content.
    (HERE / "page.html").write_text(page)
    print("Built demo/index.html and demo/page.html from committed results and traces.")


if __name__ == "__main__":
    main()

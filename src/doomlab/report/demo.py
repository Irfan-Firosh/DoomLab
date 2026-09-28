"""`doomlab demo`: a static page that needs no API key, built from results/summary.json and the test traces.

Writes demo/index.html (a full document, for GitHub Pages or opening locally), demo/page.html (the same page
without the document shell, for hosts that wrap it) and demo/assets/: one animated WebP per agent, replayed
from the recorded button presses and checked against the trace before it is used.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from string import Template
from typing import Any

from PIL import Image, ImageDraw

from doomlab.eval.harness import load_events
from doomlab.replay import load_trace, replay
from doomlab.report.charts import WIDTH, bars_with_intervals, dot_plot, paired_lines
from doomlab.runner import SCORES
from doomlab.variants import LLM_VARIANTS, VARIANTS

TEMPLATE = Path(__file__).with_name("demo_template.html")
REPO = "https://github.com/Irfan-Firosh/DoomLab"
FRAME_EVERY = 4  # keep every 4th game tic
SPEEDUP = 2  # played at twice real time
WEBP_QUALITY = 50
CAPTION_H = 22
ABOUT = {
    "random": "picks any allowed tool at random",
    "scripted": "four hand-written rules",
    "react_single": "one Qwen agent, one tool call per turn",
    "commander": "a Qwen commander and two specialists",
}
SCORE_TEXT = {"tics": "tics to kill", "survived_tics": "tics survived"}


class DemoError(RuntimeError):
    """A replay did not reproduce its trace, so its animation would misrepresent the episode."""


def build_demo(results: Path, traces: Path, out: Path, *, scenario: str = "defend_the_center", seed: int = 1000) -> Path:
    summary = json.loads((results / "summary.json").read_text())
    (out / "assets").mkdir(parents=True, exist_ok=True)
    scores = {}
    for variant in VARIANTS:
        trace = traces / f"{scenario}-s{seed}-{variant}.jsonl"
        scores[variant] = _animate(trace, out / "assets" / f"{scenario}-s{seed}-{variant}.webp")
    commander = load_events(traces / f"{scenario}-s{seed}-commander.jsonl")
    fields = _fields(summary, scenario, seed, scores, commander)
    body = Template(TEMPLATE.read_text()).substitute(fields)
    (out / "page.html").write_text(body)
    head, rest = body.split("<style>", 1)
    document = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                f'{head}<style>{rest.split("</style>", 1)[0]}</style>\n</head>\n<body>\n'
                f'{rest.split("</style>", 1)[1]}\n</body>\n</html>\n')
    (out / "index.html").write_text(document)
    return out / "index.html"


# ------------------------------------------------------------------ animations


def _animate(trace_path: Path, target: Path) -> dict[str, Any]:
    trace = load_trace(trace_path)
    report = replay(trace)
    if not report.matches:
        raise DemoError(f"{trace_path.name} did not replay exactly: {report.mismatches[:3]}")
    frames = [_with_caption(frame, caption) for i, (frame, caption) in enumerate(zip(report.frames, report.captions))
              if i % FRAME_EVERY == 0 or i == len(report.frames) - 1]
    frames[0].save(target, save_all=True, append_images=frames[1:], loop=0, quality=WEBP_QUALITY, method=4,
                   duration=round(1000 * FRAME_EVERY / 35 / SPEEDUP))
    end = trace.end
    return {"score": end["score"], "outcome": end["outcome"], "kills": end["kills"], "file": target.name}


def _with_caption(frame: Any, caption: str) -> Image.Image:
    image = Image.fromarray(frame)
    canvas = Image.new("RGB", (image.width, image.height + CAPTION_H), (14, 16, 20))
    canvas.paste(image, (0, 0))
    ImageDraw.Draw(canvas).text((6, image.height + 5), caption[:52], fill=(230, 232, 236))
    return canvas


# ------------------------------------------------------------------ page fields


def _fields(summary: dict[str, Any], scenario: str, seed: int, scores: dict[str, dict[str, Any]],
            commander: list[dict[str, Any]]) -> dict[str, str]:
    test, trial, prov = summary["test"], summary["trial"], summary["provenance"]
    groups = test["groups"]
    defend, supreme = groups["defend_the_center"], groups["health_gathering_supreme"]
    obs = test["needless_observe"]
    total_obs = sum(v["observe"] for v in obs.values())
    total_dec = sum(v["decisions"] for v in obs.values())
    seeds = test["seeds"]
    best = max(scores, key=lambda v: scores[v]["score"])
    score_name = SCORES[scenario][0]
    return {
        "lede": escape(
            "Four players take the same Doom levels through one harness: random moves, four hand-written rules, "
            "one Qwen agent, and a Qwen commander with two specialists. Every decision is a typed, validated tool "
            "call, every episode replays exactly, and the numbers below come only from those recordings."),
        "meta": "".join(f"<span>{escape(m)}</span>" for m in (
            f"{test['episodes']} held-out episodes", f"seeds {seeds[0]}–{seeds[-1]}, never used for tuning",
            "model qwen3.8:27b, temperature 0", f"recipe {prov['frozen']['hash'][:12] if prov['frozen'] else '–'}")),
        "arena": "\n".join(_player(v, scores[v], scenario, seed, v == best) for v in VARIANTS),
        "arena_note": escape(
            f"The same unseen level (defend_the_center, seed {seed}) played by each agent, replayed from its recorded "
            f"button presses at {SPEEDUP}× speed. The strip under each screen shows the decision being carried out. "
            f"Score: {SCORE_TEXT[score_name]}, higher is better."),
        "results_title": escape(f"On {len(seeds)} unseen levels, simple rules still win"),
        "results_intro": escape(
            "Both Qwen agents play far above the random floor, but neither beats the hand-written scripted agent, and "
            "the two-specialist team does not beat the single agent. basic is only a smoke test: every agent that "
            "eventually aims and shoots gets the same time."),
        "takeaways": "\n".join(_takeaway(a, b) for a, b in (
            (f"{defend['react_single']['score']['median'] / defend['random']['score']['median']:.1f}×",
             f"the random floor on defend_the_center for the single Qwen agent "
             f"({_n(defend['react_single']['score']['median'])} vs {_n(defend['random']['score']['median'])} tics survived, medians)."),
            (_n(defend["scripted"]["score"]["median"]),
             "tics survived by the scripted agent on defend_the_center, the best of the four."),
            (f"{supreme['react_single']['successes']}/{supreme['react_single']['n']}",
             f"health_gathering_supreme levels survived to the end by the single Qwen agent; scripted also "
             f"{supreme['scripted']['successes']}/{supreme['scripted']['n']}, commander {supreme['commander']['successes']}/{supreme['commander']['n']}."),
        )),
        "headline_table": _headline_table(groups),
        "scores_chart": dot_plot(
            {s: {v: _seed_scores(summary, s, v) for v in VARIANTS if v in groups[s]}
             for s in ("defend_the_center", "health_gathering_supreme")},
            title="Score per unseen level (tick = median)", higher_is_better=True, unit="tics survived"),
        "success_chart": bars_with_intervals(
            {s: {v: (g["successes"] / g["n"], *g["success_ci95"]) for v, g in ((v, groups[s][v]) for v in VARIANTS)}
             for s in ("health_gathering_supreme",)},
            title=f"Survived to the end, with 95% interval (n = {len(seeds)})"),
        "observe_share": f"{total_obs / total_dec:.0%}",
        "observe_text": escape(
            f"The game waits between calls and every prompt already contains the current view, so the observe tool "
            f"can never show anything new. Its description says so. The agents called it anyway: {total_obs:,} of "
            f"{total_dec:,} decisions on the test levels, and about one in five on the dev levels too. Episodes that "
            f"ran out of their call budget had spent a fifth of it here."),
        "observe_table": _observe_table(obs, groups),
        "trial_intro": escape(
            "An Analyst LLM read the counted failures and 11 corrected decisions and proposed three lessons for the "
            f"single agent's prompt (policy {trial['candidate']}). Offline it looked like a clear win. On five fresh "
            "validation levels it survived shorter on most of them: it stopped calling observe and started turning "
            "back and forth on the spot instead."),
        "lessons": "\n".join(f"    <li>{escape(lesson)}</li>" for lesson in trial["lessons"]),
        "trial_points": "\n".join(_takeaway(a, b) for a, b in (
            (f"{trial['regression_passed'][trial['parent']]} → {trial['regression_passed'][trial['candidate']]}",
             f"of {trial['cases']} corrected decisions answered correctly (asked 3 times each)."),
            (f"{trial['worse_seeds']} of {len(trial['ab'])}",
             "validation levels where the new policy survived for less time."),
        )),
        "gate_verdict": escape(trial["gate_verdict"]),
        "human_decision": escape(trial["human_decision"] or "pending"),
        "human_note": escape(trial["human_note"] or ""),
        "trial_chart": paired_lines({row["seed"]: (row[trial["parent"]], row[trial["candidate"]]) for row in trial["ab"]},
                                    labels=(f"{trial['parent']} (no lessons)", f"{trial['candidate']} (3 lessons)"),
                                    title="Tics survived per validation level"),
        "timeline_intro": escape(_timeline_intro(commander)),
        "timeline": _timeline_svg(commander),
        "caveats": "\n".join(f"    <li>{escape(c)}</li>" for c in (
            "One model (qwen3.8:27b through Purdue GenAI Studio), three vizDoom scenarios, 10 test levels per cell: "
            "the 95% intervals are wide and most differences are pilot-sized.",
            "Scores on defend_the_center are survival within an equal budget of 150 LLM calls; both LLM agents ran out "
            "on some levels and then stood still.",
            f"Of the 11 corrections behind the improvement trial, {summary['corrections']['human']} were written by a "
            f"human reviewer and {summary['corrections']['assistant_drafted']} were drafted by an AI assistant from the "
            "ViZDoom scenario docs; they are labelled as such.",
            "A hosted model is not fully repeatable at temperature 0; regression cases are asked three times for that reason.",
        )),
        "recipe": prov["frozen"]["hash"][:12] if prov["frozen"] else "–",
        "repo": REPO,
    }


def _player(variant: str, score: dict[str, Any], scenario: str, seed: int, best: bool) -> str:
    return (f'<figure class="player{" best" if best else ""}">'
            f'<div class="screen"><img src="assets/{score["file"]}" width="320" height="262" '
            f'alt="{escape(variant)} playing {escape(scenario)}, seed {seed}" loading="eager"></div>'
            f'<figcaption><span class="agent"><i class="dot-{variant}"></i>{escape(variant)}</span>'
            f'<span class="score">{_n(score["score"])} <small>tics · {int(score["kills"])} kills</small></span>'
            f'<span class="what">{escape(ABOUT[variant])}</span></figcaption></figure>')


def _takeaway(big: str, text: str) -> str:
    return f"    <li><b>{escape(big)}</b><span>{escape(text)}</span></li>"


def _headline_table(groups: dict[str, Any]) -> str:
    head = "".join(f"<th>{escape(v)}</th>" for v in VARIANTS)
    rows = []
    for s in ("basic", "defend_the_center", "health_gathering_supreme"):
        name, higher = SCORES[s]
        medians = {v: groups[s][v]["score"]["median"] for v in VARIANTS}
        best = (max if higher else min)(medians.values())
        cells = "".join(
            f'<td{" class=\"win\"" if medians[v] == best else ""}>{_n(medians[v])} '
            f'<small>{groups[s][v]["successes"]}/{groups[s][v]["n"]}</small></td>' for v in VARIANTS)
        rows.append(f"<tr><td><code>{s}</code><br><small>{SCORE_TEXT[name]}, {'higher' if higher else 'lower'} is better</small></td>{cells}</tr>")
    return (f"<table><thead><tr><th>Scenario · median score, levels won</th>{head}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def _observe_table(obs: dict[str, Any], groups: dict[str, Any]) -> str:
    rows = []
    for v in (v for v in VARIANTS if v in LLM_VARIANTS):
        blind = sum(groups[s][v]["rejected_codes"].get("NO_ENEMY_IN_CONE", 0) for s in groups if v in groups[s])
        rows.append(f"<tr><td><span class=\"agent\"><i class=\"dot-{v}\"></i>{escape(v)}</span></td>"
                    f"<td>{obs[v]['observe']:,} of {obs[v]['decisions']:,}</td><td>{obs[v]['share']:.1%}</td><td>{blind}</td></tr>")
    return ("<table><thead><tr><th>Agent</th><th>observe calls</th><th>share</th><th>blind shots</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def _seed_scores(summary: dict[str, Any], scenario: str, variant: str) -> list[float]:
    return [scores[variant] for scores in summary["test"]["paired"][scenario].values() if variant in scores]


def _timeline(events: list[dict[str, Any]]) -> tuple[list[tuple[float, float, str]], list[float], int]:
    tic_of = {e["step"]: e["tic"] for e in events if e["event"] == "observe"}
    end = next(e for e in events if e["event"] == "episode_end")["tics"]
    starts = [(tic_of.get(e["step"], 0), e["mode"]) for e in events if e["event"] == "mode"]
    segments = [(t, starts[i + 1][0] if i + 1 < len(starts) else end, m) for i, (t, m) in enumerate(starts)]
    kills = [tic_of[e["step"]] + e["tics"] for e in events
             if e["event"] == "tool_exec" and e.get("kills_gained") and e["step"] in tic_of]
    return segments, kills, end


def _timeline_intro(events: list[dict[str, Any]]) -> str:
    segments, kills, end = _timeline(events)
    switches = sum(1 for a, b in zip(segments, segments[1:]) if a[2] != b[2])
    return (f"The commander team on the same level: {len(segments)} mode choices, {switches} switches between the Combat "
            f"specialist (aim, shoot) and the Navigator (turn to look around), {len(kills)} kills, then its health ran "
            f"out at tic {end:,}. The router only asks the commander again when the situation changes; in between, "
            f"the current specialist keeps going without an extra call.")


def _timeline_svg(events: list[dict[str, Any]]) -> str:
    segments, kills, end = _timeline(events)
    left, right, top = 20.0, WIDTH - 20.0, 44.0
    scale = (right - left) / end
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} 128" width="{WIDTH}" height="128" role="img">',
             f'<text class="ink title" x="{left}" y="20">Mode over the episode (tics), kills marked above</text>']
    for start, stop, mode in segments:
        parts.append(f'<rect class="m-{mode}" x="{left + start * scale:.1f}" y="{top + 12:.1f}" '
                     f'width="{max((stop - start) * scale, 1):.1f}" height="26"><title>{mode}: tic {start:,}–{stop:,}</title></rect>')
    for tic in kills:
        x = left + tic * scale
        parts.append(f'<line class="kill" x1="{x:.1f}" x2="{x:.1f}" y1="{top:.1f}" y2="{top + 9:.1f}" stroke-width="1.5"/>')
    for tic in range(0, end + 1, 250):
        x = left + tic * scale
        parts.append(f'<text class="muted small" x="{x:.1f}" y="{top + 56:.1f}" text-anchor="middle">{tic:,}</text>')
    legend_y = top + 76
    parts.append(f'<rect class="m-fight" x="{left}" y="{legend_y - 9}" width="12" height="12"/>'
                 f'<text class="muted small" x="{left + 18}" y="{legend_y + 1}">fight (Combat specialist)</text>'
                 f'<rect class="m-navigate" x="{left + 190}" y="{legend_y - 9}" width="12" height="12"/>'
                 f'<text class="muted small" x="{left + 208}" y="{legend_y + 1}">navigate (Navigator)</text>'
                 f'<line class="kill" x1="{left + 380}" x2="{left + 380}" y1="{legend_y - 9}" y2="{legend_y + 3}" stroke-width="1.5"/>'
                 f'<text class="muted small" x="{left + 388}" y="{legend_y + 1}">kill</text>')
    parts.append("</svg>")
    return "".join(parts)


def _n(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"

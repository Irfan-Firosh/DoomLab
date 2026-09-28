"""Small hand-written SVG charts (no plotting dependency). Colours come from CSS classes, so the same markup
works standalone (`standalone()` adds a light/dark style block) and inline in a themed page (the page styles
the classes). Numbers in labels are formatted for people; coordinates use one decimal.
"""

from __future__ import annotations

import math
from html import escape
from statistics import median

WIDTH = 720
LABEL_W = 150
RIGHT_PAD = 70
ROW_H = 26
PANEL_GAP = 20
HEADER_H = 34
AXIS_H = 26

STYLE = """
.bg{fill:#ffffff}.ink{fill:#1d2430}.muted{fill:#5b6573}.grid{stroke:#dde2e8}.axis{stroke:#9aa3ad}
.v-random{fill:#a4acb6;stroke:#a4acb6}.v-scripted{fill:#4f5b69;stroke:#4f5b69}
.v-react_single{fill:#2f6fde;stroke:#2f6fde}.v-commander{fill:#c7791b;stroke:#c7791b}
.v-v0{fill:#4f5b69;stroke:#4f5b69}.v-v1{fill:#2f6fde;stroke:#2f6fde}
text{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;font-size:12px}
.title{font-size:14px;font-weight:600}.small{font-size:11px}
@media (prefers-color-scheme: dark){
.bg{fill:#12161c}.ink{fill:#e4e8ee}.muted{fill:#9aa4b0}.grid{stroke:#2a313a}.axis{stroke:#56606b}
.v-random{fill:#6f7884;stroke:#6f7884}.v-scripted{fill:#b9c2cd;stroke:#b9c2cd}
.v-react_single{fill:#6ea2ff;stroke:#6ea2ff}.v-commander{fill:#e39d4a;stroke:#e39d4a}
.v-v0{fill:#b9c2cd;stroke:#b9c2cd}.v-v1{fill:#6ea2ff;stroke:#6ea2ff}}
"""


def standalone(svg: str) -> str:
    """A self-contained SVG file: adds the style block and a background that follows light/dark mode."""
    head, rest = svg.split(">", 1)
    return f'{head}><style>{STYLE}</style><rect class="bg" x="0" y="0" width="100%" height="100%"/>{rest}'


def dot_plot(data: dict[str, dict[str, list[float]]], *, title: str, higher_is_better: bool | dict[str, bool],
             unit: str | dict[str, str] = "tics") -> str:
    """One panel per scenario (own scale and direction): a dot per seed and a tick at the median per variant."""
    height = HEADER_H + sum(len(v) * ROW_H + AXIS_H + PANEL_GAP + 18 for v in data.values())
    parts = [_open(height), _title(title)]
    y = HEADER_H
    for scenario, variants in data.items():
        top = max(max(values) for values in variants.values() if values) or 1.0
        scale = _nice_max(top)
        higher = higher_is_better[scenario] if isinstance(higher_is_better, dict) else higher_is_better
        label = unit[scenario] if isinstance(unit, dict) else unit
        better = "higher is better" if higher else "lower is better"
        parts.append(_text(16, y + 12, f"{scenario}  ·  {label} ({better})", "muted small"))
        y += 18
        parts += _grid(y, len(variants) * ROW_H, scale)
        for i, (variant, values) in enumerate(variants.items()):
            cy = y + i * ROW_H + ROW_H / 2
            parts.append(_text(16, cy + 4, variant, "ink"))
            for v in values:
                parts.append(f'<circle class="v-{variant}" cx="{_x(v, scale):.1f}" cy="{cy:.1f}" r="4.5" fill-opacity="0.55"/>')
            if values:
                m = median(values)
                parts.append(f'<line class="v-{variant}" x1="{_x(m, scale):.1f}" x2="{_x(m, scale):.1f}" '
                             f'y1="{cy - 9:.1f}" y2="{cy + 9:.1f}" stroke-width="3"/>')
                parts.append(_text(WIDTH - RIGHT_PAD + 8, cy + 4, f"{_fmt(m)}", "ink small"))
        y += len(variants) * ROW_H
        parts += _axis(y, scale)
        y += AXIS_H + PANEL_GAP
    parts.append("</svg>")
    return "".join(parts)


def bars_with_intervals(data: dict[str, dict[str, tuple[float, float, float]]], *, title: str) -> str:
    """Success rate per variant with its 95% interval; (rate, low, high) as fractions."""
    height = HEADER_H + sum(len(v) * ROW_H + AXIS_H + PANEL_GAP + 18 for v in data.values())
    parts = [_open(height), _title(title)]
    y = HEADER_H
    for scenario, variants in data.items():
        parts.append(_text(16, y + 12, f"{scenario}  ·  success rate, 95% interval", "muted small"))
        y += 18
        parts += _grid(y, len(variants) * ROW_H, 1.0, percent=True)
        for i, (variant, (rate, low, high)) in enumerate(variants.items()):
            cy = y + i * ROW_H + ROW_H / 2
            parts.append(_text(16, cy + 4, variant, "ink"))
            parts.append(f'<rect class="v-{variant}" x="{LABEL_W:.1f}" y="{cy - 6:.1f}" '
                         f'width="{max(_x(rate, 1.0) - LABEL_W, 0):.1f}" height="12" fill-opacity="0.8"/>')
            parts.append(f'<line class="v-{variant}" x1="{_x(low, 1.0):.1f}" x2="{_x(high, 1.0):.1f}" '
                         f'y1="{cy:.1f}" y2="{cy:.1f}" stroke-width="1.5"/>')
            for end in (low, high):
                parts.append(f'<line class="v-{variant}" x1="{_x(end, 1.0):.1f}" x2="{_x(end, 1.0):.1f}" '
                             f'y1="{cy - 5:.1f}" y2="{cy + 5:.1f}" stroke-width="1.5"/>')
            parts.append(_text(WIDTH - RIGHT_PAD + 8, cy + 4, f"{rate:.0%}", "ink small"))
            parts.append(f"<title>{escape(variant)}: {rate:.0%} (95% interval {low:.0%}–{high:.0%})</title>")
        y += len(variants) * ROW_H
        parts += _axis(y, 1.0, percent=True)
        y += AXIS_H + PANEL_GAP
    parts.append("</svg>")
    return "".join(parts)


def paired_lines(pairs: dict[int, tuple[float, float]], *, labels: tuple[str, str], title: str,
                 unit: str = "tics survived") -> str:
    """Slope chart: each seed's score under two policies, joined by a line."""
    height = 320
    top_y, bottom_y = 70.0, height - 40.0
    left_x, right_x = 250.0, 470.0
    scale = _nice_max(max(max(p) for p in pairs.values()))

    def y_of(v: float) -> float:
        return bottom_y - (bottom_y - top_y) * v / scale

    parts = [_open(height), _title(title), _text(16, 52, unit, "muted small")]
    for tick in _ticks(scale):
        ty = y_of(tick)
        parts.append(f'<line class="grid" x1="{left_x - 60:.1f}" x2="{right_x + 60:.1f}" y1="{ty:.1f}" y2="{ty:.1f}"/>')
        parts.append(_text(left_x - 70, ty + 4, _fmt(tick), "muted small", anchor="end"))
    for x, label, cls in ((left_x, labels[0], "v-v0"), (right_x, labels[1], "v-v1")):
        parts.append(_text(x, height - 16, label, "ink", anchor="middle"))
    for seed, (a, b) in sorted(pairs.items()):
        cls = "v-v1" if b > a else "v-v0"
        parts.append(f'<line class="{cls}" x1="{left_x:.1f}" x2="{right_x:.1f}" y1="{y_of(a):.1f}" y2="{y_of(b):.1f}" '
                     f'stroke-width="2" stroke-opacity="0.8"/>')
        parts.append(f'<circle class="v-v0" cx="{left_x:.1f}" cy="{y_of(a):.1f}" r="4.5"/>')
        parts.append(f'<circle class="v-v1" cx="{right_x:.1f}" cy="{y_of(b):.1f}" r="4.5"/>')
    label_x = right_x + 40
    for seed, point_y, label_y in _spread_labels({s: y_of(b) for s, (_, b) in pairs.items()}, top_y - 10, bottom_y + 6):
        a, b = pairs[seed]
        parts.append(f'<line class="grid" x1="{right_x + 6:.1f}" x2="{label_x - 4:.1f}" y1="{point_y:.1f}" y2="{label_y - 4:.1f}"/>')
        parts.append(_text(label_x, label_y, f"seed {seed}: {_fmt(a)} → {_fmt(b)}", "muted small"))
    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------------------------ helpers


def _spread_labels(points: dict[int, float], top: float, bottom: float, gap: float = 15.0) -> list[tuple[int, float, float]]:
    """Label baselines near their points but at least `gap` apart, kept inside [top, bottom]."""
    ordered = sorted(points.items(), key=lambda kv: kv[1])
    ys: list[float] = []
    for _, y in ordered:
        ys.append(max(y + 4, ys[-1] + gap) if ys else y + 4)
    overflow = ys[-1] - bottom if ys else 0
    if overflow > 0:
        ys = [y - overflow for y in ys]
        for i in range(len(ys) - 2, -1, -1):
            ys[i] = min(ys[i], ys[i + 1] - gap)
    ys = [max(y, top) for y in ys]
    return [(seed, y, label_y) for (seed, y), label_y in zip(ordered, ys)]


def _open(height: float) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height:.0f}" '
            f'width="{WIDTH}" height="{height:.0f}" role="img">')


def _title(text: str) -> str:
    return _text(16, 22, text, "ink title")


def _text(x: float, y: float, text: str, cls: str, anchor: str = "start") -> str:
    return f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}">{escape(text)}</text>'


def _x(value: float, scale: float) -> float:
    return LABEL_W + (WIDTH - LABEL_W - RIGHT_PAD) * max(0.0, min(value, scale)) / scale


def _nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(value))
    return next(step * magnitude for step in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if step * magnitude >= value)


def _ticks(scale: float, count: int = 4) -> list[float]:
    return [scale * i / count for i in range(count + 1)]


def _grid(y: float, height: float, scale: float, percent: bool = False) -> list[str]:
    return [f'<line class="grid" x1="{_x(t, scale):.1f}" x2="{_x(t, scale):.1f}" y1="{y:.1f}" y2="{y + height:.1f}"/>'
            for t in _ticks(scale)]


def _axis(y: float, scale: float, percent: bool = False) -> list[str]:
    parts = [f'<line class="axis" x1="{LABEL_W:.1f}" x2="{WIDTH - RIGHT_PAD:.1f}" y1="{y:.1f}" y2="{y:.1f}"/>']
    for t in _ticks(scale):
        label = f"{t:.0%}" if percent else _fmt(t)
        parts.append(_text(_x(t, scale), y + 16, label, "muted small", anchor="middle"))
    return parts


def _fmt(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:,.0f}" if float(value).is_integer() or abs(value) >= 100 else f"{value:,.1f}"

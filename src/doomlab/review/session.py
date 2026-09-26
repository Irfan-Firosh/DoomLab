"""`doomlab review`: walk the shortlist one flagged decision at a time and record corrections.

Input and output are injected (`ask`, `say`) so the whole conversation is testable. Every answer is written
immediately, so quitting at any point loses nothing and the next session resumes after the last reviewed flag.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from doomlab.env.perception import describe
from doomlab.review.corrections import (
    LABELS, append_record, check_call, describe_expectation, load_records, next_case_id, parse_call, record, skipped,
)
from doomlab.review.flags import Flag
from doomlab.tools.registry import ToolCall

TARGET = 10
CONTEXT_STEPS = 5


def run_review(flags: list[Flag], store: Path, *, ask: Callable[[str], str] = input,
               say: Callable[[str], None] = print, target: int = TARGET) -> None:
    done = {r["key"] for r in load_records(store)}
    todo = [f for f in flags if f"{f.step.trace}#{f.step.step}" not in done]
    corrected = sum(r["action"] == "corrected" for r in load_records(store))
    if not todo:
        say(f"nothing left to review: {corrected} correction(s) saved in {store}")
        return
    say(f"{len(todo)} flagged decisions left ({len(flags) - len(todo)} already reviewed); "
        f"{corrected} correction(s) so far, target about {target}")
    for i, flag in enumerate(todo, start=1):
        say("")
        say(_card(flag, i, len(todo)))
        while True:
            choice = ask("[c] correct  [s] skip  [v] view the steps around it  [q] quit > ").strip().lower()
            if choice == "v":
                say(_around(flag))
                continue
            if choice in ("c", "s", "q"):
                break
            say("type c, s, v or q")
        if choice == "q":
            break
        if choice == "s":
            append_record(store, skipped(flag))
            continue
        rec = _correct(flag, store, ask, say)
        append_record(store, rec)
        corrected += 1
        say(f"saved {rec['id']}: {describe_expectation(rec['expect'])}  ({corrected} so far)")
        if corrected == target:
            say(f"that is the target of {target}; you can stop with q, or keep going")
    say(f"{corrected} correction(s) in {store}; run `doomlab regress` to test the current policy on them")


def _correct(flag: Flag, store: Path, ask: Callable[[str], str], say: Callable[[str], None]) -> dict:
    menu = "  ".join(f"{i}={label}" for i, label in enumerate(LABELS, start=1))
    label = ""
    while label not in LABELS:
        answer = ask(f"label ({menu}) > ").strip()
        label = LABELS[int(answer) - 1] if answer.isdigit() and 1 <= int(answer) <= len(LABELS) else answer
    fix = ""
    while not fix:
        fix = ask("fix, in one sentence > ").strip()
    corrected: ToolCall | None = None
    while True:
        text = ask("corrected call, e.g. go_to(target_id=12)  (Enter = none) > ").strip()
        if not text:
            break
        try:
            call = parse_call(text)
        except ValueError as exc:
            say(f"  {exc}")
            continue
        problem = check_call(call, flag.step)
        if problem:
            say(f"  not possible at that moment: {problem}")
            continue
        corrected = call
        break
    return record(flag, next_case_id(store), label, fix, corrected)


def _card(flag: Flag, i: int, total: int) -> str:
    s = flag.step
    where = f"{s.scenario} · seed {s.seed} · {s.variant}{f' ({s.mode})' if s.mode else ''} · step {s.step}"
    result = "ok" if s.ok else f"REJECTED {s.code}"
    lines = [f"[{i} of {total}] {where}", f"  why flagged: {flag.detail}", "  saw:"]
    lines += [f"    {line}" for line in describe(s.observation).splitlines()]
    lines.append(f"  did: {_call_text(s.call)} -> {result}: {s.message}")
    return "\n".join(lines)


def _around(flag: Flag) -> str:
    recent = flag.step.history[-CONTEXT_STEPS:]
    lines = ["  before it:"] + [f"    step {h.step}: {h.tool}({_args(h.args)}) -> {'ok' if h.ok else h.code}: {h.message}"
                                for h in recent]
    return "\n".join(lines if recent else ["  (this was the first decision)"])


def _call_text(call: ToolCall) -> str:
    return f"{call.name}({_args(call.arguments)})"


def _args(args: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in args.items())

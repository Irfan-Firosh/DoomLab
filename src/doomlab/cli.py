"""`doomlab` command line. Commands exit with code 2 until their schedule block lands."""

from __future__ import annotations

import argparse
import sys

VARIANTS = ("react_single", "commander", "scripted", "random")
SCENARIOS = ("basic", "defend_the_center", "health_gathering")

COMMANDS: dict[str, str] = {
    "preflight": "done",
    "run": "scripted and react_single ready; random on Day 2",
    "eval": "Day 2",
    "review": "Day 3",
    "improve": "Day 3",
    "replay": "done",
    "report": "Day 3",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doomlab", description="Agent harness for vizDoom")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="Check the model endpoint and record runs/preflight.json")
    run = sub.add_parser("run", help="Play one episode with a chosen variant")
    run.add_argument("--variant", choices=VARIANTS, required=True)
    run.add_argument("--scenario", choices=SCENARIOS, required=True)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--seeds", help="several seeds, e.g. 0-4 or 0,2,5 (overrides --seed)")
    evaluate = sub.add_parser("eval", help="Run a scenario x seed x variant suite")
    evaluate.add_argument("--split", choices=("dev", "validation", "test"), required=True)
    review = sub.add_parser("review", help="Step through an episode and record corrections")
    review.add_argument("episode")
    sub.add_parser("improve", help="Propose, validate and gate one policy patch")
    replay = sub.add_parser("replay", help="Rebuild a GIF from a saved trace")
    replay.add_argument("trace")
    sub.add_parser("report", help="Build metrics and charts from saved runs")
    return parser


def _preflight() -> int:
    import asyncio

    from doomlab.config import RUNS_DIR, ConfigError, load_settings
    from doomlab.llm.client import RCACClient
    from doomlab.llm.preflight import run_preflight

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"preflight: {exc}", file=sys.stderr)
        return 1

    async def go() -> dict:
        async with RCACClient(settings) as client:
            return await run_preflight(client, settings, RUNS_DIR / "preflight.json")

    report = asyncio.run(go())
    if report["error"]:
        print(f"preflight FAILED: {report['error']['message']}", file=sys.stderr)
    else:
        tc, th, ov = report["tool_calling"], report["thinking"], report["overlap_probe"]
        print(f"model listed      : {report['model_listed']}  ({report['model_id']})")
        print(f"tool call         : {tc['example_call']}  in {tc['latency_s']}s")
        print(f"thinking disabled : {th['disabled']}  (completion tokens {th['completion_tokens_default']} -> {th['completion_tokens_switched']})")
        print(f"usage reported    : {report['usage_reported']}")
        print(f"2-request overlap : {ov['overlap_s']}s  latencies {ov['latencies_s']}")
        print(f"frozen decoding   : {report['decoding_frozen']}")
    print(f"wrote {RUNS_DIR / 'preflight.json'}  ->  {'PASS' if report['ok'] else 'FAIL'}")
    return 0 if report["ok"] else 1


def parse_seeds(text: str) -> list[int]:
    """'0-4' -> [0..4], '0,2,5' -> [0, 2, 5]; ranges and lists can be mixed."""
    seeds: list[int] = []
    for part in text.split(","):
        start, _, end = part.strip().partition("-")
        seeds.extend(range(int(start), int(end) + 1) if end else [int(start)])
    return seeds


def _run(args: argparse.Namespace) -> int:
    import asyncio

    implemented = ("scripted", "react_single")
    if args.variant not in implemented:
        print(f"doomlab run: variant {args.variant!r} not implemented yet ({COMMANDS['run']})", file=sys.stderr)
        return 2
    seeds = parse_seeds(args.seeds) if args.seeds else [args.seed]
    try:
        results = asyncio.run(_run_episodes(args.variant, args.scenario, seeds))
    except Exception as exc:  # config problems and fatal LLM errors: explain and stop
        from doomlab.config import ConfigError
        from doomlab.llm.client import LLMError

        if isinstance(exc, (ConfigError, LLMError)):
            print(f"doomlab run: {exc}", file=sys.stderr)
            return 1
        raise
    _print_results(args.variant, args.scenario, results)
    return 0


async def _run_episodes(variant: str, scenario: str, seeds: list[int]) -> list:
    from contextlib import AsyncExitStack
    from datetime import datetime

    from doomlab.agents.scripted import ScriptedAgent
    from doomlab.config import RUNS_DIR
    from doomlab.env.doom import DoomSession
    from doomlab.runner import arun_episode
    from doomlab.trace import TraceWriter

    run_dir = RUNS_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    async with AsyncExitStack() as stack:
        make_agent = ScriptedAgent
        if variant == "react_single":
            make_agent = await _react_factory(stack, scenario)
        results = []
        for seed in seeds:
            with DoomSession(scenario, seed=seed) as session, TraceWriter(run_dir / f"{scenario}-s{seed}-{variant}.jsonl") as trace:
                results.append(await arun_episode(session, make_agent(), scenario=scenario, seed=seed, trace=trace))
        return results


async def _react_factory(stack, scenario: str):
    from doomlab.agents.react import ReactAgent
    from doomlab.config import RUNS_DIR, load_settings
    from doomlab.llm.budget import Budget
    from doomlab.llm.client import RCACClient
    from doomlab.llm.preflight import load_frozen_decoding

    settings = load_settings()
    decoding = load_frozen_decoding(RUNS_DIR / "preflight.json", settings.model_id)
    client = await stack.enter_async_context(RCACClient(settings))
    return lambda: ReactAgent(client, scenario=scenario, decoding=decoding, budget=Budget())


def _print_results(variant: str, scenario: str, results: list) -> None:
    if len(results) == 1:
        r = results[0]
        for s in r.steps:
            call = f"{s.tool}({', '.join(f'{k}={v}' for k, v in s.args.items())})"
            status = f"ok   {s.message}" if s.ok else f"REJECTED {s.code}: {s.message}"
            llm = f"  llm {s.llm_seconds:.1f}s {s.llm_tokens if s.llm_tokens is not None else '?'} tok" if s.llm_calls else ""
            print(f"step {s.step:<2} {call:<22} -> {status}  [{s.tics_used} tics]{llm}")
        llm = f"   llm calls {r.llm_calls}   tokens {r.tokens if r.tokens is not None else 'unknown'}   llm time {r.llm_seconds:.1f}s" if r.llm_calls else ""
        print(f"outcome: {r.outcome.upper()}   steps {len(r.steps)}   tics {r.tics}   kills {r.kills}   rejected calls {r.rejected}{llm}")
        print(f"trace: {r.trace_path}")
        return
    print(f"{'seed':<6}{'outcome':<14}{'steps':<7}{'tics':<6}{'rejected':<10}{'llm calls':<11}{'tokens':<8}{'llm s'}")
    for r in results:
        print(f"{r.seed:<6}{r.outcome:<14}{len(r.steps):<7}{r.tics:<6}{r.rejected:<10}{r.llm_calls:<11}{str(r.tokens):<8}{r.llm_seconds:.1f}")
    wins = sum(r.outcome == "success" for r in results)
    tics = sorted(r.tics for r in results)
    print(f"{variant} on {scenario}: success {wins}/{len(results)}   median tics {tics[len(tics) // 2]}"
          f"   rejected {sum(r.rejected for r in results)}   llm calls {sum(r.llm_calls for r in results)}")
    print(f"traces: {results[0].trace_path.rsplit('/', 1)[0]}/")


def _replay(trace_path: str) -> int:
    from pathlib import Path

    from doomlab.replay import load_trace, replay, write_gif

    path = Path(trace_path)
    if not path.exists():
        print(f"doomlab replay: no such trace {path}", file=sys.stderr)
        return 1
    trace = load_trace(path)
    print(f"scenario {trace.scenario} · seed {trace.seed} · agent {trace.agent} · {len(trace.steps)} steps")
    report = replay(trace)
    for step in trace.steps:
        call = f"{step.tool}({', '.join(f'{k}={v}' for k, v in step.args.items())})"
        bad = [m for m in report.mismatches if m.startswith(f"step {step.step}:")]
        print(f"step {step.step:<2} {call:<22} {len(step.buttons):>3} tics  {'MISMATCH' if bad else 'matches trace'}")
    for problem in report.mismatches:
        print(f"  ! {problem}")
    gif = write_gif(report.frames, report.captions, path.with_suffix(".gif"))
    print(f"replay: {'MATCHES' if report.matches else 'DOES NOT MATCH'} ({report.tics} tics, outcome {trace.end.get('outcome')})")
    print(f"gif: {gif}  ({len(report.frames)} frames, {gif.stat().st_size / 1e6:.2f} MB)")
    return 0 if report.matches else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "preflight":
        return _preflight()
    if args.command == "replay":
        return _replay(args.trace)
    if args.command == "run":
        return _run(args)
    print(f"doomlab {args.command}: not implemented yet ({COMMANDS[args.command]})", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

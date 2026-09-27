"""`doomlab` command line. Commands exit with code 2 until their schedule block lands."""

from __future__ import annotations

import argparse
import sys

VARIANTS = ("react_single", "commander", "scripted", "random")
SCENARIOS = ("basic", "defend_the_center", "health_gathering", "health_gathering_supreme")

COMMANDS: dict[str, str] = {
    "preflight": "done",
    "freeze": "done",
    "run": "done",
    "eval": "done",
    "review": "done",
    "regress": "done",
    "mine": "done",
    "improve": "Day 3",
    "replay": "done",
    "report": "Day 3",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doomlab", description="Agent harness for vizDoom")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="Check the model endpoint and record runs/preflight.json")
    freeze = sub.add_parser("freeze", help="Lock the current recipe into configs/frozen.json and print its hash")
    freeze.add_argument("--name", default="frozen-v0")
    run = sub.add_parser("run", help="Play one episode with a chosen variant")
    run.add_argument("--variant", choices=VARIANTS, required=True)
    run.add_argument("--scenario", choices=SCENARIOS, required=True)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--seeds", help="several seeds, e.g. 0-4 or 0,2,5 (overrides --seed)")
    evaluate = sub.add_parser("eval", help="Run a scenario x seed x variant suite")
    evaluate.add_argument("--split", choices=("dev", "validation", "test"), required=True)
    evaluate.add_argument("--variants", default=",".join(VARIANTS), help="comma list; default: all four")
    evaluate.add_argument("--scenarios", help="comma list; default: the benchmark three")
    evaluate.add_argument("--out", help="results folder; rerunning with the same folder resumes (default runs/eval-<split>)")
    evaluate.add_argument("--score-only", action="store_true", help="play nothing; rescore the traces already there")
    review = sub.add_parser("review", help="Correct flagged decisions from dev episodes (saved to corrections/)")
    review.add_argument("episode", nargs="?", help="one trace to review; default: every LLM episode in --from")
    review.add_argument("--from", dest="source", default=None, help="folder of dev traces (default runs/eval-dev)")
    regress = sub.add_parser("regress", help="Ask a policy what it would do at each corrected moment")
    regress.add_argument("--policy", default=None, help="policy file (default policies/v0.json)")
    regress.add_argument("--repeats", type=int, default=None, help="asks per case (default: the gate rules, 3)")
    mine = sub.add_parser("mine", help="Count recurring failure signatures across dev traces")
    mine.add_argument("--from", dest="source", default=None, help="folder of dev traces (default runs/eval-dev)")
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

    from doomlab.config import RUNS_DIR
    from doomlab.env.doom import DoomSession
    from doomlab.runner import arun_episode
    from doomlab.trace import TraceWriter
    from doomlab.variants import open_agent_maker

    from doomlab.freeze import current

    run_dir = RUNS_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    _, config_hash = current()
    async with AsyncExitStack() as stack:
        make_agent = await open_agent_maker(stack, (variant,))
        results = []
        for seed in seeds:
            with DoomSession(scenario, seed=seed) as session, TraceWriter(run_dir / f"{scenario}-s{seed}-{variant}.jsonl") as trace:
                agent = make_agent(variant, scenario, seed)
                results.append(await arun_episode(session, agent, scenario=scenario, seed=seed, trace=trace,
                                                  config_hash=config_hash))
        return results


def _print_results(variant: str, scenario: str, results: list) -> None:
    from doomlab.runner import SCORES

    score_name = SCORES.get(scenario, ("tics", False))[0]
    if len(results) == 1:
        r = results[0]
        for s in r.steps:
            call = f"{s.tool}({', '.join(f'{k}={v}' for k, v in s.args.items())})"
            status = f"ok   {s.message}" if s.ok else f"REJECTED {s.code}: {s.message}"
            llm = f"  llm {s.llm_seconds:.1f}s {s.llm_tokens if s.llm_tokens is not None else '?'} tok" if s.llm_calls else ""
            print(f"step {s.step:<3} {call:<24} -> {status}  [{s.tics_used} tics]{llm}")
        stop = f" (agent stopped: {r.stop_reason})" if r.stop_reason else ""
        llm = f"   llm calls {r.llm_calls}   tokens {r.tokens if r.tokens is not None else 'unknown'}   llm time {r.llm_seconds:.1f}s" if r.llm_calls else ""
        print(f"outcome: {r.outcome.upper()}{stop}   {score_name} {r.score:g}   steps {len(r.steps)}   tics {r.tics}   kills {r.kills}   rejected {r.rejected}{llm}")
        print(f"trace: {r.trace_path}")
        return
    print(f"{'seed':<6}{'outcome':<10}{score_name:<15}{'stop':<20}{'steps':<7}{'tics':<6}{'rejected':<10}{'llm calls':<11}{'tokens':<8}")
    for r in results:
        print(f"{r.seed:<6}{r.outcome:<10}{r.score:<15g}{(r.stop_reason or '-'):<20}{len(r.steps):<7}{r.tics:<6}{r.rejected:<10}{r.llm_calls:<11}{str(r.tokens):<8}")
    wins = sum(r.outcome == "success" for r in results)
    scores = sorted(r.score for r in results)
    print(f"{variant} on {scenario}: success {wins}/{len(results)}   median {score_name} {scores[len(scores) // 2]:g}"
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


def _eval(args: argparse.Namespace) -> int:
    import asyncio
    from contextlib import AsyncExitStack
    from pathlib import Path

    from doomlab.config import RUNS_DIR, ConfigError
    from doomlab.eval.harness import BENCHMARK, SPLITS, format_table, plan, run_jobs, score_jobs, write_results
    from doomlab.eval.scorers import summarize
    from doomlab.freeze import FreezeError
    from doomlab.llm.client import LLMError
    from doomlab.variants import open_agent_maker

    variants = tuple(v.strip() for v in args.variants.split(",") if v.strip())
    scenarios = tuple(s.strip() for s in args.scenarios.split(",")) if args.scenarios else BENCHMARK
    unknown = sorted((set(variants) - set(VARIANTS)) | (set(scenarios) - set(SCENARIOS)))
    if unknown:
        print(f"doomlab eval: unknown variant or scenario {unknown}", file=sys.stderr)
        return 2
    out_dir = Path(args.out) if args.out else RUNS_DIR / f"eval-{args.split}"
    jobs = plan(SPLITS[args.split], scenarios, variants)

    async def play(config_hash: str) -> None:
        async with AsyncExitStack() as stack:
            make_agent = await open_agent_maker(stack, variants)
            played, skipped = await run_jobs(jobs, out_dir, make_agent, config_hash=config_hash)
            print(f"played {played}, skipped {skipped} already done")

    if not args.score_only:
        try:
            config_hash = _check_recipe(args.split, out_dir)
        except FreezeError as exc:
            print(f"doomlab eval: {exc}", file=sys.stderr)
            return 2
        print(f"eval {args.split}: {len(jobs)} episodes -> {out_dir}  (rerun the same command to resume)")
        try:
            asyncio.run(play(config_hash))
        except (ConfigError, LLMError) as exc:
            print(f"doomlab eval: {exc}  (finished episodes are kept; rerun to resume)", file=sys.stderr)
            return 1
    episodes = score_jobs(jobs, out_dir)
    meta = {"split": args.split, "seeds": list(SPLITS[args.split]), "scenarios": list(scenarios),
            "variants": list(variants), "label": "pilot" if args.split == "dev" else args.split}
    csv_path, json_path = write_results(out_dir, episodes, meta)
    print(format_table(summarize(episodes)))
    missing = len(jobs) - len(episodes)
    print(f"\n{len(episodes)} episodes scored{f', {missing} not played yet' if missing else ''}"
          f"{' (dev split: pilot numbers, small samples)' if args.split == 'dev' else ''}")
    print(f"wrote {csv_path}  and  {json_path}")
    return 0


def _check_recipe(split: str, out_dir) -> str:
    """The current recipe's hash, after checking it may run here. The test split runs only on the frozen recipe."""
    from doomlab.eval.harness import check_folder
    from doomlab.freeze import FreezeError, current, load_frozen

    _, config_hash = current()
    frozen = load_frozen()
    matches = frozen is not None and frozen["hash"] == config_hash
    status = f"matches {frozen['name']}" if matches else "NOT the frozen recipe"
    print(f"recipe {config_hash[:12]}  ({status})")
    if split == "test" and not matches:
        raise FreezeError("the test split runs only on the frozen recipe; run `doomlab freeze` (and commit) first")
    if out_dir.exists():
        check_folder(out_dir, config_hash)
    return config_hash


def _freeze(name: str) -> int:
    from doomlab.freeze import FROZEN_PATH, current, write_frozen

    value, _ = current()
    if value["model"] is None:
        print("doomlab freeze: no passing preflight; run `doomlab preflight` first", file=sys.stderr)
        return 1
    frozen = write_frozen(value, name=name)
    model = value["model"]
    print(f"froze {name}: {frozen['hash']}")
    print(f"  model {model['model_id']}  temperature {model['temperature']}  max_tokens {model['max_tokens']}  "
          f"thinking {model['thinking']}")
    print(f"  budgets {value['budgets']['calls']}  pacing {value['rate']['requests_per_minute']}/min  "
          f"policy {value['policy']['version']} ({len(value['policy']['lessons'])} lessons)")
    print(f"  {len(value['code'])} behaviour files hashed -> {FROZEN_PATH}")
    return 0


def _review(args: argparse.Namespace) -> int:
    from pathlib import Path

    from doomlab.config import RUNS_DIR
    from doomlab.review.corrections import CORRECTIONS
    from doomlab.review.flags import shortlist
    from doomlab.review.session import run_review
    from doomlab.variants import LLM_VARIANTS

    if args.episode:
        paths = [Path(args.episode)]
    else:
        source = Path(args.source) if args.source else RUNS_DIR / "eval-dev"
        paths = sorted(p for p in source.glob("*.jsonl") if p.stem.rsplit("-", 1)[-1] in LLM_VARIANTS)
    if not paths:
        print("doomlab review: no LLM traces found; run `doomlab eval --split dev` first", file=sys.stderr)
        return 1
    try:
        flags = shortlist(paths)
    except ValueError as exc:
        print(f"doomlab review: {exc}", file=sys.stderr)
        return 2
    try:
        run_review(flags, CORRECTIONS)
    except (KeyboardInterrupt, EOFError):
        print("\nstopped; everything answered so far is saved")
    return 0


def _regress(args: argparse.Namespace) -> int:
    import asyncio
    import json
    from contextlib import AsyncExitStack
    from pathlib import Path

    from doomlab.config import ConfigError
    from doomlab.improve.gate import load_rules
    from doomlab.llm.client import LLMError
    from doomlab.policy import DEFAULT_POLICY, load_policy
    from doomlab.review.corrections import CORRECTIONS, cases
    from doomlab.review.regress import run_regression
    from doomlab.variants import open_llm_maker

    policy = load_policy(Path(args.policy) if args.policy else DEFAULT_POLICY)
    rules, _ = load_rules()
    repeats = args.repeats or rules.regression_repeats
    votes = min(rules.regression_votes_to_pass, repeats)
    saved = cases(CORRECTIONS)
    if not saved:
        print("doomlab regress: no corrections yet; run `doomlab review` first", file=sys.stderr)
        return 1

    async def go() -> list:
        async with AsyncExitStack() as stack:
            make = await open_llm_maker(stack, policy)

            def agent_for(case: dict):
                snap = case["snapshot"]
                agent = make(snap["variant"], snap["scenario"])
                return agent.specialist(snap["mode"]) if snap["mode"] else agent

            return await run_regression(saved, agent_for, repeats=repeats, votes_to_pass=votes)

    try:
        results = asyncio.run(go())
    except (ConfigError, LLMError) as exc:
        print(f"doomlab regress: {exc}", file=sys.stderr)
        return 1
    for r in results:
        print(f"{r['id']}  {r['author']:<9} {r['label']:<17} {r['expect']:<32} "
              f"{'PASS' if r['passed'] else 'FAIL'} {r['votes']}/{r['asked']}   {policy.version} chose {r['chose']}")
    passed = sum(r["passed"] for r in results)
    print(f"{policy.version} passes {passed}/{len(results)} cases ({votes} of {repeats} votes needed per case)")
    out = CORRECTIONS.parent / f"regress-{policy.version}.json"
    out.write_text(json.dumps({"policy": policy.version, "repeats": repeats, "votes_to_pass": votes, "passed": passed,
                               "total": len(results), "results": results}, indent=2) + "\n")
    print(f"wrote {out}")
    return 0


def _mine(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    from doomlab.config import REPO_ROOT, RUNS_DIR
    from doomlab.improve.miner import mine
    from doomlab.variants import LLM_VARIANTS

    source = Path(args.source) if args.source else RUNS_DIR / "eval-dev"
    paths = sorted(p for p in source.glob("*.jsonl") if p.stem.rsplit("-", 1)[-1] in LLM_VARIANTS)
    if not paths:
        print(f"doomlab mine: no LLM traces in {source}", file=sys.stderr)
        return 1
    try:
        report = mine(paths)
    except ValueError as exc:
        print(f"doomlab mine: {exc}", file=sys.stderr)
        return 2
    print(f"{report['episodes']} dev LLM episodes, {report['decisions']} decisions\n")
    print(f"{'signature':<20}{'occurrences':>12}{'episodes':>10}   by variant                      example")
    for s in report["signatures"]:
        variants = ", ".join(f"{k} {v}" for k, v in s["by_variant"].items())
        print(f"{s['name']:<20}{s['occurrences']:>12}{s['episodes']:>7}/{report['episodes']:<3}  {variants:<32}{s['examples'][0]}")
    out = REPO_ROOT / "improve" / "miner_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": str(source.relative_to(REPO_ROOT)) if source.is_relative_to(REPO_ROOT)
                               else str(source), **report}, indent=2) + "\n")
    print(f"\nwrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure:
        reconfigure(line_buffering=True)  # progress shows live even through `| tee`
    args = build_parser().parse_args(argv)
    if args.command == "preflight":
        return _preflight()
    if args.command == "freeze":
        return _freeze(args.name)
    if args.command == "replay":
        return _replay(args.trace)
    if args.command == "run":
        return _run(args)
    if args.command == "eval":
        return _eval(args)
    if args.command == "review":
        return _review(args)
    if args.command == "regress":
        return _regress(args)
    if args.command == "mine":
        return _mine(args)
    print(f"doomlab {args.command}: not implemented yet ({COMMANDS[args.command]})", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

# Game Agent Lab — Wednesday–Friday Solo Sprint Plan

Based on Game_Agent_Lab_PRD.md, version 6. One developer using Claude Code. This is an implementation plan; the project has not been built or benchmarked by this document.

Architecture board: https://whimsical.com/CnuFTUFBrcsPn8uqZfeR9v

**Target:** finish Friday with a working three-role game agent, one bounded policy-improvement trial, a fair baseline comparison, and a demo supported by real traces.

**Time assumption:** use 09:00–18:00 as an example local-time window. Shift the whole schedule around classes or work. Wednesday and Thursday include breaks at 10:40–10:55 and 14:50–15:05, plus lunch at 12:20–13:20. That leaves 7.5 hours for building, checks and daily reviews, or about 22.5 available work hours over three days. Friday includes hosted-model waiting, during which you can prepare documentation. This is an ambitious schedule; API latency or an unfamiliar environment can reduce the final sample size.

**Scope held fixed:** one MiniGrid task, one hosted model, Python/asyncio, symbolic observations, three online roles, one offline Failure Analyst, one candidate lesson patch, local JSONL traces, and a static report. Keep adaptive agent-count routing, extra models, vision, browser games, training, CUDA and a dashboard outside these sprints.

**Daily solo rhythm**

Treat your standup as a ten-minute decision note, not a meeting. Write it in `SPRINT_LOG.md` before opening Claude Code:

```text
Date:
Yesterday's evidence: command / trace / file / commit, or "starting today"
Today's one demo:
First task, and what proves it is done:
Biggest blocker and timebox:
What I will cut if I fall behind:
```

At the midday checkpoint, run the current vertical slice and choose one next task. At end of day, spend 30 minutes demonstrating it, saving evidence, committing the working state and writing the next morning's first task. Allow at most one implementation task in progress. Maintain three small lists: Today, Blocked, Done. A generated code file enters Done only after the corresponding behavior has been exercised.

## Wednesday — Sprint 1: a real, observable single-agent loop

**Sprint goal:** one hosted agent controls the game through a bounded executor, and you can replay what actually happened.

**Standup, 09:00–09:10**

Today's demo: "I can start one episode, watch the agent act, identify why it stopped, and replay it from a saved trace."

First risks: Purdue authentication/structured output and correct MiniGrid action semantics. Resolve these before writing multiple agent prompts. Keep the PRD and Whimsical views 01/02 open as references.

| Time | Ticket and implementation | Completion evidence |
| --- | --- | --- |
| 09:10–10:40 | **W1 — Preflight and environment.** Create repo/venv, install PRD dependencies, configure ignored credentials. Verify one actual model response and its usage fields. Reset/render DoorKey; manually exercise actions. Probe two concurrent requests. | `preflight.json` records verified model ID/backend, schema behavior, latency, usage availability and overlap. A local game reset and manual action work. |
| 10:55–12:10 | **W2 — Contracts and executor.** Define Snapshot/Proposal/ToolResult, decode partial observations, track inventory, implement primitive checks and the sole `env.step` call site. Establish shared client timeouts, limiter and budget accounting. Start JSONL events now. | A scripted action sequence creates truthful observation/action/result events. Invalid pickup is rejected; termination prevents further actions. |
| 12:10–12:20 | **Checkpoint.** Run the adapter and API probes from a clean terminal. Inspect the exact input the model will receive. | No hidden-grid data in the snapshot. Record the single biggest remaining blocker. |
| 13:20–14:50 | **W3 — Complete the first vertical slice.** Connect Goal Planner → schema validation → queued plan → one-action executor → observation/memory update → continue/replan/stop. Add basic failure feedback and hard episode limits. | One real `single` episode finishes with a classified outcome and bounded resource use. Completion can be failure; do not require a win before the harness is correct. |
| 15:05–16:20 | **W4 — Evidence and evaluation skeleton.** Implement deterministic observed memory, replay, terminal/call/action summaries and a runner that accepts explicit variant/seed/split. Add random-action sanity baseline; timebox a simple observed-state scripted baseline. | Replay checks observation hashes. Summary comes from saved events. A new episode resets memory. Label an incomplete scripted policy as partial. |
| 16:20–17:30 | **W5 — Development runs and buffer.** Exercise the target task; use DoorKey if integration is still blocking. Run `single` on development seeds 0–5, inspect one failure and fix the highest-impact implementation issue. | Up to six real development traces, measured episode time and a chosen task. Record any missing runs or reruns. These are baseline/debug traces, not the later frozen `multi_v0` improvement batch. |
| 17:30–18:00 | **Review and EOD.** Demonstrate run → trace → replay; save artifacts, commit and prepare Thursday's first ticket. | You can explain one action, its checked preconditions, actual outcome and memory update from the trace. |

**Wednesday EOD deliverables**

- [ ] Repo with setup instructions, `.env.example`, ignored secrets and dependency versions.
- [ ] `preflight.json` with real API evidence, including missing usage if applicable.
- [ ] Working adapter, schemas, executor, basic memory and `single` variant.
- [ ] `seeds.json`: dev 0–5, validation 100–105, test 1000–1009; test seeds unused for tuning.
- [ ] Real development traces and one replay; simple outcome/call/action summary.
- [ ] One written failure diagnosis and a latency estimate for the remaining runs.
- [ ] Commit checkpoint and Thursday's first task in `SPRINT_LOG.md`.

**Acceptance check:** `single` can complete a bounded episode without manual intervention; only observed outcomes enter memory; the saved record explains its exit. An authentic failure is acceptable evidence. A mocked response is not evidence of working Purdue access.

**Cutoff:** if access is unresolved after an hour, switch to clearly labeled fixtures for orchestration and record the live blocker. If the target game delays the vertical slice, use DoorKey. Do not begin the multi-agent scheduler while the single-agent execution path is broken.

**Claude Code handoff**

> Implement Wednesday only, in W1–W5 order. Keep one Python CLI and one environment writer. Demonstrate each boundary using a real response or action result before extending it. Build the trace writer alongside execution. I will inspect the observation boundary, state updates and stopping behavior. Finish with one runnable episode and replay; keep multi-agent and improvement work for Thursday.

## Thursday — Sprint 2: coordination, recovery and one improvement candidate

**Sprint goal:** Planner and Explorer really overlap, Reviewer waits for both, recovery works, and one evidence-derived lesson patch reaches validation or a recorded abstention.

**Standup, 09:00–09:10**

Yesterday's evidence: run Wednesday's episode/replay command. Ask: "Is the executor trustworthy? Is the target task fixed? What did the measured API latency imply for today's batch?"

Today's demo: "Two agents propose from the same snapshot, Reviewer selects one, and a failure produces a controlled recovery transition. I can show where the proposed lesson came from."

| Time | Ticket and implementation | Completion evidence |
| --- | --- | --- |
| 09:10–10:40 | **T1 — Parallel round.** Add Explorer and Reviewer contracts. Freeze one snapshot, reserve two proposal slots plus a held review slot, launch two proposers, join typed results, then review. Validate selected candidate identity before queuing actions. | A live trace shows overlapping proposer requests and Reviewer submission after both branch results. One failed proposer cannot silently cancel the other. |
| 10:55–12:10 | **T2 — Routing and integrity.** Finish `CONTINUE / PLAN / RECOVER / STOP`, failure consumption, stale-result rejection and recovery limits. Exercise budget race, bad candidate, branch timeout, mid-plan failure and terminal fixtures. | No overspend, stale commit or post-terminal action. A failed dependent action clears the queue; the same failure is not consumed repeatedly. |
| 12:10–12:20 | **Checkpoint.** Demonstrate a complete multi-agent episode and inspect actual request intervals. | Separate verified concurrency from a merely async-looking implementation. If this fails, use the afternoon to fix it before attempting improvement. |
| 13:20–14:50 | **T3 — Fair controls and eval runner.** Add `single_refine` through the shared harness. Complete paired seed scheduling, outcome/behavior/cost scoring and artifact summaries. Run small development pilots and freeze parent prompts/model/budgets. | `single`, `single_refine` and `multi_v0` all run with identical observation/execution boundaries and aggregate limits. Scorers handle success, game failure, API failure and missing usage. |
| 15:05–16:20 | **T4 — Improvement input and machinery.** Run frozen `multi_v0` on six dev seeds. Build the failure miner, bounded Analyst contract, lesson retrieval, policy registry and deterministic promotion gate. Use inference waiting for isolated offline modules; leave the online runtime frozen. | Parent traces identify an actionable failure class. Patch schema accepts dev-only evidence. The gate rejects a synthetic bad candidate and leaves the active version unchanged. |
| 16:20–17:30 | **T5 — One candidate and validation launch.** Invoke Analyst once on at most three evidence windows. Lint its 1–3-rule patch; run required fixtures. Freeze the validation manifest, then start six matched parent/candidate seed pairs. | `candidate_v1.json` with parent hash/evidence, or `no_candidate` with a real reason. Validation checkpoints completed pairs; no edits based on interim results. |
| 17:30–18:00 | **Review and EOD.** Show coordination/recovery evidence and the lesson diff. Commit the implementation and record remaining validation episodes. | Clear Friday starting state: what is frozen, what ran, what remains and whether promotion has been decided. |

**Thursday EOD deliverables**

- [ ] Three online roles and a real fork/join trace.
- [ ] One recovery or failure-handling trace; synthetic injections labeled separately.
- [ ] `single`, `single_refine`, `multi_v0`, and a functioning paired evaluation runner.
- [ ] Critical integrity fixtures passing, including memory/split isolation and policy pinning.
- [ ] Frozen parent policy and six parent development episodes, or an explicit incomplete batch.
- [ ] One candidate lesson patch or evidence-backed abstention; no fabricated learning result.
- [ ] Frozen promotion thresholds and validation manifest; started/completed pairs recorded.
- [ ] Working commit, validation checkpoint and a ten-minute Friday launch checklist.

**Acceptance check:** trace timestamps prove client overlap, the sole executor acts only on a checked selection, all variants share the same harness, and the candidate can be traced to development evidence. Live validation need not finish by Thursday EOD.

**Validation expectations:** twelve episodes can consume up to 72 minutes at the PRD's wall cap, plus small scheduling overhead. Start them before the final review if possible. Otherwise finish Friday morning. Keep runs resumable; do not rely on leaving the laptop running overnight.

**Cutoff:** at the midday checkpoint, prioritize broken coordination over the Analyst. At 16:20, use the PRD's one-candidate limit: freeze the proposed lesson or record insufficient evidence. If core runtime is still unstable, defer improvement explicitly and protect Friday's baseline comparison. A rejected lesson is an acceptable outcome; a broken executor is not.

**Claude Code handoff**

> Implement T1–T5 through the existing harness. Add atomic request reservations and demonstrate stale/failed branch handling. Implement the refinement baseline before declaring the multi-agent system ready for evaluation. Freeze the parent, generate at most one lesson patch from its dev traces, and apply the PRD's exact gate. Do not change validators, success rules or thresholds to make the candidate pass.

## Friday — Sprint 3: frozen experiments and an explainable demo

**Sprint goal:** turn the implementation into reviewable evidence: a recorded improvement decision, controlled comparisons, one diagnosed failure and a short demo.

**Standup, 09:00–09:10**

Ask: "Are all variants runnable? Is validation complete? Which policy is eligible for testing? What sample count fits today's measured latency?"

Today's demo: "Here is the system running, the comparison against the controls, the lesson's promote/reject decision, and one failure I can explain from the trace."

| Time | Ticket and implementation | Completion evidence |
| --- | --- | --- |
| 09:10–10:25 | **F1 — Finish validation and decide.** Resume remaining matched validation pairs. Apply frozen gates; record promote/reject/inconclusive. If no candidate was justified, record that outcome. | `gate_result.json`; active policy matches the decision. No tuning from validation results. |
| 10:25–10:40 | **F2 — Final experiment freeze.** Lock commit, environment/model versions, prompt/schema/lesson hashes, budgets, test seeds and per-seed variant order. Check resume behavior and output paths. | `run_manifest.json` and a declared run time limit. `multi_v1` enters test only after promotion. |
| 10:55–14:55 | **F3 — Held-out evaluation.** Run the three required variants across ten test seeds; add promoted `multi_v1` if applicable. Checkpoint every episode and complete paired seed blocks. Run non-LLM sanity baselines as well. | Raw records and visible failures, without silent retries or changed budgets. Thirty LLM episodes have a three-hour wall-cap upper bound; forty have four hours, excluding small overhead. |
| 12:10–12:20 | **In-run checkpoint.** Check API health, manifest consistency, completion count and estimated finish time. Do not inspect results to retune the policy. | A progress note and any infrastructure issue. Let the bounded runner continue through lunch; use waiting time for setup/docs text. |
| 15:05–16:20 | **F4 — Analyze.** Generate success counts/denominators and intervals, paired differences, calls/tokens/latencies, recovery counts and a role timeline. Inspect one representative failure. | `episodes.csv`, `paired_results.csv`, `summary.json`, `report.md`; claims link to episode IDs. Missing usage and incomplete runs remain visible. |
| 16:20–17:30 | **F5 — Package.** Finish reproduction commands and README, record a 30–45s replay/timeline clip, and link the Whimsical design. Verify a clean setup path without triggering another full benchmark. | Reviewable repo, demo, report, manifest and representative redacted traces. |
| 17:30–18:00 | **Final review and retrospective.** Run the demo, inspect reported denominators and save the working release checkpoint. Write what worked, what failed, and the next experiment. | An honest delivery status and one concrete follow-up backed by observed evidence. |

**Friday EOD deliverables**

- [ ] Reproducible source and setup instructions; no credentials committed.
- [ ] Recorded promote/reject/inconclusive/no-candidate decision and supporting artifacts.
- [ ] Frozen manifest, per-episode traces and complete planned-versus-finished run accounting.
- [ ] Ten matched test seeds, or an explicitly labeled smaller paired pilot.
- [ ] Baseline/multi-agent comparison; improved-policy comparison only when eligible.
- [ ] Success/failure, calls/tokens, latency and recovery evidence, including infrastructure failures.
- [ ] One diagnosed failure, a role timeline and a short replay clip.
- [ ] README linking the code, results and Whimsical board.

**Acceptance check:** another engineer can identify what ran, reproduce the configuration, see whether coordination helped, and understand why a lesson was accepted or rejected. The multi-agent system does not need to win to satisfy the engineering deliverable.

**Cutoff:** freeze before held-out testing. If a correctness bug appears, preserve the affected run, mark it invalid, fix it and start a new recorded experiment; do not patch silently and pool the results. If test outcomes influence a policy change, those seeds are no longer a fresh holdout for that revision. By 15:00, transition to reporting the completed matched subset and missing slots. Do not spend the demo/report window chasing additional favorable results.

**Claude Code handoff**

> Finish the frozen validation trial, record the gate result, then run the declared test matrix. Keep all submitted attempts and infrastructure failures visible. Generate the report from saved artifacts only. Prepare the README, replay and role timeline without changing the frozen policy. If the run is incomplete or an integrity check fails, report that explicitly and preserve the original records.

## Keep the three-day scope under control

| Situation | Decision |
| --- | --- |
| Only six work hours available per day | Keep the same dependency order. Shorten polish and optional work; protect the three online variants and report a paired pilot if needed. Improvement may remain an explicitly incomplete milestone. |
| Slow endpoint | Use measured durations, finish complete seed blocks, keep episode budgets equal and report fewer pairs if necessary. |
| No token usage returned | Report missing usage. Under the current PRD the candidate cannot pass the token gate, so promotion is inconclusive; the base-agent comparison can still run. |
| No actionable development failure | Analyst abstains. Save the evidence rather than writing a lesson and labeling it learned. |
| Candidate fails validation | Retain `v0`; report the failed hypothesis and run the core test matrix. |
| Core runtime still broken Thursday afternoon | Fix state/execution/coordination first; mark improvement incomplete. |
| Extra time remains | Improve a failure explanation or add one predeclared ablation. Avoid adding new infrastructure before delivery. |

**What you personally own:** inspect the observation boundary, sole game writer, router, shared budget reservations, evaluation splits and promotion decision. Ask Claude Code to explain the actual trace proving each property. These are the parts you should be able to discuss without reading generated code aloud.

**EOD log template**

```text
Sprint goal: met / partly met / blocked
Working command and commit:
Evidence files:
Tests or live checks completed:
Actual failure learned from:
What is still incomplete:
Frozen experiment/policy status:
First task tomorrow:
Scope cut, if any, and why:
```

The progression is deliberate: Wednesday establishes a trustworthy game loop; Thursday adds coordination and an evidence-derived candidate; Friday measures and explains the result.

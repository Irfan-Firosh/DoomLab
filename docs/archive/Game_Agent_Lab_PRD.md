# Game Agent Lab — Runtime, Evaluation and Controlled Self-Improvement

Version 6 · September 22, 2026 · Wednesday–Friday · One developer with Claude Code

**Build status:** implementation specification. The diagrams and this document are complete; the game harness, model calls, learning experiment and benchmark results have not been implemented or measured here.

**Whimsical architecture:** https://whimsical.com/CnuFTUFBrcsPn8uqZfeR9v

The board has four views: **01 episode routing**, **02 online agent round**, **03 offline improvement**, and **04 evaluation harness**. This version replaces the six-box overview with execution contracts, branching conditions, data ownership, measurable feedback loops and a bounded improvement experiment. The previous Eraser board is an older overview.

**1. Product and research objective**

Build a small game-playing agent system whose behavior can be inspected and improved from evidence. Two LLM roles independently propose short plans; a third selects a plan. Deterministic code executes, observes and routes the next step. A fourth, offline LLM role analyzes development failures and proposes a versioned lesson patch. Code tests that patch and either promotes it or keeps the existing policy.

The project asks two separate questions:

1. **Coordination:** does parallel proposal generation plus review outperform a simple single agent or a single agent given sequential refinement calls?
2. **Improvement:** does one evidence-derived lesson patch improve the same multi-agent system on unseen validation and test seeds?

The second comparison changes only the lesson artifact. It does not simultaneously change model, routing, action tools, game difficulty or evaluation budgets. A rejected patch is a valid result. Improvement is a measured outcome, not an acceptance requirement that encourages cherry-picking.

Use MiniGrid with symbolic observations. Start on `MiniGrid-DoorKey-6x6-v0`; target `MiniGrid-BlockedUnlockPickup-v0`. The target has dependency failures worth analyzing: an obstruction, a key, a locked door and an object to retrieve. Keep one task fixed for all reported comparisons. The sprint does not download or automate Iron Snout or MooMoo.io. Those require separate environment adapters later. [Task documentation](https://minigrid.farama.org/environments/minigrid/BlockedUnlockPickupEnv/)

**Scope and time:** the deeper design is an ambitious 18–24 focused hours over Wednesday–Friday, plus hosted API waiting. Reserve 6–8 hours each day. With a strict 18-hour ceiling, implement one improvement candidate, skip adaptive agent-count routing, and report a smaller paired pilot if inference is slow. Do not add a browser controller, visual model, web dashboard, GPU training, kernel work, distributed workers or a vector database to this sprint.

**2. Agent count, permissions and runtime topology**

| Role | Input | Output | May change | When it runs |
| --- | --- | --- | --- | --- |
| Goal Planner | Frozen observed facts, mission, inventory, recent failures, pinned lessons | Candidate A: subgoal, evidence references and 1–8 primitives | Its own candidate only | In parallel with Explorer |
| Explorer | Same factual snapshot, separate exploration/recovery instruction | Candidate B or typed abstention | Its own candidate only | In parallel with Planner |
| Reviewer | Frozen snapshot, candidate results and deterministic validation findings | Existing candidate ID or reject-all, short reason code and evidence | Its selection only | After both proposer results terminate |
| Failure Analyst | Up to three development failure windows, observed outcomes, parent lessons | One candidate patch with at most three short lesson rules | Proposed lesson artifact only | Offline, after development episodes |

There are **three online LLM roles and one offline LLM role**. At most two client requests run concurrently. The four roles may use the same hosted pretrained model, with separate prompts and structured outputs. Neither the game nor the model needs to run on a local GPU.

The Coordinator, Memory, Executor, Failure Miner, Scorers, Candidate Builder and Promotion Gate are ordinary Python functions. Naming these as additional agents would obscure what is actually happening. Claude Code helps implement the system and is not a runtime role.

The Coordinator owns mutable episode state. The Executor is the only component allowed to call `env.step()`. LLM outputs are proposals. No LLM writes canonical memory, edits source files, changes evaluation labels, increases budgets or sets the success flag.

**3. Where the system runs and what you install**

| Piece | Location | Responsibility |
| --- | --- | --- |
| MiniGrid, Coordinator, memory, executor, eval runner | Your laptop, one Python process | Game and all control logic |
| Four role prompts and schemas | Local versioned files | Define the custom agent implementation |
| Pretrained model inference | Purdue GenAI Studio API | Generate bounded JSON responses |
| JSONL traces, lesson versions, reports | Local files, selected examples in Git | Evidence and reproducibility |
| Whimsical | Design-time board | Explain architecture; not a gameplay dependency |
| Claude Code | Development environment | Implement and review modules with you |

Download Python 3.11+, Git, Claude Code if needed, and the packages below. No CUDA, PyTorch, model weights, Docker or paid GPU account is required for this version.

```bash
mkdir game-agent-lab
cd game-agent-lab
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install minigrid gymnasium numpy httpx pydantic pillow matplotlib python-dotenv pytest
```

Freeze package versions after preflight. Use your platform's equivalent activation command. Store the API key in an ignored `.env`; commit `.env.example` with placeholders only.

```dotenv
RCAC_BASE_URL=https://genai.rcac.purdue.edu
RCAC_API_KEY=REPLACE_LOCALLY
RCAC_MODEL=REPLACE_WITH_VERIFIED_ACCOUNT_MODEL_ID
```

Purdue uses Bearer authentication and exposes `/api/models` and `/api/chat/completions`. Its current model page recommends `qwen3.6:27b` for agentic workflows; verify account availability and a real schema-constrained response before selecting it. Freeze the exact returned ID and backend for comparisons. vLLM uses `response_format`; Ollama uses `format`. The published limit is 60 requests/minute/user; our shared limiter is 30/minute with at most two requests in flight. A rate-limited response can be JSON `null`, so validate the outer response before reading `choices`. These are published capabilities, not a completed account-access test. [API](https://docs.rcac.purdue.edu/services/genai/api/) · [Models](https://docs.rcac.purdue.edu/services/genai/models/)

Preflight must record model ID, backend, output-schema behavior, token-usage availability, request latency and a two-request overlap probe. Stop on authentication errors. If Purdue is unavailable, finish fixture-based orchestration and label live evaluation blocked; do not quietly substitute invented results or an unconfigured paid provider.

**4. State and information boundary**

Agents receive MiniGrid's partial observation, mission, facing direction, carried object and truthful action feedback. Convert visible cells into object/color/state fields. This is a symbolic planning experiment; screenshots are for human replay.

Use episode-relative coordinates. The adapter may instrument actual movement deltas and inventory to verify execution, but exposes the same limited feedback to every variant. Do not serialize the full grid, absolute hidden target coordinates, shortest paths or future simulator state into prompts. The renderer and scorer may inspect the environment internally; their privileged data must never flow back into the policy.

| State object | Fields and purpose | Writer / lifetime |
| --- | --- | --- |
| `ObservedFact` | Stable ID, relative cell, object/color/state, last-observed step, current/stale marker | Memory reducer / episode |
| `EpisodeMemory` | Observed map, verified inventory/interactions, visited positions, last 8 failures | Coordinator / reset each episode |
| `Snapshot` | Run/episode/round IDs, state version, facts, mission, inventory, recent outcomes, policy hash | Coordinator / immutable for one round |
| `PlanQueue` | Candidate ID, primitives, typed checks, cursor, selection version | Coordinator / until invalidated or exhausted |
| `FailurePacket` | Error code, attempted command, expected/actual outcome, fact/event IDs, repeat count | Router / bounded recent history |
| `BudgetLedger` | Attempted and reserved requests, primitive attempts, elapsed time, token totals | Coordinator / episode and run |
| `PolicyBundle` | Base prompts, schema hash, model config, lesson artifact, parent/policy hashes | Registry / immutable version |

Memory stores observations as facts and model subgoals as intentions in separate fields. A proposed pickup does not become an inventory update. Re-observation supersedes a stale map entry. Unknown cells remain unknown. Rotation alone does not count as spatial progress; revealing a previously unseen tile while turning does.

**5. The actual control loop: Whimsical 01**

The event loop evaluates routes in a fixed priority order. It does not call a model at every primitive action.

| Priority | Condition | Route and side effect |
| --- | --- | --- |
| 1 | Environment terminates or truncates | `STOP`; classify actual outcome |
| 2 | Wall/action cap reached, or fatal authentication/adapter failure | `STOP`; record separate exit reason |
| 3 | A new action failure, rejected round, repeated failure or stagnation event is pending | `RECOVER`; clear queue, append one failure packet, increment recovery counter |
| 4 | No pending failure, queue nonempty, next command's live checks pass, subgoal unfinished | `CONTINUE`; execute one primitive with zero LLM calls |
| 5 | Queue empty or verified subgoal completed | `PLAN`; freeze fresh snapshot and run the configured agent subgraph |
| 6 | Next queued command's live check fails | `RECOVER`; reject command without dispatch |

A model-request cap does not invalidate a still-valid queued plan: it can finish while action/time caps permit. If a new planning round cannot reserve its minimum calls, stop with `request_budget`. The board's budget gate means the budget required for the next transition, not an unconditional stop whenever no new calls remain.

After every dispatched primitive: record result, commit facts, increment state version, update progress counters, and route again. A selected plan is never a license to execute eight actions blindly. Stop immediately if the environment terminates halfway through a queue.

A simplified implementation skeleton:

```python
while True:
    route = choose_route(state)  # no LLM, fixed priority
    if route.kind == "STOP":
        return finish_episode(state, route.reason)
    if route.kind == "CONTINUE":
        result = executor.step_one(state.queue.peek(), state)
        state = reduce_verified_result(state, result)
        continue
    if route.kind == "RECOVER":
        state = consume_failure_once_and_clear_queue(state, route.failure)
        if state.consecutive_recoveries >= 3:
            return finish_episode(state, "recovery_exhausted")
    snapshot = freeze_snapshot(state)
    decision = await run_variant_round(snapshot, shared_client, ledger)
    state = commit_decision_or_pending_failure(state, decision)
```

This is a control-flow contract, not a complete runnable implementation. Ensure the same pending failure is consumed only once; otherwise the loop can increment its recovery counter repeatedly without performing a new round.

**6. Parallel proposal, join and review: Whimsical 02**

1. Freeze one snapshot and pin the episode's policy bundle. Generate candidate IDs in code.
2. Atomically reserve three model-call slots: one per proposer and one held for Reviewer. A lock protects reservation accounting. If three slots do not fit, end the full multi-agent episode; never silently downgrade it to single-agent.
3. Launch Goal Planner and Explorer with `asyncio.gather` or `TaskGroup`. Each receives the same facts and lesson retrieval results, but a different role instruction. They cannot see each other's current answer.
4. Convert expected HTTP/schema failures into typed branch results. Join after both finish, timeout or abstain. A failed proposer must not accidentally cancel a healthy proposer.
5. Reject stale episode/round/version IDs and invalid schemas. If no ready candidate survives, release the unsent Reviewer reservation and return a failure packet. If only one survives, Reviewer still evaluates it and the round is marked degraded.
6. Reviewer consumes the held slot and selects an existing candidate ID or rejects all. Code checks the selection belongs to the same snapshot and passed structural validation.
7. Commit the exact selected plan. Do not let Reviewer rewrite commands. The executor rechecks the next primitive against current facts before dispatch.

A candidate can contain actions whose preconditions become true after earlier actions. Validate the whole plan structurally, but check dynamic preconditions immediately before each action. Do not reject a later door toggle merely because the first action has not yet picked up its key. Conversely, do not assume an intermediate effect happened just because the plan predicted it.

**Reviewer rubric:** reject an immediate contradiction with known facts; otherwise prefer a feasible next step that advances the mission dependency. If direct progress lacks observed evidence, prefer a feasible information-gathering alternative. Break otherwise similar choices by shorter executable prefix. Output a reason code such as `DIRECT_PROGRESS`, `NEED_INFORMATION`, `RECOVERY_ALTERNATIVE`, `INVALID_PRECONDITION` or `INSUFFICIENT_EVIDENCE`, with fact IDs. These are selection instructions, not numeric ground truth. Correctness still comes from the environment and validators.

Both proposers may make the same mistake because they share a base model. Separate role prompts do not establish independence. Measure selection and disagreement; do not promise diversity as an outcome.

**Model-client boundaries:** one `httpx.AsyncClient`; global semaphore of 2; shared 30 RPM rolling limiter permitting a burst of 2; queue waits count against the episode deadline. Each role invocation has at most two HTTP attempts total: initial attempt plus either one transient retry or one schema repair, never an unbounded combination. Each attempt times out after 30 seconds or the remaining episode time, whichever is shorter. Honor Retry-After when present; otherwise use bounded jittered backoff. Record a client timeout as a submitted attempt even if the server may continue processing it.

Retries require an extra unreserved budget slot and cannot steal the held Reviewer slot. Release reservations for requests never submitted. Log reservation, submission and completion separately. Mark late responses stale and discard them. A full round's critical path is approximately `max(planner_time, explorer_time) + review_time + overhead`, including actual queue waits in reported wall time. Overlapping client requests do not prove concurrent GPU execution at the host.

**7. Action contracts and recovery semantics**

Supported primitives are `left`, `right`, `forward`, `pickup`, `drop`, `toggle`. Omit `done` as a policy action. MiniGrid's source implements pickup/drop/toggle even where an environment's documentation table is misleading; verify behavior against the pinned installed version. [Environment source](https://github.com/Farama-Foundation/Minigrid/blob/main/minigrid/minigrid_env.py)

| Action | Live checks | Verified outcome |
| --- | --- | --- |
| `left` / `right` | Valid heading and remaining action budget | Heading changes as expected; new visible tiles may be learned |
| `forward` | Current forward cell observed and traversable | Movement delta; report `NO_EFFECT` if it did not move |
| `pickup` | Hands empty; forward object observed and pickable | Carried object changes and observed cell changes |
| `drop` | Hands occupied; forward cell observed and empty | Carried object cleared; dropped object observed |
| `toggle` | Forward interactable object observed; door-specific key requirement when locked | Door/object state actually changes |

Unknown precondition evidence returns `NEED_OBSERVATION`. It does not invent a cell state. Code validates local semantics, not a hidden route to solve the task. Agents must still decide which obstacle to move, where to drop it, which object to approach and when to explore.

Increment `primitive_attempts` for dispatched actions and locally rejected primitive attempts; separately count actual `env.step` calls. This prevents free unlimited invalid actions. Schema-invalid model outputs spend request budget and trigger bounded recovery but are not fabricated game steps.

Failure codes are explicit: `SCHEMA_INVALID`, `STALE_RESULT`, `UNKNOWN_CANDIDATE`, `HANDS_FULL`, `FRONT_BLOCKED`, `NEED_KEY`, `NEED_OBSERVATION`, `NO_EFFECT`, `REPEAT_FAILURE`, `STAGNATION`, `MODEL_TIMEOUT`, `REVIEW_REJECTED`, `REQUEST_BUDGET`, `ACTION_BUDGET`, `WALL_BUDGET`, `AUTH_ERROR`, `ADAPTER_ERROR`.

The state version changes after every committed action result, including a no-effect result. A failure signature must therefore exclude version and timestamp: hash normalized relevant facts, inventory, command and failure code. Two occurrences of the same signature without verified progress trigger `REPEAT_FAILURE`.

Progress means a newly observed tile, first visit to a position, inventory change, or door/object state change. Track positions separately from orientation so left-right spinning cannot reset the counter. Eight primitive attempts without progress trigger `STAGNATION`. A recovery consumes its pending event, clears the queue and replans with structured feedback. Three consecutive recovery entries without progress end the episode. A verified progress event resets that recovery counter.

**Worked example, illustrative rather than measured:** the agent holds a ball blocking a door. Planner proposes `pickup` for the key; live validation returns `HANDS_FULL`. The executor does not pretend the pickup happened. Recovery preserves the ball in inventory and tells both proposers why the queue was discarded. Explorer proposes moving to an observed empty cell and dropping the ball before returning for the key. Reviewer can select that proposal. Only verified actions update memory. The later Failure Analyst can propose a lesson about freeing inventory before another pickup, citing this trace. This illustrates within-episode recovery and cross-episode improvement as two different loops.

**8. Structured messages and artifact contracts**

Use Pydantic models with `extra='forbid'`, enums and size limits. IDs and role ownership originate in code. The model echoes IDs for validation but cannot mint authority.

```json
{
  "episode_id": "dev-003",
  "round_id": 4,
  "state_version": 19,
  "candidate_id": "dev-003-r4-explorer",
  "role": "explorer",
  "status": "ready",
  "subgoal": "Free inventory before obtaining the key",
  "evidence_fact_ids": ["inventory-19", "front-cell-19"],
  "commands": [
    {"action": "drop", "requires": ["hands_full", "front_empty"]}
  ]
}
```

This is an illustrative message with fictional IDs, not a saved response. `requires` values come from a small fixed enum; avoid an arbitrary predicate language or Python `eval`. Evidence IDs must resolve, but an existing ID alone does not establish that the model interpreted it correctly.

A proposal may also include an optional typed `stop_when`: `inventory_is`, `door_state_is`, `at_observed_cell`, or `none`, with a target object/cell and expected value where required. Validate its target against known facts. Code evaluates it after actual outcomes; unknown evidence means not satisfied. If omitted, use `none` and replan at queue exhaustion or failure. Never infer subgoal completion by asking whether the free-text subgoal sounds achieved.

A `Review` includes the same IDs/version, `selected_candidate_id` or null, a reason enum and evidence IDs. It contains no replacement plan. A `BranchResult` is `ready | abstain | error`, with explicit error and timing fields. A `ToolResult` has attempted command, dispatch flag, actual outcome, verified deltas, next state version, reward, terminated/truncated flags and counters.

A `FailurePacket` cites exact trace event IDs and records expected versus actual effects. A `LessonPatch` has `parent_policy_hash`, cited development episode/event IDs, a failure category, and 1–3 proposed rules. Each rule has an ID, enum tags and a short instruction of at most 300 characters. Cap the entire lesson file at 900 instruction characters for the sprint. Store evidence/provenance alongside it but send only the bounded instructions to online agents.

**9. What self-improvement changes: Whimsical 03**

There are three different forms of change:

| Loop | Trigger | What changes | What stays fixed |
| --- | --- | --- | --- |
| Observation and execution | Every action result | Current facts and plan cursor | Policy bundle and model weights |
| Recovery | Failure or stagnation | Queue, failure history and next plan | Policy bundle and model weights |
| Offline improvement | Completed development batch | Candidate lesson artifact; promoted policy version if gate passes | Model weights, harness, evaluators and test split |

The offline loop follows evidence-driven verbal feedback ideas such as Reflexion, but adds a project-specific version registry and promotion gate. It is **policy/lesson improvement through context**, not gradient training or a new foundation-model architecture. The single-agent refinement control draws on iterative feedback/revision ideas such as Self-Refine. These are inspirations, not reproductions of the papers' results. [Reflexion](https://arxiv.org/abs/2303.11366) · [Self-Refine](https://arxiv.org/abs/2303.17651)

**One bounded candidate per sprint:**

1. Run parent policy `v0` on six development seeds. Keep successes as well as failures.
2. Failure Miner groups failures by deterministic signatures. Select the most frequent actionable class; break ties by failure-code order. Exclude authentication/outage errors from behavioral lessons. Capture at most three windows, each containing the failed plan, checks, nearby observations/actions and eventual outcome.
3. Failure Analyst receives those windows and the current lessons. It proposes one patch with at most three rules and exact evidence references. It may abstain if evidence is insufficient. It cannot read validation/test traces or invoke the game.
4. Candidate Builder validates source split, parent hash, length, allowed tags and citation existence, then creates immutable `candidate_v1.json`. A cited event is provenance, not proof of the proposed causal explanation. Keep the explanation explicitly a hypothesis until tested.
5. Run regression fixtures and paired live validation of `v0` and `v1` on six unseen validation seeds. Evaluate with the same model, task, budgets and seed order. The Analyst does not see validation feedback during this trial.
6. Promotion Gate returns `promote`, `reject` or `inconclusive` with machine-readable reasons. Promotion changes a registry pointer for **new runs only**. An active episode remains pinned to its original policy hash.
7. Freeze the accepted policy and launch test evaluation. Do not tune from test failures. A later improvement trial requires fresh validation and test splits.

If development runs produce no actionable failure, save `no_candidate: insufficient_evidence`. Do not manufacture a real-looking failure for the Analyst. Fixtures may exercise the pipeline, clearly labeled synthetic.

**Lesson retrieval:** keep a JSON file, not a vector database. Deterministically select at most two rules whose tags match current inventory/door facts or recent failure code; break ties by rule ID. Include the same retrieved text in all three online roles and trace the rule IDs. Start `v0` with no learned rules. Instructions are advisory; validators still enforce the fixed action semantics. This makes `v0` versus `v1` a narrow and interpretable intervention.

An example candidate could recommend choosing an observed empty drop location before attempting another pickup while carrying an obstruction. It must not hardcode seed-specific coordinates, read hidden state, relax the pickup validator or change the success definition. The candidate can still be wrong, which is why it goes through validation.

**10. Exact promotion gate**

Freeze these thresholds before generating the candidate. They are conservative engineering criteria for a small experiment, not statistical proof that the patch generalizes.

| Gate | Required result |
| --- | --- |
| Contract and provenance | Allowed lesson schema only; all evidence from development; parent hash matches |
| Harness regressions | All integrity fixtures pass; zero stale commits, budget overspend or unauthorized environment writes |
| Validation completeness | Six matched `v0`/`v1` pairs complete with usable traces; outages make the trial inconclusive |
| No observed success regression | No validation seed solved by `v0` becomes a failure under `v1` |
| Benefit | At least one additional success; **or** equal success count and at least 15% fewer mean model attempts on commonly successful seeds |
| Efficiency-route sample | At least three commonly successful seeds; otherwise the call-saving route is inconclusive |
| Request guard | Mean requests over all six seeds at most 110% of parent |
| Latency guard | Mean episode wall time over all six seeds at most 125% of parent |
| Token guard | Mean total reported tokens over all six seeds at most 125% of parent; missing usage makes promotion inconclusive |

Token usage and latency can be noisy on a shared endpoint. Retain every measurement and explain which gate rejected a candidate. Do not waive a threshold after seeing the result. Use a low, fixed decoding temperature where supported, but acknowledge this does not make hosted inference deterministic.

Keep `policies/v0.json`, `policies/candidate_v1.json`, `policies/registry.json`, `improvement/patch.json` and `improvement/gate_result.json`. A rejected candidate remains available for analysis but never becomes the active policy. If the serving model or base prompts changed between parent and candidate validation, invalidate the comparison and freeze a new experiment rather than attributing the difference to the lesson.

**11. Evaluation data flow: Whimsical 04**

A frozen manifest drives a seed-paired scheduler. Every variant goes through the same environment adapter, memory, action checks, recovery rules and trace writer. Scorers read recorded events and verified outcomes. No LLM decides whether the game was solved.

| Split | Seeds | Permitted use |
| --- | --- | --- |
| Development | `0–5` | Implementation, prompt tuning and Analyst evidence |
| Validation | `100–105` | One candidate promotion decision; no iterative tuning this trial |
| Test | `1000–1009` | Final frozen comparison only |
| Robustness, stretch | `2000–2004` | Separate disclosed perturbation suite; never mixed into clean score |

These are fixed proposed seed IDs, not evidence of unique layouts. Verify task initialization hashes after freezing the split manifest. Different seeds can generate the same small layout. Report duplicates, avoid claiming distinct-task generalization, and if enforcing unique layouts do it by a predeclared layout-hash procedure before any model outcomes are observed. Pin one environment version and task for the study.

**Required clean variants:**

| Variant | Round logic | Purpose |
| --- | --- | --- |
| `single` | One Goal Planner proposal, then code validation | Simplest practical LLM baseline |
| `single_refine` | Proposal → critique → revision, sequential, same agent | Control for three inference opportunities per round |
| `multi_v0` | Parallel Planner/Explorer → Reviewer; empty learned lessons | Coordination treatment |
| `multi_v1` | Identical to `multi_v0` with promoted lessons | Improvement treatment; only included if promotion passes |
| `random` | Seeded choice among locally admissible actions | Metric sanity and task floor |
| `scripted` | Small observed-state controller with no hidden-grid access | Whether simple task logic suffices; label partial if incomplete |

All LLM variants receive the same aggregate allowance of 36 request attempts, 128 primitive attempts and six minutes per episode. They share observed memory, failure feedback and recovery thresholds. `single` intentionally has cheaper rounds and can use more rounds within the same cap. `single_refine` and `multi_v0` each reserve three initial call slots. Use equivalent output-token ceilings for corresponding propose/revise stages; publish the actual totals. Equal requests are not equal tokens or FLOPs.

Create the per-seed variant order with a separate fixed scheduler seed. Interleave variants within each seed to reduce time-of-day effects. Reset memory and response history between episodes. Policy lessons remain fixed by treatment. Never feed one variant's trajectory into another. Keep a planned-episodes manifest so missing runs are visible.

**12. Scorers, metrics and denominators**

| Scorer | Exact measurement | Interpretation |
| --- | --- | --- |
| Outcome | Environment-confirmed success, normalized terminal reason, steps, native reward | Primary behavioral outcome |
| End-to-end reliability | Successful episodes / all scheduled episodes actually started | Includes API failures and budget exits; display their counts |
| Behavioral subset | Same score after explicitly excluding infrastructure-failed episodes | Secondary, labeled; never silently replace the primary denominator |
| Plan validity | Structurally valid ready proposals / all completed non-abstaining proposal responses | API failures and abstentions reported separately |
| Execution validity | Locally rejected primitive attempts / all primitive attempts | Identifies bad plans even if the game never receives them |
| Progress and loops | No-effect count, repeated signatures, stagnation/recovery entries | Whether actions change the world usefully |
| Recovery | Recoveries followed by verified progress within next 8 primitive attempts / eligible recoveries | Also report terminal success after recovery; these are distinct |
| Cost | Actual submitted model requests, retries, reported input/output/total tokens | Missing usage is null, not zero; include usage coverage |
| Latency | Request queue/network durations, round and episode wall time, p50/p95 with sample size | Shared-host delays included and separately visible |
| Coordination | Candidate selection by role, abstentions, reject-all, degraded rounds, stale discards | Describes how roles participate; not causal benefit by itself |
| Concurrency | Positive overlap of Planner and Explorer submitted-request intervals | Establishes client overlap, not backend GPU parallelism |
| Improvement | Paired success and cost deltas for `multi_v1` versus `multi_v0` | Only lesson file differs |

For two requests with start/end timestamps `(sA,eA)` and `(sB,eB)`, overlap is `max(0, min(eA,eB) - max(sA,sB))`. Record monotonic timestamps locally. Reviewer submission must follow both terminal branch results, not merely their initial request submission.

Give success counts and Wilson 95% intervals for each variant. For paired comparisons, publish a per-seed win/tie/loss table and paired differences. Ten seeds are a pilot-sized sample; do not turn one extra success into a robust general claim. Latency p95 from a handful of episodes is unstable, so include the raw distribution and sample size. Report actions/calls both across all episodes and on common successful seeds to expose early-failure cost artifacts.

No arbitrary weighted score mixes success with token cost for the main result. Show the tradeoff explicitly. A high-cost success and a cheap early failure are different outcomes.

A trace with corrupted IDs or an impossible action sequence is quarantined, never scored as a valid success. Its planned-run slot remains visible as a harness failure. Keep original and rerun IDs with the reason; report initial attempts separately from reruns rather than selecting the best result.

**13. Regression, recovery and ablation experiments**

These tests verify consequential boundaries, not implementation details copied into mocks.

| Fixture | Injected condition | Expected assertion |
| --- | --- | --- |
| Stale response | Return previous round/version after a newer snapshot | Result logged and discarded; no state/queue mutation |
| Budget race | Two branches try to reserve the last request | No overspend; normal multi round never starts without review capacity |
| Failed proposer | Explorer times out, Planner returns a valid candidate | Barrier terminates, Reviewer sees one candidate, round marked degraded |
| Bad Reviewer | Unknown candidate ID or malformed selection | No game action; bounded repair/recovery only |
| Mid-plan failure | First action does not produce predicted state | Queue cleared before dependent action executes |
| Inventory boundary | Attempt pickup with occupied hands | `HANDS_FULL`; inventory remains truthful |
| Terminal boundary | Game succeeds before remaining commands finish | No post-terminal `env.step` |
| Memory isolation | Start a new episode after a different seed | No previous map/failure history enters snapshot |
| Split isolation | Patch cites a validation or test trace | Candidate rejected before validation |
| Policy pinning | Registry changes during a running episode | Active episode keeps original hash |
| Promotion rejection | Candidate fails a fixture or validation threshold | Registry still points to parent; rejection reason recorded |

Keep API fixtures grounded in captured redacted real responses where possible. Mark synthetic failures clearly. Saved-response replay can test orchestration but cannot measure fresh model performance or live API latency.

**Optional live robustness:** suppress the first eligible `forward` action after primitive attempt 8 on five reserved seeds, using a wrapper that consumes a step and returns truthful no-effect feedback. If no eligible action occurs, mark perturbation not applied. Store the event schedule and hidden perturbation flag in evaluator logs, not policy inputs. Compare `multi_v0` and `single_refine` under the same rule. Different policies may reach different states at that time; this is matched perturbation policy, not identical counterfactual state. Keep clean and perturbed scores separate.

**Ablations after required runs:** no Reviewer (choose Planner if valid, otherwise Explorer); no Explorer (Planner plus Reviewer); no accumulated memory; no learned lessons (already `v0`); serial rather than parallel proposal submission. Change one factor at a time. Removing a role also changes calls; report that confound rather than claiming pure causal attribution. Do not add all ablations to a three-day critical path.

**14. Routing extensions and what is actually in the sprint**

Required routing is explicit `CONTINUE / PLAN / RECOVER / STOP` plus valid/error/abstain branch routing and promote/reject routing. The full multi-agent variant always uses both proposers and Reviewer for a new round. This keeps the coordination comparison interpretable.

A later `multi_adaptive` variant may call only Goal Planner on easy states, escalating to all three online roles when repeated failure, an unresolved dependency or an information gap is detected. Define those signals from observable facts, freeze thresholds on development data and compare with `multi_v0`. Do not route based solely on a model's uncalibrated self-reported confidence. Keep this extension out of Friday's mandatory comparison: otherwise a changed router would confound the lesson experiment and add implementation risk.

A genuinely trained router or controller is a later milestone: label observed snapshots with outcomes from successful traces, train on development data, and evaluate call savings and task success on fresh held-out tasks. CUDA practice begins only when a local or self-hosted workload exists and profiling identifies a real operator bottleneck. Client code cannot modify Purdue's hosted model kernels.

**15. Budgets and evaluation runtime**

| Budget | Default |
| --- | --- |
| Primitive attempts per episode | 128; environment's own limit also applies |
| Model attempts per episode | 36 total across all online roles, retries and repairs |
| Episode wall deadline | 360 seconds, including rate-limit waits |
| Commands per proposal | 1–8 |
| Consecutive recoveries without progress | 3 |
| Request concurrency | 2 globally; one active episode at a time |
| Rate limiter | 30 submitted requests/minute/user for this application |
| Offline Analyst invocations | 1, with at most one additional retry/repair attempt |
| Improvement candidates | 1 |
| Validation maximum | 12 episodes × 36 = 432 submitted model attempts |
| Required test maximum | 30 episodes × 36 = 1,080 attempts |
| Added promoted-policy test maximum | 10 episodes × 36 = 360 attempts |

The three baseline test variants can take up to 180 minutes at the episode wall cap; adding the promoted policy raises that to 240 minutes. Actual runs may finish much sooner. Validation can take up to 72 minutes. These are conservative serial-episode upper bounds; API outages and preparation still require attention. Record Wednesday's measured latencies to choose a realistic Friday window.

Reserve up to three hours of Friday for core live tests, with a fourth hour only if the promoted-policy comparison is ready and time permits. Run complete seed blocks, checkpoint each episode and stop at the declared run budget. If fewer than ten matched seeds finish, publish the matched subset and all incomplete slots as a pilot. Do not reduce budgets for one variant or hide slow/failing seeds. Remove optional robustness, adaptive routing and dashboard polish first.

Token output ceilings are chosen in preflight and frozen before held-out evaluation. The shared Purdue API is not assumed to have a public per-token price; measure tokens and latency rather than inventing dollar savings. Log offline candidate-generation and validation costs separately from online episode cost.

**16. Trace format, replay and report artifacts**

Use append-only JSONL with a shared event envelope: `run_id`, `episode_id`, `event_id`, `parent_event_id`, monotonic time, task/seed/split, variant, policy/model IDs, round, state version and event type.

Required event types: `episode_started`, `snapshot_frozen`, `budget_reserved`, `model_submitted`, `model_finished`, `branch_failed`, `barrier_completed`, `candidate_validated`, `review_selected`, `command_rejected`, `action_dispatched`, `action_result`, `memory_committed`, `recovery_entered`, `stale_discarded`, `episode_finished`. Improvement adds `patch_proposed`, `patch_linted`, `validation_finished`, `gate_decided`, `policy_promoted`.

Store role prompts or their reproducible hashes, short output summaries, exact parsed commands, validation findings, actual token-usage fields and redacted errors. Keep credentials and Authorization headers out. Never invent long reasoning transcripts for a demo. Include small facts/subgoals/evidence references, which are sufficient to explain selection.

Replay saved actions against the same environment version and seed, checking observation hashes. Deterministic replay verifies the trace and renderer. A saved-response mode is explicitly labeled and never used to claim live performance.

The manifest contains code commit, package versions, model ID/backend, decoding settings, prompt/schema/lesson hashes, task config, seed splits, scheduler seed, budgets and perturbation rule. Hash JSON with a deterministic serializer. Persist the exact policy artifact selected for every episode.

Outputs: `episodes.csv`, `summary.json`, `paired_results.csv`, `run_manifest.json`, `gate_result.json`, `report.md`, role timeline and a short replay. The report reads artifacts; it must not trigger new inference requests.

**17. Wednesday–Friday implementation and end-of-day evidence**

| Day | Required implementation | End-of-day deliverables and gate |
| --- | --- | --- |
| Wednesday, 6–8h | Install; real API/schema probe; partial-observation adapter; typed actions and results; single writer; basic memory; `single`; trace/replay; seed manifest | One real bounded episode with truthful outcomes, five or six development traces, `preflight.json`, a replay and measured latency. Manual action checks pass. If BlockedUnlockPickup blocks progress, use DoorKey consistently. |
| Thursday, 6–8h | Parallel Planner/Explorer; Reviewer; atomic budgets; explicit router/recovery; `single_refine`; critical fixtures; failure miner and one Analyst patch; begin paired validation | One real overlapping proposal round, one visible disagreement or failure, three online variants, candidate artifact or evidence-backed abstention, integrity-test results and frozen validation gate. No dashboard. |
| Friday, 6–8h | Finish one validation trial; record promote/reject; freeze policies; run matched tests; analyze outcomes/costs/failures; produce timeline and demo | Promotion record even if rejected, honest ten-seed results or labeled paired pilot, raw traces/config, comparison report, code README, 30–45s clip and Whimsical board. |

Suggested Wednesday allocation: 1h preflight, 2h adapter/contracts, 1.5h single agent and memory, 1h traces/replay, 0.5–2.5h buffer. Thursday: 2h parallel round, 1h routing/tests, 1h refinement control, 1.5h improvement artifact and gate, 0.5–2.5h buffer/validation. Friday: 0.5–1h freeze/validation completion, 2–4h live eval window, 1h analysis, 1.5h documentation/demo. Use API waiting for documentation work, not tuning already frozen prompts.

**Friday done means:** online agents and executor work with correct boundaries; traces expose their behavior; one improvement trial reaches a recorded decision or explicit evidence/access blocker; comparisons are reproducible. It does not mean the multi-agent system must win or the candidate must be promoted.

If basic execution is unstable Thursday afternoon, preserve the core three-agent comparison and report improvement as incomplete. Be explicit about the missed gate. Do not rename a handwritten lesson as an autonomous learned result. This is the fallback, not a promise that every extension fits 18 hours.

**18. Repository and node-to-code mapping**

| Module | Board nodes / responsibility |
| --- | --- |
| `agentlab/env_adapter.py` | Partial observation, movement/inventory feedback, task outcome normalization |
| `agentlab/schemas.py` | Snapshot, Proposal, Review, BranchResult, ToolResult, FailurePacket, LessonPatch |
| `agentlab/coordinator.py` | Main state machine, snapshot freezing, fork/join, commit decisions |
| `agentlab/router.py` | Fixed-priority routes, failure signature, stagnation and recovery counters |
| `agentlab/executor.py` | Primitive checks and sole `env.step` call site |
| `agentlab/memory.py` | Deterministic verified-fact reducer and episode reset |
| `agentlab/model_client.py`, `budget.py` | Purdue adapter, shared HTTP/limiter, deadline, atomic reservations |
| `agentlab/agents/planner.py`, `explorer.py`, `reviewer.py` | Three online contracts |
| `agentlab/variants.py` | Single, refinement and fixed multi-agent round implementations |
| `agentlab/improve.py` | Failure Miner, Analyst invocation, candidate construction, immutable registry |
| `agentlab/evaluate.py`, `scorers.py`, `promotion.py` | Split checks, paired scheduler, deterministic metrics, promotion decision |
| `agentlab/trace.py`, `replay.py`, `report.py` | Events, reproducible rendering, reports |
| `prompts/`, `policies/`, `configs/`, `tests/` | Versioned roles, lessons, experiment manifests and critical fixtures |

Suggested CLI contract, to implement rather than assume already exists:

```bash
python -m agentlab preflight
python -m agentlab run --variant single --split dev
python -m agentlab run --variant multi_v0 --split dev
python -m agentlab improve propose --from runs/dev --parent policies/v0.json
python -m agentlab improve validate --candidate policies/candidate_v1.json
python -m agentlab improve decide --validation runs/validation
python -m agentlab evaluate --config configs/final.json
python -m agentlab report --run runs/final
python -m agentlab replay --episode runs/example/episode.jsonl
```

Use plain Python, Pydantic and asyncio for this sprint. An orchestration framework is optional later; it does not replace explicit state ownership, validators or evals. JSON files are enough for policy storage and manifests. Prefer a small codebase whose decisions you can explain over adding services that do no necessary work.

**19. Claude Code handoff and ownership**

Give Claude Code this document and build vertical slices, not all nodes at once:

1. Implement environment adapter, schemas, executor and one real `single` episode. Verify pickup/drop/toggle semantics and actual API response fields. Capture redacted real fixtures.
2. Add memory and the fixed-priority router. Explain why intended actions cannot update observed state, why state versions differ from failure signatures, and how pending failures are consumed once.
3. Add Planner/Explorer fork/join and Reviewer. Demonstrate submitted-request overlap and Reviewer ordering. Demonstrate budget reservation under contention.
4. Add `single_refine` through the same harness. Keep baseline differences limited to planning subgraphs.
5. Add one offline lesson patch, split/provenance validation and deterministic promotion gate. Show a rejected candidate leaves the registry unchanged.
6. Freeze the manifest, run paired evaluations and report the actual results. Never edit the frozen policy after viewing test outcomes.

Ask the coding agent to show one real event trace at each milestone and explain the remaining failure modes. You should personally understand and inspect the router, budget ledger, sole writer boundary, split isolation and gate. These are the engineering decisions you will discuss with interviewers.

**20. What to demonstrate publicly**

A strong clip shows a real observation, two concurrently generated proposals, the Reviewer's selected candidate, an actual action failure and the recovery transition. Then show the specific lesson diff, its promotion/rejection decision and the paired results. Every claim should link to a trace or table.

A useful portfolio statement would be: built and evaluated a bounded multi-agent controller with parallel proposals, verified execution and evidence-driven policy updates; measured the reliability, token and latency tradeoffs against a sequential refinement control. Add numbers only after measuring them. Do not claim novel model training, general game intelligence or automatic recursive self-improvement.

The engineering substance is the closed feedback loop, strict state ownership, failure handling, evaluation isolation and honest tradeoffs. The number of agents is just one implementation choice.

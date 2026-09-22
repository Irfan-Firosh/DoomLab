# DoomLab — Design Spec

Date: 2026-09-22 · Status: approved design, pending spec review · Owner: solo developer with Claude Code

Diagram (Lucid, 2 pages): https://lucid.app/lucidchart/cfc18bb2-f111-478e-a9fd-f9d1de1d6a1d/edit
Previous MiniGrid design (superseded, reference only): `docs/archive/`

## 1. Purpose

A portfolio project that demonstrates, with measured evidence, the skills named in current AI/agent engineer postings (Agent Integrator, Serval, Traversal, Machinify, Lynton, Guild.ai, Hedra):

| Posting theme | DoomLab evidence |
|---|---|
| Orchestration engine / agentic loop | Custom typed state-graph runtime (later ported to LangGraph) |
| Single- vs multi-agent topologies, routing | `react_single` vs `commander` + specialists on the same benchmark |
| Tool calling / MCP, tool-call accuracy | Typed vizDoom tools with MCP-compatible schemas; MCP server in week 2; tool-validity metrics |
| Evals first: harness, benchmarks, trajectory evals | Scenario × seed suite, deterministic scorers, trajectory metrics |
| Feedback loops from human corrections | Review CLI → corrections → regression cases + improvement evidence |
| Diagnose failure → change system → prove metric moved | Failure miner → Analyst patch → paired A/B → promotion gate |
| Memory/state, recovery, observability, replay, autonomy gates | Verified-fact memory, recovery routing, span traces, GIF replay, human approval gate |

Success is honest, reproducible evidence. The multi-agent topology does not have to win; a rejected patch is a valid result.

## 2. Verified environment facts (spike, 2026-09-22)

- `vizdoom==1.3.1` installs on macOS arm64 / Python 3.12 and runs headless. Bundled scenarios include `basic`, `defend_the_center`, `health_gathering`, `deadly_corridor`, `my_way_home`, `take_cover`, `defend_the_line`.
- `set_labels_buffer_enabled(True)` yields per-object labels: `object_name`, `object_id`, screen box, and world position. The player itself appears as `DoomPlayer` and must be filtered.
- Purdue RCAC `qwen3.6:27b` is listed at `/api/models` and supports OpenAI-style native `tools`: a probe returned `turn_to(target_id=7)` in 3.2 s with `usage` reported. Reasoning ("thinking") output is on by default and dominated completion tokens; it must be capped or disabled via decoding config.
- `.env` sets `RCAC_BASE_URL` ending in `/api`; the client must normalize this (no `/api/api/...`).

## 3. Architecture

```
eval harness ─► episode runner ─► graph engine ─► agents (LLM) ─► tool validator ─► tool executor ─► vizDoom
                     ▲                                                                   │
                     └──────── memory (verified facts) ◄── verifier ◄────────────────────┘
                                         └──► trace spans (JSONL) ─► scorers / replay / review CLI
```

### 3.1 Units

| Unit | Responsibility | Depends on |
|---|---|---|
| `env/doom.py` | Create/reset scenario with seed, sync PLAYER mode, headless; expose raw state; **sole `make_action` caller lives in executor** | vizdoom |
| `env/perception.py` | Labels buffer + game variables → `Fact`s in agent-relative terms (bearing°, distance, visible, id, kind). Filters player; never exposes non-visible objects | schemas |
| `tools/registry.py` | Tool specs (name, JSON schema, preconditions, allowed roles). Exports OpenAI `tools` payload and MCP-compatible definitions | schemas |
| `tools/executor.py` | Validate args + preconditions against memory, translate a tool into button sequences over N tics, call `make_action`, return `ToolResult` with verified deltas | env, registry |
| `memory.py` | Immutable episode memory: facts, last-seen enemies/items, health/ammo history, recent failures | schemas |
| `graph/engine.py` | Minimal typed state-graph: nodes, conditional edges, step limit, per-node checkpoint to trace | schemas, trace |
| `graph/router.py` | Deterministic routing: STOP / RECOVER / CONTINUE / PLAN with fixed priority | memory |
| `agents/` | `react` (all tools), `commander` (classifies situation → specialist), `navigator` (move, go_to, use), `combat` (turn_to, attack), `analyst` (offline) | llm client, registry |
| `llm/client.py` | RCAC client: httpx async, base-URL normalization, semaphore 2, 30 rpm limiter, ≤2 attempts, timeout, usage capture, redacted errors | config |
| `llm/budget.py` | Per-episode request/token ledger with atomic reservations | — |
| `trace.py` | Append-only JSONL spans: run › episode › step › llm_call / tool_call, with parent IDs and monotonic timing | schemas |
| `replay.py` | Deterministic re-execution by seed + recorded button sequence; GIF export | env |
| `eval/harness.py`, `eval/scorers.py` | Suite × seeds × variants scheduler; outcome/trajectory/cost metrics from traces only | trace |
| `review/cli.py` | Step through an episode, tag a step (label enum + free-text fix + corrected tool call), write `Correction` | trace |
| `improve/` | Failure miner, Analyst invocation, candidate builder, regression-from-corrections, promotion gate, policy registry | eval, review |
| `cli.py` | `doomlab preflight | run | eval | review | improve | replay | report` | all |

### 3.2 Tools (initial set)

| Tool | Args | Preconditions (code-checked) | Verified result |
|---|---|---|---|
| `observe` | — | — | refreshed facts |
| `turn_to` | `target_id` | target visible in memory | new bearing to target |
| `turn` | `degrees` (−180..180) | — | heading delta |
| `move` | `direction` (forward/back/left/right), `steps` 1–10 | — | position delta; `NO_EFFECT` if blocked |
| `go_to` | `target_id` | target known (item/door) | distance delta; arrival flag |
| `attack` | `burst` 1–5 | ammo > 0; a visible enemy within aim cone | ammo delta, kill delta, hit flag |
| `use` | — | — | door/switch state change if any |

Scenarios expose different button sets; the registry marks tools unavailable when their buttons are absent (e.g. `defend_the_center` has only TURN_LEFT/RIGHT/ATTACK).

### 3.3 Topologies

- `react_single`: one LLM with all available tools; loop of tool call → result.
- `commander`: Commander LLM returns `{mode: navigate|fight, reason}`; the chosen specialist receives only its tools. Router overrides nothing; the validator rejects out-of-role tools.
- Baselines: `random` (uniform over valid tools), `scripted` (hand-written rules on facts).
- All variants share perception, validator, executor, memory, budgets and scorers. Only the planning subgraph differs.

### 3.4 Control loop

Fixed-priority router each step: (1) episode finished/budget exhausted → STOP; (2) pending failure → RECOVER (clear queue, add failure packet, max 3 consecutive recoveries without progress); (3) queued valid tool call → CONTINUE with zero LLM calls; (4) otherwise PLAN. Progress = kill, item pickup, health gain, new position cell, or newly seen object.

## 4. Evaluation

- Scenarios (core): `basic`, `defend_the_center`, `health_gathering`. Week 2 adds `deadly_corridor`, `my_way_home`.
- Seed splits per scenario: dev `0–4`, validation `100–104`, test `1000–1009`. Test is frozen until the final comparison.
- Budgets per episode (initial, frozen after dev preflight): 60 LLM requests, 400 tool calls, 300 s wall, max_tokens 512. Reasoning: preflight first tries to disable it (`chat_template_kwargs: {"enable_thinking": false}`); if the endpoint ignores that, reasoning stays on and `max_tokens` is the cap. The chosen setting is recorded in `preflight.json` and frozen.
- Metrics (from traces; no LLM decides success):
  - Outcome: scenario success (per-scenario definition: `basic` target killed; `defend_the_center` kills + survival; `health_gathering` survival time), kills, damage taken, episode length.
  - Trajectory: tool-call validity rate, schema errors, precondition rejections, wasted attacks (no enemy in cone), recoveries and recovery success.
  - Cost: requests, tokens (null when missing, never 0), latency p50/p95 with n.
  - Coordination (`commander`): mode distribution, specialist switches, out-of-role rejections.
- Report: success counts with Wilson 95% intervals, per-seed paired tables, raw distributions. Small-sample claims are labeled pilot.

## 5. Human corrections and improvement

- `doomlab review <episode>` shows each step (facts summary, tool call, result). The reviewer can tag a step with `label ∈ {wrong_tool, wrong_target, premature_attack, missed_pickup, stuck_loop, other}`, a short fix, and optionally a corrected tool call. Stored as `Correction` JSONL with episode/step/span IDs.
- Each correction becomes a **regression case**: the saved snapshot + the corrected expectation (e.g. "must not call attack when no enemy in cone"), replayable without the game.
- Improvement trial (one per sprint): failure miner (deterministic signatures) + corrections → Analyst proposes ≤3 rules (≤300 chars each) citing dev evidence → candidate policy → regression suite + paired A/B on validation seeds → gate → **human approval** → registry promotes for new runs only.
- Gate thresholds (frozen before the candidate exists): all regression cases pass; no validation seed regresses from success to failure; ≥1 additional success **or** ≥15% fewer requests on common successes; requests ≤110%, latency ≤125%, tokens ≤125% of parent; missing usage → inconclusive.

## 6. Error handling

- LLM: typed outcomes (`ok | schema_invalid | timeout | rate_limited | auth_error`); auth errors stop the run; transient errors retry once within budget; malformed tool calls become precondition failures, not game actions.
- Tools: every rejection has a code (`UNKNOWN_TARGET`, `NO_AMMO`, `NO_ENEMY_IN_CONE`, `UNAVAILABLE_TOOL`, `OUT_OF_ROLE`, `NO_EFFECT`, `BAD_ARGS`).
- Game: episode end mid-tool stops execution immediately; no actions after termination.
- Trace integrity: corrupted/incomplete traces are quarantined and shown as harness failures, never scored.

## 7. Testing

- Unit: schemas, perception (fixture label buffers), registry export, executor precondition logic, router priority, budget reservations, scorers.
- Integration (real vizDoom, no LLM): scripted policy runs `basic`; replay reproduces the same outcome from a trace.
- LLM integration: recorded-response fixtures for orchestration; live preflight only when `.env` is present.
- Architecture guards: only `tools/executor.py` calls `make_action`; only `llm/client.py` imports httpx; no `eval`/`exec`.

## 8. Roadmap

**Base sprint — 3 days**
- Day 1: project scaffold, preflight, env + perception, tool registry + executor, LLM client, `react_single` completes `basic`; traces + replay GIF.
- Day 2: graph engine + router + recovery, `commander` + specialists, eval harness + scorers + baselines, dev runs across 3 scenarios.
- Day 3: review CLI + corrections, failure miner, one Analyst patch → regression + validation A/B → gate + human approval, report and demo clip.

**Extension — 2 weeks (independent add-ons, in priority order)**
1. MCP server exposing game tools; agents consume via MCP client.
2. LangGraph port of `commander`; written comparison with the custom engine.
3. Next.js + FastAPI dashboard: run monitoring, frame-by-frame replay, click-to-correct, approval button.
4. Vision ablation: screenshots to `qwen3.6:27b` vs symbolic-only.
5. Trajectory LLM-judge calibrated against human correction labels (agreement rate reported).
6. Live intervention: pause an episode, override the next tool call.
7. Harder scenarios, CI eval on recorded fixtures, public write-up.

## 9. Out of scope

Training/RL, GPU work, multiplayer/deathmatch, screen-pixel control in the base sprint, and any claim of general game intelligence.

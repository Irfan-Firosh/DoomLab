# Day 2 — Friday 9/25 (shifted from Thu 9/24): "Two agent setups, measured on the same benchmark"

**Objective:** `react_single` (one Qwen agent) and `commander` (a Qwen Commander handing off to Navigator/Combat specialists) both play all three scenarios through one harness. `doomlab eval --split dev` produces a first metrics table against the `scripted` and `random` baselines.

References: schedule `docs/superpowers/plans/2026-09-23-doomlab-schedule.md` · spec `docs/superpowers/specs/2026-09-22-doomlab-design.md` · Lucid diagram https://lucid.app/lucidchart/cfc18bb2-f111-478e-a9fd-f9d1de1d6a1d/edit (page 1: router, recovery, topology; page 2: eval harness)

---

## 1. Starting point (end of Day 1, commit `d37d4bf`)

| Piece | Status |
|---|---|
| vizDoom sessions, perception → facts | ✅ all 3 scenarios start and read correctly |
| Tools | `observe`, `aim_at` (strafe or turn), `attack`. **No way to move or look around yet** |
| Executor + validator | ✅ sole `make_action` caller, 7 checks, calibrated on `basic` only |
| Agents | `scripted`, `react_single` (qwen3.8:27b) behind one `decide()` contract |
| Runner | Plain async loop, per-episode LLM budget, JSONL traces |
| Success rules | **`basic` only** (kills ≥ 1) |
| Replay + GIF | ✅ 10/10 dev traces match |
| Results | `basic` dev seeds 0–4: scripted 5/5, react_single 5/5, identical tics, ~1,360 tokens/episode |

**The lesson that shapes today:** `basic` is too easy to tell agents apart. Today's real work is making `defend_the_center` and `health_gathering` playable, because that's where decisions can actually differ.

---

## 2. What each scenario needs (verified 9/23)

| Scenario | Buttons | What the agent must do | Missing today |
|---|---|---|---|
| `basic` | strafe L/R, attack | Aim, shoot one monster | nothing |
| `defend_the_center` | turn L/R, attack | Enemies approach **from all sides**; spot, turn, shoot; 26 ammo; 2100-tic limit | a way to **look around** when nothing is visible (`turn`) |
| `health_gathering` | turn L/R, forward | The floor hurts; walk onto medikits to survive; no weapon; 2100-tic limit | a way to **move** (`go_to`) |

---

## 3. Blocks (in order)

| # | Block | What gets built | Done when |
|---|---|---|---|
| 1 | **New tools + scenario rules** (1.5h) | `turn(degrees)` to look around; `go_to(target_id)` to turn toward an item and walk until picked up, lost or capped. Success rules and scores for `defend_the_center` and `health_gathering`. Re-check the attack threshold on `defend_the_center`'s enemies | Scripted rules extended and scoring on all 3 scenarios; live tests for `turn` and `go_to`; per-scenario calibration saved to `data/` |
| 2 | **Graph engine + router + recovery** (1.5h) | Small typed state-graph engine (nodes, conditional edges, step cap). Runner rebuilt on it. Fixed-priority router: STOP → RECOVER → CONTINUE → PLAN. Recovery: rejection reason goes into the next prompt; 3 consecutive rejections with no progress end the episode as `recovery_exhausted` | Day 1 results and all tests unchanged; a trace shows a recovery; graph transitions are traced |
| 3 | **`commander` topology** (1.5h) | Commander (Qwen) picks a mode, `fight` or `navigate`, via a `choose_mode` tool. The specialist gets **only its own tools**: Combat = `observe`, `aim_at`, `attack`; Navigator = `observe`, `turn`, `go_to`. Out-of-role calls rejected with `OUT_OF_ROLE` | A trace shows a navigate ↔ fight switch; out-of-role rejection is tested |
| 4 | **`random` baseline** (20m) | Uniformly random valid tool calls | Runs all 3 scenarios with no LLM |
| 5 | **Eval harness + scorers** (1.5h) | `doomlab eval --split dev`: scenario × seed × variant matrix, resumable (skips finished episodes). Writes `episodes.csv` and `summary.json`. Scorers: success rate with Wilson 95% CI, kills, survival tics, rejected-call rate, wasted attacks, LLM calls, tokens, latency p50/p95 | Table produced from traces only |
| 6 | **Dev pilot (background)** (~1h wall) | 3 scenarios × seeds 0–4 × 4 variants = 60 episodes (30 use Qwen). Start it while finishing block 5 | Pilot table; prompts, budgets and model **frozen** and hashed |

---

## 4. Decisions (settled in block 1 with measured numbers)

Scripted baselines, dev seeds 0–4, measured 9/25:

| Scenario | Scripted result | Decision |
|---|---|---|
| `basic` | 5/5 success, median 43 tics | Keep. Success = kill; score = tics (lower is better) |
| `defend_the_center` | Dies every time (1,248–1,660 tics); **26 kills (= all ammo) on 3/5 seeds** | **Score = tics survived** (kills are capped at 26 by ammo). Success = alive at 2100 tics. Kills still reported |
| `health_gathering` | **Survives 5/5** (capped at 2100) | Too easy: kept only as a sanity scenario, **not in the benchmark** |
| `health_gathering_supreme` | 1/5 success, median **1,376** tics survived; has `Poison` hazards | **Replaces `health_gathering` in the benchmark.** Success = alive at 2100; score = tics survived |

**Benchmark scenarios:** `basic`, `defend_the_center`, `health_gathering_supreme`.

Other settled points:
- **Aim cone is per enemy** (from `data/calibration_defend_aim.json`, 210 shots): Cacodemon 15u, Demon 15u, **MarineChainsawVzd 9u** (88% hits within 18u, ~0% beyond 24u), unknown enemies 9u.
- **Stopping never freezes time.** If an agent gives up or runs out of steps or budget, the runner plays the rest of the episode standing still, so quitting can't dodge a death. Results carry `outcome` (what the game decided) and `stop_reason` (why the agent stopped).
- **Rate limit (measured 9/25, `data/rate_limit_probe.json`):** Purdue documents 60/min, but the 21st request in any ~60 s window is refused at every spacing tried; 18/min is sustainable (45/45 calls). The client paces at 18/min (~3.3 s per call).
- **Equal budgets, per scenario:** basic 20 calls, defend 150, supreme 80 (the same for react_single and commander). Sized from scripted's decisions (median 2 / 111 / 38) × ~1.4 calls per decision for commander; time and token caps derive from the call count so the call cap binds first.
- **Decision speed:** at ~0.7 s per Qwen call, 100+ decisions ≈ 1–2 min of LLM time per long episode. Check against the pilot's wall-clock before Day 3.

---

## 5. Expected output (shape only; real numbers come from the runs)

```
$ uv run doomlab eval --split dev
running 60 episodes (30 LLM)… resumable, 0 already done
scenario            variant        success  CI95        score (median)   rejected  llm calls  tokens/ep
basic               scripted       5/5      0.57–1.00   kill @43 tics    0         0          0
basic               random         ?/5      …           …                …         0          0
basic               react_single   5/5      0.57–1.00   kill @43 tics    0         2          ~1,360
basic               commander      ?/5      …           …                …         ~4         …
defend_the_center   …              …        …           kills …          …         …          …
health_gathering    …              …        …           survived … tics  …         …          …
wrote runs/eval-dev-…/episodes.csv, summary.json
```

**Honest expectation:** `scripted` stays strong on `basic`. The first real differences between `react_single` and `commander` should show up on `defend_the_center` (choosing targets, scanning, ammo) and `health_gathering` (navigation). A pilot of 5 seeds gives wide confidence intervals, so these are clearly labeled **pilot** numbers.

---

## 6. End-of-day deliverables

- [x] `turn` and `go_to` tools; success rules + scores for all scenarios; calibration re-checked on `defend_the_center` (block 1)
- [x] Graph engine + router + recovery, with Day 1 results reproduced (block 2: 20/20 scripted episodes identical before/after; recovery trace `runs/block2-recovery-demo/` replays exactly). CONTINUE route deferred to block 3, where the commander's mode is the thing to continue
- [x] `commander` topology with role-restricted tools; a traced mode switch (block 3: live `defend_the_center` seed 0 switched navigate <-> fight 7 times, replay matches; `OUT_OF_ROLE` tested). Also fixed from the live run: repeated `observe` is rejected as `NOTHING_CHANGED` (the game is paused, so it can never show anything new), and the client now paces requests at 30/min (Purdue answered HTTP 400 "Rate limit exceeded" after 20 calls in 8 s)
- [x] `random` baseline (block 4: seeded, schema-valid calls, no LLM; dev seeds 0-4 — basic 5/5 at the same tics as scripted, defend median 346 survived, supreme median 832)
- [x] `doomlab eval --split dev` → `episodes.csv` + `summary.json` (pilot, clearly labeled) — block 5 built and checked on the free variants (`runs/eval-dev-free/`: 30 episodes, numbers match `doomlab run` seed for seed, rerun resumes in 0.3 s); the LLM half runs in block 6
- [x] Frozen config (prompt, budget and model hashes) committed — done as Day 3 block 0 (`configs/frozen.json`, tag `frozen-v0`)
- [ ] Carry-overs from Day 1: CodeRabbit review of `d37d4bf`; `git push`

## 7. Cut lines

- If `health_gathering` movement misbehaves by 13:00, drop it and report 2 scenarios.
- If `commander` is unstable by 15:00, fix it before adding anything else. The two-topology comparison is the point of the day.
- If the pilot is slow, run 3 seeds instead of 5 and label it so. Never shrink one variant's budget to save time.
- The graph engine can stay minimal. Nodes, edges and a step cap are enough; no framework features.

---

## 8. EOD log (fill in at the end of the day)

```text
Sprint goal: met / partly met / blocked
Working commands and commit:
Evidence files:
Tests or live checks completed:
Pilot results (headline):
Failures learned from:
Still incomplete:
Frozen config hashes:
First task tomorrow:
Scope cut, if any, and why:
```

# Day 3 — next session after Day 2: "Held-out results, one human-corrected improvement, a demo people can open"

**Objective:** freeze the recipe, measure it on the untouched **test** seeds, run **one** improvement trial that is driven by your corrections and ends in your approve/reject, and publish a static demo page with the numbers.

References: master schedule `docs/superpowers/plans/2026-09-23-doomlab-schedule.md` (Day 3) · spec `docs/superpowers/specs/2026-09-22-doomlab-design.md` §4–5 · Day 2 `schedule/day2.md` · Lucid diagram (page 2: evals + improvement) https://lucid.app/lucidchart/cfc18bb2-f111-478e-a9fd-f9d1de1d6a1d/edit

---

## 1. Starting point (end of Day 2)

| Piece | Status |
|---|---|
| Agents | `random`, `scripted`, `react_single`, `commander` (Commander + Combat/Navigator), one harness |
| Runtime | State-graph runner: STOP → RECOVER → CONTINUE → PLAN; recovery with `recovery_exhausted` after 3 rejections |
| Evals | `doomlab eval --split …`: resumable, scored from traces only, Wilson 95% CIs, per-seed paired tables |
| Limits (measured) | Purdue refuses the 21st request in any ~60 s window → client paces at **18/min**; budgets **20 / 150 / 80** calls (basic / defend / supreme) |
| Commits | `0998e0e` (blocks 1–5), `ccb94cd` (rate limit + budgets) |

**Dev pilot (seeds 0–4, 60 episodes, 0 LLM errors), median score:**

| Scenario | random | scripted | react_single | commander |
|---|---|---|---|---|
| basic (tics to kill, lower better) | 43 | 43 | 43 | 43 |
| defend (tics survived) | 346 | **1,248** | 996 | 1,140 |
| supreme (tics survived) | 832 | 1,376 (1/5) | **2,100 (3/5)** | 1,312 (0/5) |

Pilot lessons that shape today:
- `basic` separates nothing (the tools do the work): it stays a smoke test.
- On `defend` the Combat specialist almost never fired blind (1 `NO_ENEMY_IN_CONE` vs 22 for `react_single`), but 150 calls still ran out on 3/5 episodes.
- On `supreme` the commander has only one mode, so it reduces to a single specialist, and did worse.
- `report_back` was used once in ~15 team episodes.

---

## 2. The constraint that sets the day: LLM time

Purdue allows ~20 requests a minute **per user**, across all processes. The dev pilot's LLM half took **100 min** for 30 episodes, so:

| LLM job | Episodes | Estimated time |
|---|---|---|
| Test eval, 10 seeds (2 LLM variants × 3 scenarios) | 60 | **~3.5 h** |
| Improvement A/B, 5 validation seeds, one scenario (parent + candidate) | 10 | ~30 min on supreme, ~70 min on defend |
| Regression suite (one decision per case, parent + candidate) | ~20 calls | ~1–2 min |

**Rule for the day: only one thing uses Purdue at a time.** Two processes each pacing at 18/min would total 36/min and get refused. All the non-LLM building (review CLI, failure miner, gate, report, demo page) happens *while* the test eval runs.

---

## 3. Blocks (in order)

| # | Block | What gets built | Done when |
|---|---|---|---|
| 0 | **Freeze** (carry-over from Day 2 block 6, 45m) | Apply the pilot decisions (§4). `configs/frozen.json` holds model, decoding, budgets, pacing, prompts, tool schemas, trigger rules; its **sha256** goes into every trace's `episode_start`, and `eval` refuses to mix hashes in one results folder. Progress lines flush without `PYTHONUNBUFFERED`. Tag `frozen-v0` | Hash printed by `doomlab eval`; commit + tag done; **you start the test eval** |
| 1 | **Test eval** (background, ~3.5h) | No new code: `doomlab eval --split test` → seeds 1000–1009, 120 episodes (60 LLM) | `runs/eval-test/summary.json` with n = 10 per cell |
| 2 | **`doomlab review`** (1.5h, no LLM) | Step through a dev trace: facts, tool call, result per step. You tag a step `wrong_tool / wrong_target / premature_attack / missed_pickup / stuck_loop / other`, write a short fix, optionally a corrected call → `corrections/corrections.jsonl`. Each correction becomes a **regression case**: saved observation + history + menu + expectation ("must not call attack", "must call go_to on id 12") | ~10 of your corrections saved; `doomlab regress` checks cases without the game (unit-tested on the fake LLM) |
| 3 | **Failure miner + gate** (1h, no LLM) | Deterministic failure signatures from dev traces: observe loops (`NOTHING_CHANGED`), blind attacks, budget exhaustion, death with a medikit in view, early death. Gate with thresholds frozen **before** any candidate exists (spec §5): all regression cases pass; no validation seed goes success → failure; ≥1 extra success **or** ≥15% fewer calls on common successes; calls ≤110%, tokens and latency ≤125% | Miner report on the dev pilot; gate unit-tested on hand-made A/B results |
| 4 | **Improvement trial** (after the test eval ends, ~1h mostly waiting) | The Analyst (Qwen) reads miner signatures + your corrections and proposes **≤3 rules** (≤300 chars each), each citing trace evidence → candidate policy v1 = v0 + those lessons in the prompt → regression suite + paired A/B on validation seeds 100–104 (one scenario × one variant, §4) → gate → **your approve/reject** → registry points new runs at the winner | `improve/gate_result.json`: promote / reject / inconclusive, with reasons and the number of corrections used |
| 5 | **`doomlab report`** (1h) | `results/summary.json`, `results/metrics.md` (the website block), charts: success with 95% CI, score vs LLM calls, rejection rate by code. Every number links to its trace file | Report rebuilt from traces alone; no hand-typed numbers |
| 6 | **Demo page** (1.5h) | Static page, no API key: the same seed side by side (random / scripted / react_single / commander GIFs), a commander role timeline for one episode, the metrics table, the improvement verdict. README with repro commands. Tag `v0.1` | Page opens from a link; README commands work on a fresh clone |

**Timeline:** 0 → start 1 → build 2, 3 and the code of 5–6 while 1 runs → when 1 finishes, run 4 → fill 5–6 with the real numbers.

---

## 4. Decisions to settle at the start (from the pilot)

| Decision | Recommendation | Why |
|---|---|---|
| Keep `report_back`? | **Drop it** before freezing | Used once in ~15 team episodes; the router's rules already cover every hand-back it would make |
| `defend` budget | **Keep 150** and report "survival within 150 decisions" | Equal for both LLM agents, so fair; 250 would push the test eval to ~5 h |
| Commander in one-mode scenarios | Keep it and **say so** in the report | Honest: in `basic`/`supreme` the team reduces to one specialist, which is itself a finding |
| Improvement trial target | **`react_single` on `health_gathering_supreme`** | Cheapest to A/B (~3 min per episode vs ~7 on defend) and has clear failure modes (deaths around 1,300 tics). Revisit if the miner shows a stronger pattern elsewhere |
| `observe` | Keep, with the `NOTHING_CHANGED` rule | The rule already recovers every case; removing the tool would change the frozen menu for a small gain |

---

## 5. Expected output (shape only; real numbers come from the runs)

```
$ uv run doomlab eval --split test
config frozen-v0  sha256 3f9a…   (every trace records it)
[1/120] basic  seed 1000  random  success  score 38 …
…
defend_the_center: score = tics survived (higher is better)
  variant       n   success  95% CI      score median [q1-q3] …
  commander     10  ?/10     …
  …

$ uv run doomlab review runs/eval-dev/defend_the_center-s1-react_single.jsonl
step 14  facts: Demon 210u ahead, 44u LEFT (not in cone)   call: attack(burst=1)   → REJECTED NO_ENEMY_IN_CONE
  label? premature_attack   fix? aim_at the demon first   corrected call? aim_at(target_id=3)
saved correction 7 → regression case rc-007

$ uv run doomlab improve --scenario health_gathering_supreme --variant react_single
analyst proposed 3 rules (citing 6 traces, 10 corrections)
regression: parent 6/10 cases, candidate 10/10
A/B on validation seeds 100–104: parent 2/5, candidate ?/5 (paired)
gate: PROMOTE | REJECT | INCONCLUSIVE because …   → your decision? [a]pprove / [r]eject
```

**Honest expectation:** 10 seeds still leave wide intervals, so claims are made from the per-seed paired comparisons. A rejected or inconclusive patch is a valid, publishable result: the point is that the decision is evidence-based and yours.

---

## 6. End-of-day deliverables

- [x] Frozen config + hash in every trace; tag `frozen-v0` (block 0: `report_back` dropped, budgets 20/150/80 kept, policy v0 with no lessons; `doomlab eval` prints the recipe hash, refuses to mix recipes in a folder, and runs the test split only on the frozen recipe)
- [x] Test-split metrics: 10 seeds (120 episodes, recipe `af2ab05f5f7c`)
- [x] ~10 corrections → regression suite (block 2: 11 cases — 2 typed by Irfan, 9 AI-drafted from the ViZDoom scenario docs and marked `author: assistant`; v0 passes 4/11 on one ask each). Block 3: `doomlab mine` (observe_loop is 322 of 1,712 dev decisions, 19%) and gate rules frozen in `improve/gate_rules.json` before any candidate exists
- [x] `gate_result.json` (promote / reject / inconclusive) + your decision — trial-v1: gate PROMOTE (one extra success), Irfan REJECTED (worse on 4/5 seeds, turn oscillation); gate rules v2 adds `no_broad_decline` for later trials
- [x] `results/metrics.md` website block; charts (block 5: `doomlab report`, deterministic, traces archived in `results/traces/`)
- [ ] Demo page link, 3+ GIFs, README with repro commands; tag `v0.1`
- [ ] Carry-overs: CodeRabbit review of `d37d4bf` → `ccb94cd`+; `git push`; Day 1 Lucid diagram still says `qwen3.6`

## 7. Cut lines

- If the test eval won't finish by mid-afternoon, stop it at 5 seeds (it resumes later) and label the numbers "5-seed pilot".
- If the improvement trial runs late, publish the corrections + regression suite + miner report and mark the trial "incomplete".
- **Never tune on test results.** Test numbers are reported, not acted on.
- The demo page can be one static HTML file. No framework: the Next.js dashboard is week 2.

---

## 8. EOD log (fill in at the end of the day)

```text
Sprint goal: met / partly met / blocked
Frozen config hash and tag:
Test eval (headline, n per cell):
Corrections -> regression cases:
Gate result and your decision:
Demo page link:
Failures learned from:
Still incomplete:
First task next session:
Scope cut, if any, and why:
```

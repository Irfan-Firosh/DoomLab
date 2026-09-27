# One LLM call in five was spent looking at a paused game

**DoomLab finding, 2026-09-27.** An LLM agent (`qwen3.8:27b`) plays vizDoom through typed tool calls. A deterministic failure miner scanned every decision it made, and the most common failure was not a bad shot or a missed medikit: it was the agent calling `observe`, a tool that cannot tell it anything new.

All numbers below come from saved episode traces and can be recomputed (`doomlab mine`, `runs/eval-*/`).

---

## TL;DR

- On the dev seeds, **322 of 1,705 decisions (18.9%)** were `observe` calls, in 20 of 30 LLM episodes.
- The game runs in **synchronous mode**: it is paused between calls, and every prompt already contains the current view. So `observe` can never reveal anything, and each call is a wasted LLM request (~1,000 tokens, ~3.3 s at the rate limit).
- The tool's own description says so: *"Look again. Uses no game time, and the game is paused between your calls, so the facts you were just given are already current."* The model called it anyway.
- It is **not a loop but a habit**: a guard rejects a second look with nothing in between, so the longest run was 2. The waste is spread across the episode, about one decision in five.
- **Held-out check:** on 10 unseen test seeds (measured afterwards, not used for tuning) the rate was the same, **663 of 3,369 decisions (19.7%)**.

---

## Setup (just enough to read the numbers)

- **Agents:** `react_single` (one Qwen agent choosing one tool per turn) and `commander` (a Qwen commander choosing between a Combat and a Navigator specialist, each with only its own tools). Both get the same per-episode budget of LLM calls.
- **Tools:** `observe`, `aim_at`, `attack`, `turn`, `go_to`. A single executor validates every call and is the only code that touches the game.
- **Scenarios:** `basic` (kill one monster), `defend_the_center` (survive enemies from all sides, 26 bullets), `health_gathering_supreme` (survive an acid floor by collecting medikits, avoid poison).
- **Every prompt** lists what is visible right now (ids, distances, left/right offsets, health, ammo) and the last few actions with their results.

## How it was found

Not by watching games. A **failure miner** (`src/doomlab/improve/miner.py`) runs deterministic rules over every recorded decision and counts recurring failure signatures, with example episodes to cite:

```
30 dev LLM episodes, 1,705 decisions

signature           occurrences  episodes
needless_observe            322     20/30
blind_attack                 23      6/30
turned_from_enemy            19      5/30
medikit_ignored              16      3/30
wasteful_burst               15      8/30
budget_exhausted              7      7/30
```

The expected mistakes are there (shooting with nothing lined up, walking past medikits at low health), but they are an order of magnitude rarer than looking again.

## The numbers

| | dev (seeds 0–4) | test (seeds 1000–1009, held out) |
|---|---|---|
| LLM episodes | 30 | 60 |
| Decisions | 1,705 | 3,369 |
| `observe` calls | **322 (18.9%)** | **663 (19.7%)** |
| … rejected by the guard (a second look, nothing changed) | 64 | 134 |
| Episodes with at least one | 20 / 30 | 39 / 60 |
| Longest run of consecutive `observe` | 2 | 2 |

By scenario (share of decisions):

| Scenario | react_single (dev / test) | commander (dev / test) |
|---|---|---|
| basic | 0% / 0% | 0% / 0% |
| defend_the_center | 22% / 23% | 22% / 21% |
| health_gathering_supreme | 15% / 16% | 11% / 12% |

It never happens on `basic`, where the episode is two decisions long. It is worst on `defend_the_center`, the scenario with the most going on.

## Why it matters

1. **It burns the budget.** Seven dev episodes ran out of LLM calls and then stood still until they died. In those episodes, **202 of 980 calls (20.6%)** had gone to `observe` (test: 367 of 1,810, 20.3%). Those calls could have been aims, shots or turns.
2. **It costs real time and tokens.** Purdue's endpoint allows about 20 requests a minute, so every call costs ~3.3 s. On the dev pilot, 322 calls × ~1,015 tokens ≈ **327k tokens** and ≈ **18 minutes** of the ~100 minutes of LLM time.
3. **The scenario never punishes it directly,** because a paused game costs no game time. That is exactly why it hides: the score looks fine per decision, and only the trace shows where the budget went.

## Why does the model do it? (hypotheses, not yet tested)

- **Agent-loop habit.** Many agent frameworks teach "observe, then act". The model may treat `observe` as the natural first step of a turn, even though the observation is already in the prompt.
- **Uncertainty.** Calling `observe` looks like "waiting to see what happens", a reasonable move in a real-time game, but meaningless in a paused one.
- **The tool is offered at all.** An available tool reads as a useful one. The description saying it is pointless did not outweigh that.

## What the harness already does about it

- The executor **rejects a second `observe` with no game time in between** (`NOTHING_CHANGED`), and three rejections in a row end the agent's control. That turned an early failure (one Navigator called `observe` 17 times in a row, then hit the rate limit) into at most two in a row.
- It does **not** reject the first look, because an honest tool call should not be refused just for being useless. The waste is reported instead of hidden.

## What happens next

This is the first target of the project's improvement loop: an "Analyst" LLM reads the miner report and the reviewed corrections and proposes up to three lessons for the prompt (for example *"Do not call observe; the facts you are given are current."*). The candidate policy is tested against the current one on human-reviewed correction cases and on unseen validation seeds, and a promotion gate whose rules were committed before the candidate existed decides whether it is kept.

**Caveats.** One model (`qwen3.8:27b`, temperature 0, thinking off), one prompt format, three scenarios. Dev covers 5 seeds and test 10. The rate is consistent across both, but it has not been tested on other models.

---

## Other findings so far

1. **The documented rate limit was not the real one.** Purdue's GenAI Studio docs say 60 requests per minute. Measured with 1-token requests, the 21st request inside any ~60 s window was refused at every spacing tried (back-to-back, 55/min, 60/min, 24/min, 20/min); 18/min held for 45 calls. Evidence: `data/rate_limit_probe.json`.
2. **The easiest benchmark measured the tools, not the agent.** On `basic`, a random agent tied the hand-written scripted agent to the exact tic on all 5 dev seeds (27, 51, 43, 42, 52), because the `aim_at` tool does the precise aiming and rejected calls cost no game time. On the 10 test seeds, all four agents took identical tics on 9; random's only miss was a timeout. `basic` stays a smoke test.
3. **Telling the model how it is scored changed its behaviour.** After the prompt stated the scoring rule and that one hit usually kills, the same episode (defend, seed 0, commander) went from bursts of 5 to single shots on all 9 attacks, and kills rose from 4 to 8 and survival from 366 to 601 tics. That is one episode, so it is an anecdote, not a result.
4. **The pilot's best result did not survive unseen seeds.** On dev, `react_single` survived all 2,100 tics on 3 of 5 `health_gathering_supreme` seeds and beat the scripted agent. On the 10 test seeds it won 2 of 10 (median 1,244.5 tics), and the scripted agent's median was higher (1,586). Keeping the test seeds locked until the end is what caught this.
5. **Narrow roles removed one error, not the gap.** The commander's Combat specialist almost never fired blind (dev 1 vs 22 for `react_single`; test 4 vs 32), yet the team did not score higher (defend test median 1,080 vs 1,142 tics survived).

**Test-split headline (10 unseen seeds, median):**

| Scenario | random | scripted | react_single | commander |
|---|---|---|---|---|
| basic (tics to kill, lower is better) | 60.5 | 58 | 58 | 58 |
| defend_the_center (tics survived) | 298.5 | **1,330.5** | 1,142 | 1,080 |
| health_gathering_supreme (tics survived) | 544 | **1,586** | 1,244.5 | 1,029 |

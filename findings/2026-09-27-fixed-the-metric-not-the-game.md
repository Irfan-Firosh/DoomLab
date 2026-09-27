# The lesson fixed the metric, not the game

**DoomLab finding, 2026-09-27.** An improvement loop turned counted failures into three prompt lessons for an LLM agent playing vizDoom. The new policy passed far more of the reviewed test cases and almost stopped the wasteful behaviour it targeted, yet it survived shorter on 4 of 5 unseen levels. The automatic gate said PROMOTE; the human reviewer rejected it. This is a follow-up to [one LLM call in five was spent looking at a paused game](2026-09-27-needless-observe.md).

All numbers come from committed files (`improve/trial-v1/gate_result.json`, `policies/v1.json`) and the saved episode traces.

---

## TL;DR

- An "Analyst" LLM read the failure counts and 11 corrected decisions and wrote 3 lessons for the agent's prompt (policy **v1**).
- **Offline, v1 looked clearly better:** it passed **7 of 11** correction cases against **3 of 11** for the current policy (v0), and its `observe` calls fell from **41 to 3**.
- **In play, v1 was worse:** it survived shorter on **4 of 5** validation levels (median change −36%) and won one level outright.
- It had swapped one waste for another: with nothing in view it **turned back and forth on the spot**. Direction reversals in those moments rose from **1 to 17**.
- The gate **promoted** v1 through its "one more success" rule. The human reviewer **rejected** it. The gate rules now have an extra guard, added *after* the trial and applying only to future trials.

---

## The loop

1. **Mine:** deterministic rules count failure patterns over 30 dev episodes (1,705 decisions). The top one was calling `observe` in a paused game (322 times).
2. **Correct:** 11 flagged decisions were corrected with what the agent should have done: 2 typed by the human reviewer and 9 drafted by an AI assistant from the ViZDoom scenario docs, marked as such.
3. **Propose:** the Analyst (`qwen3.8:27b`) wrote at most 3 lessons, each required to cite its evidence. Code checked length, evidence and generality before accepting them.
4. **Test:** v0 and v1 each answered the 11 correction cases 3 times (a case passes on 2 of 3), then played `health_gathering_supreme` on validation seeds 100–104, alternating policies seed by seed.
5. **Gate, then a human:** rules committed before v1 existed produced a verdict, and a human made the final call.

## The lessons (policy v1)

1. *Never call observe: the game is paused so it shows nothing new. Instead, turn to search for medikits or enemies.*
2. *When health is below 50, walk to the nearest visible medikit immediately; do not turn away or look around.*
3. *Aim at the nearest enemy before attacking, and fire only one shot (one hit kills). Never turn away from a visible enemy.*

Each is reasonable, and each cites real evidence (failure counts plus correction ids).

## What the tests said

**Correction cases (offline, one decision each, 3 asks):**

| | v0 | v1 |
|---|---|---|
| Cases passed | 3 / 11 | **7 / 11** |

**Playing the game (validation seeds, tics survived, 2,100 = survived to the end):**

| Seed | v0 | v1 |
|---|---|---|
| 100 | 704 | 448 |
| 101 | 1,088 | 416 |
| 102 | 1,438 | 736 |
| 103 | 992 | **2,100** |
| 104 | 1,041 | 960 |

**What changed in its behaviour (all 5 seeds):**

| | v0 | v1 |
|---|---|---|
| Decisions | 203 | 183 |
| `observe` | 41 | **3** |
| `turn` | 80 | 105 |
| `go_to` (walk to an item) | 75 | 68 |
| Turns made with nothing in view | 43 | 62 |
| … of which reversed the previous turn | 1 | **17** |

## What went wrong

Lesson 1 told the agent to turn instead of looking again, and it did. But with nothing in view it turned left, then right, then left again, seeing the same empty walls while the acid floor drained its health. Seed 101, v1:

```
step  5  health 84  sees Poison, 2 medikits   → go_to a medikit    → lost from view
step  6  health 70  sees nothing              → turn −90
step  7  health 62  sees nothing              → turn +90
step  8  health 54  sees nothing              → turn −90
step  9  health 46  sees nothing              → turn +90
step 10  health 38  sees nothing              → turn −45
step 11  health 38  sees nothing              → turn +45
step 12  health 38  sees nothing              → turn −90
step 13  health 30  sees nothing              → turn −137   → 2 medikits in view
step 14  health 22                             → go_to a medikit → died on the way
```

v0 wasted calls on `observe`, but between those calls it tended to keep one direction and walk. v1 removed the wasted call and filled the gap with the next-cheapest move, which here was actively harmful.

**Why the offline tests missed it.** Every correction case checks one decision in isolation ("here, do not observe; turn"). v1 got those right. Oscillation only exists across several decisions in a row, so a one-step test cannot see it. Only playing whole episodes could.

## Why the gate promoted it, and what changed

The gate had three routes to "better play". v1 met one: **one more success** (seed 103). Nothing stopped a single success from outweighing worse play on the other four seeds; with 5 seeds and rare successes, one lucky seed was enough.

The reviewer rejected v1 with this note: *"Passes 7/11 corrections and cut observe 32 to 1, but survival fell on 4 of 5 seeds (median -36%); it traded observe for back-and-forth turning. Gate promoted on one extra success."* (The 32 → 1 in the note counted 4 seeds; over all 5 it is 41 → 3.)

Gate rules **version 2** add a guard: a candidate may score lower than its parent on at most 1 of 5 paired seeds. It was written after seeing this trial, so it is **not** used to re-judge trial-v1. The recorded verdict stays PROMOTE, the rules that produced it are kept (`improve/gate_rules_v1.json`, fingerprint recorded in the result), and v2 applies only to later trials. A test pins that v2 would have rejected these numbers.

## Takeaways

1. **Fixing the counted failure is not fixing the agent.** A lesson aimed at the top failure pattern removed it almost entirely and made play worse. Measure the outcome, not only the targeted behaviour.
2. **Single-decision regression tests cannot catch multi-step failures.** They are cheap and useful for catching regressions, but they need episode-level evaluation alongside them.
3. **Promotion rules need a "did anything get broadly worse" guard,** especially with few seeds and rare successes.
4. **The human step earned its place.** The automatic verdict and the right decision differed, and the reason was visible in the trace.

**Caveats.** One scenario (`health_gathering_supreme`), one agent (`react_single`), one proposal, 5 validation seeds, one model at temperature 0 (which a hosted endpoint does not make fully repeatable). 9 of the 11 correction cases were AI-drafted rather than human-written, and they are labelled as such everywhere.

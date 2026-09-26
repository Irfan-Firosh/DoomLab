# DoomLab

An agent runtime that plays vizDoom through **typed tool calls**, then evaluates itself and improves from failures and human corrections.

Status: **Day 1 done** (commit `d37d4bf`): Qwen plays `basic` through typed tool calls, with traces and verified replays. **Day 2 in progress:** blocks 1–5 done (new tools, graph runner with recovery, commander topology, random baseline, `doomlab eval`); the pilot run is next.

- Spec: [`docs/superpowers/specs/2026-09-22-doomlab-design.md`](docs/superpowers/specs/2026-09-22-doomlab-design.md)
- Schedule (Wed → Fri): [`docs/superpowers/plans/2026-09-23-doomlab-schedule.md`](docs/superpowers/plans/2026-09-23-doomlab-schedule.md)
- Day 1 plan and walkthrough: [`schedule/day1.md`](schedule/day1.md) · Day 2 plan: [`schedule/day2.md`](schedule/day2.md) · Day 3 plan: [`schedule/day3.md`](schedule/day3.md)
- Full architecture diagram (Lucid, 2 pages): [runtime loop + evals/improvement](https://lucid.app/lucidchart/cfc18bb2-f111-478e-a9fd-f9d1de1d6a1d/edit)

## Day 1: single-agent loop on `basic`

Editable Lucid version: [DoomLab Day 1: Single-Agent Loop on basic](https://lucid.app/lucidchart/b33933f5-b78b-441e-bc77-c383eea49ff8/edit)

```mermaid
flowchart TD
    classDef code fill:#DDE7FB,stroke:#3F6FD8,color:#17202C
    classDef llm fill:#F8DDEB,stroke:#C2418A,color:#17202C
    classDef gate fill:#FBE6D0,stroke:#C9741F,color:#17202C
    classDef ev fill:#D3F0E6,stroke:#1E8F72,color:#17202C
    classDef fail fill:#F9DAD7,stroke:#CF3F37,color:#17202C

    pre["doomlab preflight: models list, tool-call probe,<br/>thinking off, overlap, latency → preflight.json"]:::code
    start(["doomlab run: react_single, basic, seed N"]):::code
    setup["Setup: load basic.cfg, headless, PLAYER mode, labels on,<br/>add POSITION/ANGLE/KILLCOUNT, set_seed, init, new_episode"]:::code
    done{"Episode finished or<br/>budget used up?"}:::gate
    endn(["Record outcome: success = KILLCOUNT > 0,<br/>tics, LLM calls, tokens"]):::ev
    gif["Build replay GIF from captured frames"]:::ev
    state["get_state(): labels buffer + game variables"]:::code
    perc["Perception: drop DoomPlayer, compute<br/>ahead / offset / in aim cone → facts"]:::code
    prompt["Build prompt: facts + recent results/failures<br/>+ tools allowed by basic's buttons"]:::code
    llm["[LLM] Purdue qwen3.8:27b<br/>native tool call, e.g. aim_at(0)"]:::llm
    script["Scripted baseline (no LLM):<br/>aim then shoot rule"]:::code
    val{"Validator: tool exists, args valid,<br/>target visible, precondition ok?"}:::gate
    rej["Reject with code (NO_ENEMY_IN_CONE,<br/>UNKNOWN_TARGET, …): no button pressed"]:::fail
    exe["Executor: aim_at strafes MOVE_LEFT/RIGHT 2 tics<br/>until aligned; attack presses ATTACK"]:::code
    doom["vizDoom make_action<br/>(game advances only here)"]:::ev
    ver["Verify deltas: offset, ammo, KILLCOUNT, position"]:::code
    mem[("Memory: last facts, tool results, failures")]:::code
    trc[("Trace JSONL + frames")]:::ev

    start --> setup --> done
    done -- yes --> endn --> gif
    done -- no --> state --> perc --> prompt --> llm --> val
    script -. baseline .-> val
    val -- pass --> exe --> doom --> ver
    val -- fail --> rej -- feedback --> mem
    ver --> mem
    ver -.-> trc
    mem -- next step --> done
```

**Colors:** pink = LLM · blue = plain code · orange = decision point · mint = game / evidence · red = rejection.

**How it works in one paragraph:** vizDoom runs in synchronous `PLAYER` mode, so the game is paused while Qwen thinks. Each step, code turns the labels buffer and game variables into facts (e.g. "Cacodemon 384u ahead, 20u left, not in aim cone"). The LLM answers with one tool call. Code validates it, then the executor translates it into `make_action` button presses. `basic` has no turn buttons, so `aim_at` strafes. The result is verified from before/after game state, stored in memory, and written to a JSONL trace used for replays and metrics.

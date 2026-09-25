# Day 1 — Wednesday 9/23: "One agent plays Doom, and every step is recorded"

**Objective:** a real vizDoom + Qwen (`qwen3.8:27b` on Purdue RCAC) loop runs end to end on the `basic` scenario, producing a trace and a replay GIF.

**Day 1 diagram (Lucid):** https://lucid.app/lucidchart/b33933f5-b78b-441e-bc77-c383eea49ff8/edit (also rendered as Mermaid in the root `README.md`)

References: overall schedule `docs/superpowers/plans/2026-09-23-doomlab-schedule.md` · spec `docs/superpowers/specs/2026-09-22-doomlab-design.md` · Lucid diagram (page 1) https://lucid.app/lucidchart/cfc18bb2-f111-478e-a9fd-f9d1de1d6a1d/edit

---

## 1. The Lucid diagram: Wednesday's slice

Wednesday uses **page 1 only**, and not all of it.

| Diagram box | Today? | What it does today |
|---|---|---|
| Episode start | ✅ | Load `basic.cfg`, set seed, headless, labels on, `init()`, `new_episode()` |
| Perception | ✅ | Turn `get_state()` into a short list of facts the LLM can read |
| Router | ✅ simplified | A plain `while` loop: stop if the episode is finished or the budget is used up, otherwise ask the LLM |
| Topology? → **ReAct agent** | ✅ | The only agent today. It gets the facts plus a tool list and replies with one tool call |
| Commander / Navigator / Combat | ❌ Thursday | Multi-agent comes after the single loop is solid |
| Tool validator | ✅ | Code checks: real tool? valid arguments? target actually visible? |
| Recovery | ✅ minimal | A rejected call becomes feedback in the next prompt ("`attack` rejected: no enemy in aim cone") |
| Tool executor | ✅ | Turns one tool call into several `make_action()` calls. **The only file that touches the game** |
| vizDoom (sync PLAYER) | ✅ | The game only advances when we call `make_action` |
| Verify | ✅ | Before/after comparison: ammo, kills, position, target still visible |
| Memory | ✅ basic | Last facts, recent tool results, recent failures |
| Trace spans | ✅ | One JSONL line per step, LLM call and tool call; this is what makes replay possible |

Page 2 (evals, human corrections, improvement gate) is Thursday and Friday.

---

## 2. From `quickstart.py` to DoomLab

The quickstart loop:

```python
game.init()
for _ in range(episodes):
    game.new_episode()
    while not game.is_episode_finished():
        state = game.get_state()
        reward = game.make_action(random.choice(actions))   # 1 decision = 1 button press
```

DoomLab keeps that skeleton and changes four things:

| | quickstart | DoomLab |
|---|---|---|
| **Who decides** | `random.choice` | An LLM picks a **tool**; code turns it into button presses |
| **Decision size** | One button press per decision | One tool = many `make_action` calls (e.g. "strafe until aligned") |
| **What the decider sees** | Nothing | **Facts** from the labels buffer + game variables, never raw pixels |
| **Record** | Nothing | Every step traced: facts in, tool out, buttons pressed, result |

**Why an LLM can play at all:** in `Mode.PLAYER` the game is **paused between `make_action` calls**. Qwen can take ~3 s to think and the monster doesn't move. Only the tics we actually play count against the scenario timeout (300 tics in `basic`).

---

## 3. Verified scenario facts (checked 2026-09-22/23, vizdoom 1.3.1)

| Scenario | Buttons | Built-in variables | Notes |
|---|---|---|---|
| `basic` | `MOVE_LEFT, MOVE_RIGHT, ATTACK` | `AMMO2` | `living_reward -1`, timeout 300 tics, starts at tic 14. **No turn buttons, so you aim by strafing** |
| `defend_the_center` | `TURN_LEFT, TURN_RIGHT, ATTACK` | `AMMO2, HEALTH` | Timeout 2100 tics |
| `health_gathering` | `TURN_LEFT, TURN_RIGHT, MOVE_FORWARD` | `HEALTH` | `living_reward +1`, timeout 2100 tics, **no attack** |

We add our own instrumentation variables to every scenario: `POSITION_X, POSITION_Y, ANGLE, KILLCOUNT` (verified to work).

**Design consequence:** the tool is a generic **`aim_at(target_id)`**. The executor **strafes or turns** depending on which buttons the scenario has, and each scenario only offers tools its buttons can perform (no `attack` in `health_gathering`). This replaces `turn_to` in the spec.

The labels buffer contains only objects **visible on screen**, plus the player's own `DoomPlayer` label, which we filter out. That is our information boundary: the agent never gets map knowledge it couldn't see.

---

## 4. One real decision step on `basic` (numbers from the live probe)

**Setup (once per episode):**

```python
game.load_config(scenarios_path / "basic.cfg")
game.set_window_visible(False)                # headless
game.set_mode(vzd.Mode.PLAYER)                # synchronous
game.set_labels_buffer_enabled(True)          # names + positions of visible objects
for v in (POSITION_X, POSITION_Y, ANGLE, KILLCOUNT):
    game.add_available_game_variable(v)       # our instrumentation
game.set_seed(seed); game.init(); game.new_episode()
```

Result: buttons `MOVE_LEFT, MOVE_RIGHT, ATTACK`; variables `AMMO2=50, POSITION=(-384, 32), ANGLE=0, KILLCOUNT=0`.

**Step A: Perception (code).** Labels: `Cacodemon at (0, 52)`, `DoomPlayer at (-384, 32)`. Drop the player and compute the target relative to the player: about **384 units ahead** and **20 units to the left**, so not yet in the aim cone. The LLM receives something like:

```
Scenario: basic. Goal: kill the monster. Ammo 50. Tic 14/300.
Visible: [id 0] Cacodemon — ahead 384u, offset 20u LEFT, not in aim cone.
Tools: observe(), aim_at(target_id), attack(burst)
```

**Step B: LLM call.** One chat request with `tools=[...]`. Qwen replies with a native tool call, e.g. `aim_at(target_id=0)`. (The 9/22 probe showed Qwen choosing a correct tool call in 3.2 s.)

**Step C: Validate (code).** Tool exists? `target_id=0` known and visible? Yes → pass. Otherwise → a rejection code (`UNKNOWN_TARGET`, `NO_ENEMY_IN_CONE`, `BAD_ARGS`, `UNAVAILABLE_TOOL`), fed back to the LLM, and **no button is pressed**.

**Step D: Execute (code). This is the quickstart loop living inside a tool:**

```python
while offset(target) > ALIGN_TOLERANCE and tics_used < MAX_TICS:
    game.make_action([1, 0, 0], 2)       # MOVE_LEFT for 2 tics
    if game.is_episode_finished():
        break
    refresh facts from game.get_state()
```

**Step E: Verify and record (code).** Before/after: offset 20 → 2, 6 tics used, target still visible. The result becomes a `ToolResult`, memory is updated, and a trace line is written with the exact buttons pressed. Frames are captured for the replay GIF.

**Next loop:** facts now say "in aim cone", Qwen calls `attack(burst=1)`, and the executor presses `[0, 0, 1]`. `KILLCOUNT` goes 0 → 1 and the episode ends. We record success, tics used, LLM calls and tokens.

---

## 5. Instructions (in order)

| # | Block | What you'll have | How to check it |
|---|---|---|---|
| 1 | **Scaffold** (45m) | uv project (Python 3.14), `vizdoom==1.3.1` + httpx + pydantic + imageio + pytest pinned, package skeleton, architecture guard tests | `uv run pytest` passes |
| 2 | **Preflight** (45m) | `doomlab preflight`: model listed, one real tool call, tries `chat_template_kwargs: {"enable_thinking": false}`, 2 overlapping requests, latency. Normalizes `RCAC_BASE_URL` ending in `/api` | `runs/preflight.json` has real numbers |
| 3 | **Env + perception** (1.5h) | `env/doom.py` (setup above) + `env/perception.py` (labels → facts, player filtered, ahead/offset/distance) | Unit tests on saved label fixtures; a live run prints the Cacodemon fact |
| 4 | **Tools + executor** (1.5h) | `observe`, `aim_at`, `attack` with preconditions + rejection codes, scenario-aware button mapping; executor is the only `make_action` caller | `attack` with nothing in the cone → `NO_ENEMY_IN_CONE`, no button pressed |
| 5 | **Scripted baseline** (15m) | Aim-then-shoot rule on the same executor, no LLM | Proves the plumbing before any LLM is involved |
| 6 | **ReAct loop + budget + trace** (1h) | `doomlab run --variant react_single --scenario basic --seed 0` | Episode ends with a classified outcome; JSONL trace exists |
| 7 | **Replay GIF** (45m) | Frames → `runs/<run>/<episode>.gif` | You can watch it |
| EOD | **5 dev episodes + summary + commit** | success, tics, LLM calls, tokens per episode | Printed table; tests green; committed |

### End-of-day deliverables

- [ ] `runs/preflight.json` (latency, thinking setting, usage availability)
- [ ] `doomlab run --variant react_single --scenario basic --seed 0` works
- [ ] 5 dev episodes on `basic` (seeds 0–4) with a summary table
- [ ] 1 replay GIF from a real trace
- [ ] Scripted baseline runs on `basic`
- [ ] Tests green, work committed

### Cut lines

- If tool calls are unreliable: force `tool_choice: "required"` and reduce to `aim_at` + `attack`.
- If Purdue is down: finish env/tools/scripted baseline and a replay; mark the LLM run blocked. Never fake a response.
- Don't start multi-agent work until one LLM episode runs cleanly.

---

## 6. Honest expectations

- **`basic` is easy on purpose.** The scripted rule will likely win nearly every time. Today proves the plumbing, not LLM cleverness. The interesting comparisons come on `defend_the_center` and `health_gathering` on Thursday.
- **Speed:** a `basic` episode is about 3–6 LLM calls at ~3 s each, so five episodes take a few minutes. Longer scenarios are where latency matters.
- **Replay:** rebuilt from recorded buttons + seed. If vizDoom isn't perfectly deterministic, fall back to frames captured during the run (the GIF uses those anyway).

---

## 7. EOD log (Wed 9/23 → finished early Thu 9/24)

```text
Sprint goal: met
Working commands: uv run doomlab preflight
                  uv run doomlab run --variant react_single --scenario basic --seeds 0-4
                  uv run doomlab replay runs/<run>/<trace>.jsonl
Evidence files: runs/preflight.json (git-ignored), data/calibration_basic_aim.json, runs/*/ traces + GIFs
Tests: 137 passing, 1 opt-in live Qwen test (DOOMLAB_LIVE=1)
Results (basic, dev seeds 0-4): scripted 5/5, react_single (qwen3.8:27b) 5/5, identical tics (median 43),
                  0 rejected calls; Qwen cost ~1,360 tokens and ~1.4 s LLM time per episode
Replay: 10/10 dev traces replay as exact matches (vizDoom is deterministic for us)
Failures learned from: Purdue retired qwen3.6:27b overnight (preflight caught it; switched to qwen3.8:27b);
                  strafing momentum made the first aim_at 6x too slow (268 -> 45 tics after predictive braking);
                  vizDoom resets its clock at episode end (tics now counted from presses);
                  unit-test fake had no momentum, so it hid the slowness (fake now models measured physics)
Still incomplete: CodeRabbit review of this commit (CLI not installed yet); 15u attack threshold only calibrated on basic
First task tomorrow: graph engine + router + recovery; commander/navigator/combat; success rules for the other scenarios
Scope cut: none
```

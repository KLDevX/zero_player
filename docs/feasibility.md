# Feasibility — training on the real game (stage 1, step 0)

Status: **done**. State, actions and speed work on the real game; one game still takes ≈ 10–70 s → recommendation: Python simulator for training, real game for testing (§10).
Build checked: Steam buildid `16736575`, `GlobalVariables.gd` says `v2.2.0` hotfix `6`, Godot `4.1.1.stable.custom`.
Every claim below cites `game_src/scripts/<file>:<line>` (local, git-ignored; never commit the code itself).

## 1. How we got the code
- The pack is embedded in the exe (PCK format 2, starts at byte 57 826 816, **not encrypted**, 3572 files).
- File offsets in the directory are **absolute in the exe** (`files_base` = 58 282 384), not relative to the
  pack start — first try read empty files because of that.
- GDScript is stored as **plain text** (Godot 4.1 has no bytecode export), so no GDRE Tools download was
  needed to read it. A 40-line Python reader extracted 99 single-player `.gd` files + `project.binary`
  into `game_src/` (`res://multiplayer/` skipped on purpose). GDRE is still needed later if we rebuild the
  project with a mod loader (scenes `.scn` are binary).

## 2. Speed
- **The developer already has a 10× key.** `GlobalVariables.gd:286-298`: with `mp_debugging` or
  `mp_debug_keys_enabled` true, keys `-` / `,` / `.` / `end` set `Engine.time_scale` to 0.05 / 1 / 10 / 0.
  Both flags are `false` in the release (`GlobalVariables.gd:30,32`). Same keys in `Debugging.gd:7-12`.
  So the game was played at 10× by its author — a good sign it survives it.
- Game timers use `get_tree().create_timer(t, false)` (e.g. `RoundManager.gd:92`), i.e. they **follow**
  `Engine.time_scale`. Score/prize timers use `get_process_delta_time()` (scaled too).
- Things that reset our speed (a mod must re-apply its scale or patch them):
  - `RoundManager.gd:63` sets `Engine.time_scale = 1` in `_ready()` (scene load).
  - `ShotgunShooting.gd:69` calls `TimeScaleManager.BeginTimeScaleLerp(.2, 1.0)` when the dealer is killed
    (slow-mo), and `TimeScaleManager.gd:21-27` lerps `Engine.time_scale` back to **1.0**.
- Not verified yet: physics (ejected shells), audio pitch, animation glitches at 5–10×.

## 3. State — where it lives (all reachable from one `RoundManager` node)
| What | Where |
|---|---|
| Shell order (hidden!) | `ShellSpawner.sequenceArray` (`ShellSpawner.gd:20`), `[0]` is the chambered shell (`ShotgunShooting.gd:109`) |
| Live/blank count at load (public) | `roundArray[currentRound].amountLive/amountBlank` (`ShellSpawner.gd:49-51`) |
| HP | `RoundManager.health_player`, `health_opponent` (`RoundManager.gd:14-15`); max HP `roundArray[i].startingHealth` |
| Items | `ItemManager.itemArray_player`, `itemArray_dealer` (`ItemManager.gd:36,40`); counts per item in `amounts.array_amounts[*].amount_player/amount_dealer` (`AmountResource.gd:9-10`) |
| Saw active / damage | `RoundManager.barrelSawedOff`, `currentShotgunDamage` (`RoundManager.gd:50,57`) |
| Cuffs | `RoundManager.dealerCuffed`, `playerCuffed`, `playerAboutToBreakFree` (`RoundManager.gd:53-55`) |
| Dealer's knowledge | `DealerIntelligence.sequenceArray_knownShell`, `knownShell`, `dealerKnowsShell` (`DealerIntelligence.gd:31,72-73`) |
| Whose turn / waiting for input | player turn begins in `RoundManager.BeginPlayerTurn()` → `perm.SetInteractionPermissions(true)` (`RoundManager.gd:308-334`, also `ShellLoader.gd:94-98`); dealer turn `DealerIntelligence.BeginDealerTurn()` |
| Stage inside a run | `playerData.currentBatchIndex` 0..2, `RoundManager.currentRound` = load inside a batch |
| Double or Nothing | `RoundManager.endless`, `double_or_nothing_rounds_beat`, `double_or_nothing_score`, `double_or_nothing_initial_score`, `initial_time` (`RoundManager.gd:47,369-371,73`) |

**Player knowledge is not stored by the game.** Magnifier (`ItemInteraction.gd:142-146`) and burner phone
(`BurnerPhone.gd:6-35`) only show it in an animation/text. The bridge must record it itself (read
`sequenceArray[0]` / the phone's index at use time) and pass the agent only public info + its own
knowledge — never the full `sequenceArray`.

## 4. Actions — functions the mouse clicks end up in (`InteractionManager.gd:45-96`)
- Shoot: `shotgun.GrabShotgun()`, then `shotgun.Shoot("self")` or `shotgun.Shoot("dealer")`.
- Use item: `itemInteraction.PickupItemFromTable(itemParent, itemName)` (`ItemInteraction.gd:51`).
- Adrenaline steal: same call with the dealer's item while `stealing` is true (`ItemInteraction.gd:63-66`).
- Item draw at load start: `itemManager.GrabItem()` and `itemManager.PlaceDownItem(gridIndex)`.
- Double or Nothing choice: `roundManager.Response(true|false)` (`RoundManager.gd:432`).
So a mod can play by calling these directly, no fake clicks.

## 5. Double or Nothing rules seen in code (for the simulator)
- Each load: HP 2–4, shells 2–8 with `live = max(1, total/2)`, items 2–5 per load, order shuffled
  (`RoundManager.gd:142-157`).
- Dealer in endless deduces the shell from public counts + its own memory (`DealerIntelligence.gd:96-104,282-303`)
  and its "coin flip" picks the majority colour (`DealerIntelligence.gd:421-431`). It does not read the
  hidden order directly except where a real player could know it (last shell, after its own magnifier).
- **Prize ≠ progress** (Akel's point, confirmed): first prize `= 70000 − initial_time/600·40000` (min 10)
  after beating 3 batches (`RoundManager.gd:385-396`); each next cycle doubles it (`RoundManager.gd:397-402`);
  the leaderboard uploads `initial · 2^(rounds_beat−1)` (`LeaderboardManager.gd:176-181`).
  The prize depends on how fast the first cycle was, so our **main progress metric is rounds survived**,
  not money. The game's "ROUNDS BEAT" counter is `brief.ending.endless_roundsbeat`, +1 per batch indicator
  (`RoundManager.gd:186`); check live whether it counts the batch you die in.

## 6. Online parts to switch off in the bridge mod
- Leaderboard upload: `EndingManager.gd:175` → `LeaderboardManager.UploadScore()` when `using_steam`.
  The mod must stub `UploadScore` before any automated game.
- Achievements (`AchievementManager.gd`) — harmless, Akel's call.

## 7. Live test 1 — reading state works (2026-10-23)
**Route: no download, no exe patch.** Godot reads `override.cfg` next to the exe at startup; ours adds one
autoload, `player/buckshot/bridge/bridge.gd` (absolute path works in the exported game). Setup:
- Save files backed up to `game_lab/save_backup_2026-10-23/`; game copied to `game_lab/game/` (git-ignored),
  `override.cfg` copied there. The Steam folder is untouched.
- The bridge sets `GlobalVariables.using_steam = false` before the scenes load → no leaderboard upload, no
  achievements (`EndingManager.gd:175`, `LeaderboardManager.gd:22`). Steam was not running anyway
  (`steam init: Steam not running`), and the copy still runs fine without it.
- It also sets `mp_debug_keys_enabled = true`, so `.` = 10× and `,` = 1× work.
- It finds `RoundManager` by script path (`/root/main/standalone managers/round manager`), again after each
  scene reload (death → main), and appends one JSON line per state change to `reports/live_*.jsonl`
  (`public` part + `_hidden` part for checking only). Watch it live: `python -m player.buckshot.bridge.watch`.

Results of Akel's first game (one Double-or-Nothing run, died in round 3):
- All fields read correctly and change as expected: HP both sides, loaded live/blank and max HP per load,
  shells left, item counts on both sides, cuffs, saw, rounds beat. 168 state lines, 0 script errors.
- `rounds_beat` was 3 when he died in round 3 → the counter **includes the round you die in**; rounds
  survived = `rounds_beat − 1` on death.
- Speed: `time_scale` 10 seen (the dev key works); 0.56 / 0.83 values are the game's own slow-mo after a
  dealer kill lerping back to **1** (confirms §2 — a bot must re-apply its speed).
- The run took 531 s at mostly 1× **with a human thinking**; 25 player decision points. Not yet a clean
  game-time measurement.
- `player_input` (= `deskUI_shotgun.visible`) is also true outside a turn (e.g. before the first load) →
  needs a better "waiting for the player" signal before the bridge sends actions.
- The game process ended with exit code 139 right after "changing scene to: menu" — Akel had closed the
  window there, so this one is a crash on close, not in play.

## 8. Live test 2 — actions and speed (random test bot)
**Actions work.** The bridge listens on `127.0.0.1:47800` (JSON lines; `player/buckshot/bridge/client.py`).
`state` returns the public state plus the **legal actions** = every `InteractionBranch` the player could
click right now (allowed, not invalid, collider on, cursor visible, whitelisted alias). `act` performs one
through `InteractionManager.MainInteractionEvent()` — the same code path as a mouse click. Covers menu
start, pills (switch to Double or Nothing), doors, waiver + signature keys, item draw (`briefcase intake`,
`grid:N`), items, adrenaline steal, shotgun + `text you`/`text dealer`, `double yes`/`no`.
`python -m player.buckshot.testbot --games N --speed X --mute` plays with random legal table moves
(navigation scripted) and appends each game to `reports/games.csv`. It is a test tool, **not** an agent.

Problems found and fixed on the way:
- Clicking 50 ms after grabbing the shotgun (mid-animation) froze the game → the bot now acts only when
  the legal set has been stable for 0.6 s of game time (human-like reaction).
- During an adrenaline steal the game leaves the player's own items "allowed", but the camera faces the
  dealer's side so a human can't click them (Akel's catch) → the bridge offers only dealer items then.
- After the first dealer kill `TimeScaleManager` keeps writing `Engine.time_scale = 1.0` every frame (its
  `moving` flag is never cleared) → speed silently fell to 1× (Akel saw it). The bridge now clears the flag
  and sets its scale last in the frame (`process_priority`); the log records the real per-frame scale.
- Waiver: lowercase keys; one letter is enough.

Measured on Akel's laptop (games start at the pills, include the walk to the table; random moves, so most
die in round 1 — a stronger player plays longer games):

| speed | games | seconds per game | seconds per action | crashes / stalls |
|---|---|---|---|---|
| 1× | 1 (partial) | — (≈ 5 min to round 2) | ≈ 3–5 | 1 crash (exit 139) while drawing items, cause unknown |
| 5× | 2 | 23.6, 24.0 | ≈ 1.06 | 0 |
| 10× | 5 (after the fix) | 67.9, 30.4, 43.0, 10.9, 41.7 (mean 38.8) | ≈ 0.62 | 0 |
| 20× | 2 | 10.0, 20.2 | ≈ 0.44 | 0 |

The real per-frame scale stayed at 10 for the whole 10× run (one 0.22 frame). No physics or animation
breakage seen at 10× and 20×. Above 10× the gain shrinks (≈ 0.1 s per action is bot + polling overhead).

## 9. Fragility
- Pinned to this build (v2.2.0.6, buildid 16736575): script paths, node names and variable names come from
  the code. An update may rename them; `override.cfg` itself survives updates.
- One unexplained crash (exit 139) in ~12 bot games; a frozen game needs a restart (no auto-recovery yet).
- Timing-sensitive: clicks must wait for animations; the game's own slow-mo fights the speed.
- Runs only with the game window open (one game at a time on this laptop), and only in the lab copy.

## 10. Recommendation (decision rule from `CLAUDE.md`)
State ✔ and actions ✔ on the real game, speed ✔ (10–20× without breaking). **But a game takes ≈ 10–70 s
even at 10–20×** (mean ≈ 39 s at 10× for a *random* player; a good player survives more rounds, so its
games get longer). The rule says ≲ 10 s → this fails. Q-learning needs tens of thousands of games:
10 000 games × 40 s ≈ 110 hours on one window.

→ **Build the Python simulator** (`player/buckshot/sim.py`) from the decompiled rules (§3–§5, dealer ported
from `DealerIntelligence.gd`) and train there. Use the real game through this bridge to **test** the
trained agent (and to check the simulator against real games: same state fields, same legal actions),
and later for the "thoughts" overlay.

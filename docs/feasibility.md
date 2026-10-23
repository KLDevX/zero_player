# Feasibility — training on the real game (stage 1, step 0)

Status: **part 1 of 2 done (code reading)**. Part 2 (live test: mod/bridge, speed, seconds per game) is next.
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

## 7. Next (part 2, live)
1. Pick the mod route: BRML-E vs. a loader baked into a rebuilt copy (game is v2.2.0.6; BRML targets old
   builds). Downloads only after Akel's "да".
2. Hello-world mod in a **separate copy** of the game: print the state table above each turn, stub
   `UploadScore`.
3. Speed test at 2×, 5×, 10×; measure seconds per Double-or-Nothing run; note what breaks.
4. Apply the decision rule (`CLAUDE.md`) and write the recommendation here.

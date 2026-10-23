# Simulator rules (`player/buckshot/sim.py`) and how sure we are

Confidence: **code** = read in the game's script (file:line in `game_src/scripts/`), **log** = seen in our
live logs (`reports/live_*.jsonl`), **guess** = not verifiable yet (scene data), marked for checking.

## Version 1 (no items)
| Rule | Sim | Confidence |
|---|---|---|
| A game = rounds (batches) until the player dies; 3 rounds = one Double-or-Nothing cycle, then take the prize or continue | `_win_batch` | code `RoundManager.gd:482-497, 432-457` |
| Each round: HP 2–4, same for both | `_start_batch` | code `RoundManager.gd:145`, `HealthCounter.gd:39-40` |
| Each load: total 2–8, live = max(1, total // 2), blank = rest | `_load` | code `RoundManager.gd:148-150`; log |
| New load whenever the gun is empty; HP carries over inside a round | `_advance` | code `RoundManager.gd:290-295` |
| The player moves first after every load | `_advance` | code `ShellLoader.gd:92-98` |
| Blank at yourself → you go again; otherwise the turn passes | `_shoot` | code `ShotgunShooting.gd:136-137`, `DealerIntelligence.gd:305-323` |
| Live = 1 damage (saw = 2, comes with items) | `_shoot` | code `ShotgunShooting.gd:119-131` |
| Dealer without items: knows the shell if it is the last one, all left are one colour, or its memory settles it → blank: self, live: player; otherwise majority colour, coin flip on a tie | `_dealer_choice` | code `DealerIntelligence.gd:96-110, 282-303, 421-431` |
| Dealer counts the real shells (matters once the inverter exists) | `_dealer_choice` | code `DealerIntelligence.gd:285-292` |
| Some loads are not shuffled: all lives first, then blanks | `shuffle_flags` | code `RoundManager.gd:156-157`, `ShellSpawner.gd:118`; log: 28 of 75 sorted vs ≈ 12 by chance |
| Number of round slots (5) and their start value (unshuffled), flags kept between games | `ROUND_SLOTS` | **guess** — scene data; refine from more logs |
| Rounds-beat counter includes the round you die in (game display) — the sim counts only won rounds | `rounds_beat` | log |

## Next versions
- v2: items — handcuffs, beer, magnifier, cigarettes, handsaw, expired medicine, inverter, burner phone,
  adrenaline (steal); 2–5 items per load, 8 slots each, per-item caps (`amount_don`), dealer item logic.
- Prize (`70000 − time/600·40000`, then ×2) is not simulated: it depends on real time; we track rounds.

# Simulator rules (`games/buckshot_roulette/sim.py`) and how sure we are

Confidence: **code** = read in the game's script (file:line in `games/buckshot_roulette/game_src/scripts/`), **scene** = read from
the game's scene data (`main.scn`, values below), **log** = seen in our live logs (`games/buckshot_roulette/reports/live_*.jsonl`),
**guess** = not verifiable yet. `BuckshotEnv(items=False)` keeps the v1 rules (no items).

## Rounds, loads, turns
| Rule | Sim | Confidence |
|---|---|---|
| A game = rounds (batches) until the player dies; 3 rounds = one Double-or-Nothing cycle, then take the prize or continue | `_win_batch` | code `RoundManager.gd:482-497, 432-457` |
| Each round has 5 load slots, regenerated at round start: HP 2–4, total 2–8 shells, 2–5 items each | `_start_batch` | code `RoundManager.gd:142-157`; scene: 5 `RoundClass` per batch |
| HP for both sides comes from slot 0 and carries over between loads of the round | `_start_batch` | code `HealthCounter.gd:31-40` |
| Loads after the 5th reuse slot 5 (same counts and item count) | `_load` | code `RoundManager.gd:197` |
| live = max(1, total // 2), blank = rest → never more live than blank | `_start_batch` | code `RoundManager.gd:148-150`; log |
| The loaded order is always random: every slot has `insertingInRandomOrder = 1`, so the gun is shuffled after the shells are shown | `_load` | scene; code `ShellSpawner.gd:89-91`; log: 9 of 35 sorted loads vs ≈ 6 by chance |
| The player moves first after every load | `_end_turn` | code `ShellLoader.gd:92-98` |
| Blank at yourself → you go again; otherwise the turn passes | `_shoot` | code `ShotgunShooting.gd:136-137`, `DealerIntelligence.gd:305-323` |
| Live = 1 damage, 2 with the saw | `_shoot` | code `ShotgunShooting.gd:119-131` |

## Items
| Rule | Sim | Confidence |
|---|---|---|
| Each load both sides draw the slot's item count, one by one, uniform among items below their cap; 8 slots per side; full → the rest is lost | `_draw_items` | code `ItemManager.gd:213-262, 344-395` |
| Caps in Double or Nothing (`amount_don`): handcuffs 1, beer 2, magnifier 3, cigarettes 1, handsaw 3, expired medicine 1, inverter 8, burner phone 1, adrenaline 2 | `ITEM_CAPS` | scene |
| No handsaw in the first load of a round with 2 HP | `_load` | code `ItemManager.gd:238-239, 356-357` |
| Items are cleared at a new round, but **kept** from round 3 into the next cycle | `_win_batch`, `step` | code `RoundManager.gd:482-497, 508`, `ItemManager.gd:118-132` |
| Handcuffs: the dealer skips his next turn, then breaks free; not usable on a cuffed dealer; all cuffs come off at a new load | `_end_turn`, `_load` | code `DealerIntelligence.gd:39-57`, `HandcuffManager.gd:40-55`, `PermissionManager.gd:68` |
| Beer: ejects the chambered shell (everyone sees it); the last one → new load | `_use_item` | code `ItemInteraction.gd:130-141` |
| Magnifier: the player sees the chambered shell | `_use_item` | code `ItemInteraction.gd:142-146` |
| Cigarettes: +1 HP up to max | `_use_item` | code `HealthCounter.gd:141-148` |
| Handsaw: next shot does 2, then the barrel grows back; not usable twice | `_use_item`, `_shoot` | code `ItemInteraction.gd:153-158`, `RoundManager.gd:269-273`, `PermissionManager.gd:70` |
| Expired medicine: 50% +2 HP (capped), 50% −1 HP (can kill) | `_use_item` | code `MedicineManager.gd:17-38, 72-75`, `HealthCounter.gd:146-148` |
| Inverter: flips the chambered shell; the player doesn't see the result unless he knew the shell | `_use_item` | code `ItemInteraction.gd:165-171` |
| Burner phone: tells one random later shell (index 1..n−1, index 7 is reported as 6); nothing if it's the last shell | `_use_item` | code `BurnerPhone.gd:6-35` |
| Adrenaline: steal one dealer item (not adrenaline) and use it at once | `legal_actions`, `step` | code `ItemManager.gd:399-432`, `ItemInteraction.gd:51-104` |
| Items are kept in the order they were drawn | `items_player`, `items_dealer` | code `DealerIntelligence.gd:121-142` |

## The dealer (`_dealer_turn`, `DealerIntelligence.gd:65-281, 282-303, 421-431`)
Each step of his turn he goes through his items **in draw order** and takes the first one a rule wants,
uses it, and starts again; when no rule fires he shoots.
| Rule | Confidence |
|---|---|
| Knows the shell if it is the last one, or the real counts + his phone memory settle it → target: blank → self, live → player | code `:96-110, 282-303` |
| Magnifier: if he doesn't know the shell (and it isn't the last) | code `:144-151` |
| Cigarettes: if hurt | code `:152-156` |
| Expired medicine: if hurt, no cigarettes, HP ≠ 1, once per turn; 50% +2 / 50% −1 | code `:157-161, 230-235`, `HealthCounter.gd:126-135` |
| Beer: if the shell isn't known live (also when known blank!); forgets the shell but keeps his target | code `:162-168` |
| Handcuffs: if the player isn't cuffed (and it isn't the last shell) | code `:169-172` |
| Handsaw: if the shell is known live | code `:173-178` |
| Burner phone: if more than 2 shells; remembers one random later shell | code `:179-186` |
| Inverter: if he knows it's blank → live, shoot the player | code `:187-193` |
| No rule fired but he has a saw and the shell isn't known blank: coin flip → saw + shoot player, or shoot himself | code `:204-215` |
| With adrenaline in hand he also looks at the player's items (after his own) and steals one when a rule wants it and he has no copy | code `:121-142, 242-257` |
| Shot with no target: majority colour of the real shells, coin flip on a tie | code `:326-329, 421-431` |
| Counts the real shells (so he "sees" an inversion) | code `:285-292` |

Check against the real game: a random player survives **0.185** rounds/game in the sim vs **0.18** for the
random test bot on the real game (11 games through the bridge).

## Observation (what the agent sees)
HP both sides, max HP, original live/blank left in the gun, whether the chambered shell was inverted, the
last shell that left the gun, its own knowledge (current shell, later shells from the phone), items on both
sides, saw, cuffs, phase (turn / steal / double). Never the order, never the dealer's knowledge.

## Not simulated
- The prize (`70000 − time/600·40000`, then ×2): it depends on real time; we track rounds.
- Timers (adrenaline steal 7 s), animations.

## Corrections
- 2026-10-23: v1 had an "unshuffled loads" quirk taken from logs. Wrong: the logs caught the shells while
  shown on the table, before the second shuffle. Removed; Q-table result unchanged (73.1% vs 73.2%).

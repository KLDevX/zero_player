# Progress log — versions of the player

Each version is a git tag (`git checkout <tag>` shows the code as it was) and its trained checkpoints are
kept in `runs/archive/<tag>/` (local only, git-ignored). Numbers: simulator, 10 000 games, exploration off.

| tag | date | what | rounds/game | round win rate |
|---|---|---|---|---|
| — | 2026-10-23 | random player (baseline) | 0.64 | 39.1% |
| `v0.1-qtable-no-items` | 2026-10-23 | sim v1 without items, Q-table, 100k games in 17 s | 2.73 | 73.2% |
| — | 2026-10-23 | random player, **full rules with items** (sim v2) | 0.185 | 15.6% |
| `v0.2-qtable-items` | 2026-10-23 | sim v2 (items, dealer items), Q-table on HP + shells, 300k games in 219 s | 1.52 | 60.4% |
| `v0.3-dqn` | 2026-10-23 | sim v2, **DQN** (50 → 64 → 64 → 21), 100k games in 32 min | 3.56 | 78.1% |
| `v0.4-reward-shaping` | 2026-10-23 | DQN d2: + HP potential (safe shaping) | 3.79 | 79.1% |
| `v0.4-reward-shaping` | 2026-10-23 | DQN **d3** (Akel's reward): −0.1 per HP lost, −0.02 per action | **4.28** | **81.1%** |

## v0.1-qtable-no-items
- Simulator: rounds, HP 2–4, loads 2–8, the dealer's item-free logic, and an "unshuffled loads" quirk that
  turned out to be wrong (removed in v2; see docs/sim-rules.md → Corrections).
- Agent sees HP, live/blank left, the last fired shell. 669 states.
- Learning curve (rounds/game per tenth of training): 0.71 0.93 1.25 1.63 2.19 2.51 2.52 2.46 2.53 2.53.
- Checkpoints: @100 0.83, @1 000 1.94, @10 000 2.62, @100 000 2.73.

## v0.2-qtable-items
- Sim v2: 5 load slots per round, item caps from the game's scene data, all 9 items for both sides,
  adrenaline steals, the dealer's item rules in draw order. Random player 0.185 rounds/game — the random
  test bot on the real game got 0.18.
- Q-table on the basic state (HP + shells; items only as available moves), 300k games, 219 s:
  learning curve 0.22 0.32 0.47 0.70 1.06 1.33 1.33 1.35 1.35 1.32; checkpoints @10k 0.86, @100k 1.51,
  @300k 1.52 rounds/game (60.4% rounds won).
- What it learned to use when available: magnifier 42%, cigarettes 33%, adrenaline 26%, beer 19%,
  inverter 15%; steals cigarettes 61% and magnifier 58%; shoots the dealer 42%, itself 4%; always doubles.
- Q-table on the **full** state (all items, cuffs, saw, phone knowledge): stopped at 76k games — 705 844
  different states (≈ 10 new per game), ~2.5 GB RAM, plays like random (0.19). The table can't cover it →
  the next agent is a neural network (DQN) that generalises between similar states.
- Q-table without items retrained on the corrected rules: 2.72 rounds/game, 73.1%.

## v0.3-dqn
- Agent: a neural network (PyTorch, CPU). 50 inputs (everything it observes, only scaled), two hidden
  layers of 64, 21 outputs = value of each move; replay memory, target network, Double-DQN, illegal moves
  masked. Same reward as the table: 1 per round won.
- 100k games, 32 min (2.9 M moves). Learning curve: 0.22 0.33 0.52 0.88 1.70 2.67 2.71 2.75 2.82 2.73.
- Checkpoints (5 000 games each, exploration off): @1 000 0.67, @10 000 1.63, @100 000 **3.56 rounds/game,
  78.1% rounds won, best game 35 rounds** — better than the Q-table even in the easier no-item game (2.72).
- Uses when available: handsaw 52%, adrenaline 51% (steals saw 61%, cuffs 58%, magnifier 49%), handcuffs
  37%, magnifier 27%; shoots the dealer 37%, itself 9%; always doubles.
- Money (not trained for it): it never takes the prize. Had it stopped after the first cycle: 49% × first
  prize; after the second: 23% × 2 = 0.47 × first prize.
- Pictures: `docs/img/v0.3-learning-curves.png`, `docs/img/v0.3-network-d1.png`
  (`python -m player.buckshot.viz curves|network <checkpoint>`); live: `tensorboard --logdir runs`.

![learning curves](img/v0.3-learning-curves.png)
![network](img/v0.3-network-d1.png)

## v0.4-reward-shaping (Akel's experiment) + overlay v1
Same network, simulator and seed as d1; only the reward changes (`train.py --shaping`).
| run | reward on top of +1 per round won | rounds/game | rounds won | moves per round |
|---|---|---|---|---|
| d1 | — | 3.56 | 78.1% | 11.5 |
| d2 | + 0.1 × change of (my HP − dealer HP) / max HP (potential-based) | 3.79 | 79.1% | 11.0 |
| d3 | − 0.1 per HP lost, − 0.02 per action | **4.28** | **81.1%** | **9.8** |
(5 000 games, exploration off; moves per round from the replays.)

Why d3 wins (from the replays, `reports/replays/*/stats.json`): it is **faster** — 9.8 moves per round
instead of 11.5, so the dealer gets fewer turns to draw items and hit back — and the HP penalty arrives
on the very move that lost HP. It is *not* tidier with items: it wastes cigarettes at full HP more often
(53% vs 32%), and the speed cost makes it skip the saw on a known live shell 22% of the time (d1 3%).
Learning curves (per tenth): d3 0.23 0.35 0.60 1.08 2.24 3.51 3.46 3.43 3.41 3.39.

Overlay v1 works on the lab copy: hint mode and play mode (see docs/overlay-design.md). First real games
of d1 through it: 3 games, 1.33 rounds/game (too few to judge; Akel saw it skip cigarettes and beer — d1
also rarely uses them in the simulator: beer 9%, cigarettes 15% of the time they are possible). Every live
decision is now logged to `reports/live_thoughts/` and checked by `python -m player.buckshot.livecheck`.

![results](img/v0.4-compare-results.png)
![moves](img/v0.4-compare-moves.png)
![mistakes](img/v0.4-compare-mistakes.png)
![learning curves](img/v0.4-learning-curves.png)

# All trained networks — one table

Test set: 18864 tables from 300 new games labelled by x1 (never seen in training). Results: 5 000 games, simulator seed 7, exploration off.

Accuracy is measured against x1 with base d3.1.3-s2 — the teacher of dx and x1's own base player, so those two have a head start on it.

| network | what | training | rounds/game | rounds won | best game | picks x1's best move | at most 1/16 below best | chance lost per move |
|---|---|---|---|---|---|---|---|---|
| d1 | DQN, +1 per round | 32 min | 3.51 | 77.8% | 41 | 67% | 81% | 4.8 pts |
| d2 | DQN, HP potential | 43 min | 3.80 | 79.2% | 39 | 67% | 82% | 4.6 pts |
| d3 | DQN, −HP −action (Akel) | 49 min | 4.44 | 81.6% | 41 | 68% | 82% | 4.5 pts |
| d2.1 | DQN, HP events | 41 min | 3.93 | 79.7% | 33 | 67% | 82% | 4.6 pts |
| d3.1 | DQN, HP events − item cost | 42 min | 4.64 | 82.3% | 43 | 69% | 83% | 4.2 pts |
| d4.1 | DQN, v4 reward + n-step | 29 min | 3.35 | 77.0% | 33 | 67% | 81% | 4.8 pts |
| d4.2.3-s0 | DQN, v4 (cigarettes free), 3 seeds × 32 tables | 22 min | 3.81 | 79.2% | 45 | 67% | 82% | 4.8 pts |
| d4.2.3-s1 | DQN, v4 (cigarettes free), 3 seeds × 32 tables | 22 min | 3.42 | 77.4% | 31 | 67% | 81% | 4.8 pts |
| d4.2.3-s2 | DQN, v4 (cigarettes free), 3 seeds × 32 tables | 21 min | 3.23 | 76.3% | 27 | 67% | 81% | 5.0 pts |
| d3.1.3-s0 | DQN d3.1, 3 seeds × 32 tables | 30 min | 5.02 | 83.4% | 48 | 69% | 84% | 4.2 pts |
| d3.1.3-s1 | DQN d3.1, 3 seeds × 32 tables | 30 min | 5.28 | 84.1% | 66 | 69% | 84% | 4.1 pts |
| d3.1.3-s2 | DQN d3.1, 3 seeds × 32 tables | 30 min | 5.53 | 84.7% | 49 | 71% | 85% | 3.6 pts |
| dx1.0 | network learned from the x1 planner | 17 min with lessons | 4.84 | 82.9% | 62 | 70% | 84% | 3.9 pts |
| dx1.1 | network learned from the x1 planner | 30 min with lessons | 5.49 | 84.6% | 53 | 71% | 85% | 3.7 pts |
| dx1.2 | network learned from the x1 planner | 45 min with lessons | 5.61 | 84.9% | 47 | 71% | 85% | 3.7 pts |
| dx1.3 | network learned from the x1 planner | 61 min with lessons | 5.92 | 85.5% | 61 | 71% | 85% | 3.6 pts |
| dx1.4 | network learned from the x1 planner | 77 min with lessons | 5.87 | 85.5% | 60 | 71% | 86% | 3.5 pts |
| dx1.5 | network learned from the x1 planner | 93 min with lessons | 5.99 | 85.7% | 57 | 71% | 85% | 3.5 pts |

## Learning progress (rounds/game per tenth of training, exploration on)

- **d1**: 0.2 0.3 0.5 0.9 1.7 2.7 2.7 2.7 2.8 2.7
- **d2**: 0.2 0.3 0.5 0.9 1.8 2.7 2.8 2.7 2.7 2.6
- **d3**: 0.2 0.4 0.6 1.1 2.2 3.5 3.5 3.4 3.4 3.4
- **d2.1**: 0.2 0.3 0.5 0.9 1.8 2.9 3.1 3.1 3.0 2.9
- **d3.1**: 0.2 0.3 0.6 1.0 1.9 3.2 3.4 3.5 3.6 3.6
- **d4.1**: 0.2 0.4 0.6 0.9 1.6 2.3 2.4 2.5 2.5 2.5
- **d4.2.3-s0**: 0.2 0.4 0.6 1.0 2.0 2.9 3.0 2.9 2.8 2.8
- **d4.2.3-s1**: 0.2 0.4 0.6 1.0 1.9 2.7 2.7 2.8 2.8 2.8
- **d4.2.3-s2**: 0.2 0.4 0.6 1.0 1.9 2.6 2.6 2.6 2.6 2.5
- **d3.1.3-s0**: 0.2 0.4 0.6 1.1 2.3 3.7 3.8 3.9 3.9 3.8
- **d3.1.3-s1**: 0.2 0.4 0.6 1.1 2.3 3.7 3.8 3.7 3.8 3.8
- **d3.1.3-s2**: 0.2 0.4 0.6 1.0 2.3 3.7 3.9 3.8 3.8 3.8
- **dx1** (per version, exploration off, 5 000 games): dx1.0 4.84 → dx1.1 5.49 → dx1.2 5.61 → dx1.3 5.92 → dx1.4 5.87 → dx1.5 5.99

## Clear mistakes (share of the cases; lower is better)

| network | shoots itself on a known live | known blank at the dealer | magnifier on a known shell | cuffs on the last shell | beer on a known live | inverter on a known live |
|---|---|---|---|---|---|---|
| d1 | 0% | 2% | 7% | 2% | 8% | 8% |
| d2 | 0% | 7% | 11% | 4% | 7% | 4% |
| d3 | 0% | 3% | 5% | 0% | 1% | 3% |
| d2.1 | 0% | 10% | 7% | 0% | 4% | 2% |
| d3.1 | 0% | 1% | 3% | 2% | 5% | 3% |
| d4.1 | 0% | 0% | 2% | 1% | 1% | 2% |
| d4.2.3-s0 | 0% | 1% | 2% | 1% | 1% | 2% |
| d4.2.3-s1 | 0% | 1% | 3% | 3% | 2% | 4% |
| d4.2.3-s2 | 0% | 1% | 2% | 2% | 1% | 1% |
| d3.1.3-s0 | 0% | 3% | 2% | 0% | 3% | 3% |
| d3.1.3-s1 | 0% | 1% | 4% | 2% | 4% | 4% |
| d3.1.3-s2 | 0% | 0% | 3% | 1% | 2% | 2% |
| dx1.0 | 0% | 2% | 9% | 2% | 1% | 4% |
| dx1.1 | 0% | 1% | 8% | 1% | 2% | 4% |
| dx1.2 | 0% | 1% | 8% | 1% | 1% | 4% |
| dx1.3 | 0% | 1% | 7% | 1% | 1% | 5% |
| dx1.4 | 0% | 1% | 7% | 1% | 1% | 5% |
| dx1.5 | 0% | 1% | 7% | 1% | 1% | 5% |

## Tactics: who found what

| network | inverter tactic done (of chances) | steals the dealer's saw on a known live | cuffs that paid off | favourite combo |
|---|---|---|---|---|
| d1 | 205 of 1089 (19%) | 45% | 76% | handcuffs → shoot_dealer (6465×) |
| d2 | 121 of 1011 (12%) | 37% | 77% | handcuffs → shoot_dealer (6417×) |
| d3 | 455 of 785 (58%) | 34% | 87% | handcuffs → shoot_dealer (11185×) |
| d2.1 | 68 of 692 (10%) | 43% | 85% | handcuffs → shoot_dealer (6121×) |
| d3.1 | 56 of 966 (6%) | 16% | 81% | handcuffs → shoot_dealer (8087×) |
| d4.1 | 68 of 722 (9%) | 12% | 77% | handsaw → shoot_dealer (3927×) |
| d4.2.3-s0 | 54 of 896 (6%) | 31% | 77% | handsaw → shoot_dealer (4473×) |
| d4.2.3-s1 | 48 of 654 (7%) | 28% | 72% | handsaw → shoot_dealer (4294×) |
| d4.2.3-s2 | 33 of 676 (5%) | 8% | 70% | inverter → shoot_dealer (2981×) |
| d3.1.3-s0 | 98 of 1240 (8%) | 45% | 78% | magnifying glass → shoot_self (4974×) |
| d3.1.3-s1 | 155 of 1318 (12%) | 62% | 84% | handcuffs → shoot_dealer (9039×) |
| d3.1.3-s2 | 84 of 1201 (7%) | 42% | 82% | handcuffs → shoot_dealer (8714×) |
| dx1.0 | 122 of 1128 (11%) | 47% | 77% | handcuffs → shoot_dealer (5659×) |
| dx1.1 | 103 of 1125 (9%) | 42% | 79% | handcuffs → shoot_dealer (6048×) |
| dx1.2 | 145 of 1125 (13%) | 43% | 78% | handcuffs → shoot_dealer (6525×) |
| dx1.3 | 184 of 1233 (15%) | 41% | 79% | handcuffs → shoot_dealer (6669×) |
| dx1.4 | 177 of 1216 (15%) | 40% | 79% | handcuffs → shoot_dealer (6432×) |
| dx1.5 | 224 of 1281 (17%) | 44% | 79% | handcuffs → shoot_dealer (6142×) |

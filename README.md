# zero_player

[Русская версия](README.ru.md)

An AI that learns to play video games by itself — one module per game.
The first one plays **Buckshot Roulette** (Double or Nothing mode); **Balatro** is next.

| game | version | status | best result |
|---|---|---|---|
| [Buckshot Roulette](games/buckshot_roulette/) | v2.2.0.6 (Steam build 16736575) | done (stage 1) | dx1.5: 5.99 rounds per game in the simulator (85.7 % of rounds won); on the real game a clean AI run survived 24 rounds and earned the Steam achievement "1 000 000 and died" |
| Balatro | — | next | — |

```
python zero_player.py                         # the games, their versions and models
python zero_player.py buckshot_roulette       # start the game copy with the AI (default model dx1.5)
```
How to run everything: [games/buckshot_roulette/docs/how-to-run.md](games/buckshot_roulette/docs/how-to-run.md)
(in Russian).

## Layout
```
zero_player.py      starts a game with a model (reads games/<game>/game.toml)
core/               shared by every game: the agent's Thought, the brain ↔ game protocol
games/<game>/       everything about one game: its mod (bridge), simulator, agents, models, reports, docs
```
The games themselves, their decompiled code and the raw logs and videos are never in this repository
(see `.gitignore`): only our own code, the best trained networks and the result summaries.

## Rules the project keeps
- Single-player only: no multiplayer, no leaderboards (the mod switches the leaderboard off).
- The agent sees only what a player could know; it learns its strategy by itself.
- A copy of the game is modded, never the installed one.

Author: Akel (KLDevX). Built with the help of an AI coding assistant (Claude Code); see the project write-up.

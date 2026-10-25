# zero_player — example project instructions for an AI coding assistant

This is an example of the instructions file we used with Claude Code (`CLAUDE.md`, kept private: it has
personal notes). Copy it to `CLAUDE.md`, replace the placeholders and adjust the rules to how you work.

## Who you work with
`<your name>`, `<language you talk in>`. Code, comments and commit messages in English.

## The project
An AI that learns to play video games by itself, one module per game (see README.md).
- `zero_player.py` starts a game with a model (reads `games/<game>/game.toml`).
- `core/` holds only what every game shares: `core/thought.py` (what the agent "thinks" about a move) and
  `core/protocol.py` (the JSON protocol between the AI's brain and the game's mod: `state`, `act`, `thought`).
- Everything about a game lives in `games/<game>/`: code, `bridge/` (the mod), `models/`, `reports/`, `docs/`,
  `tests/`, and the git-ignored `game_copy/` (a copy of the installed game) and `game_src/` (decompiled code).
- Tests for Buckshot Roulette:
  `python -c "import games.buckshot_roulette.tests.test_sim as t; [getattr(t, x)() for x in dir(t) if x.startswith('test_')]"`

## Architecture (keep it)
- Core + modules: a new game plugs in as `games/<game>/`, it is not woven into the core.
- The simulator holds the **rules of the world**; the agent learns the **strategy** by itself. Never hard-code
  strategy into a learning agent.
- **What the agent sees:** only what a player could know (public counts, HP, items, what it revealed itself).
  Never hidden state, never what the opponent learned, never hints about a strategy.
- **Every game is saved** to `games/<game>/reports/` so statistics can be looked at later.
- **Main progress metric:** pick the one that really measures progress (for Buckshot: rounds survived, not
  money — the first prize depends on speed, later cycles only double it).
- **Checkpoints:** save frozen copies of an agent while it trains (e.g. after 100, 1 000, 10 000, 100 000
  games) to `games/<game>/models/<run>/` with their metadata.

## How to work
- Small steps of 30–60 minutes, each ends with something that can be run and seen. Say the step and the time
  estimate before starting.
- Plan → the user's "yes" → do. When the user asks to answer first, answer and wait before writing code.
- Show the results (numbers, a chart) after every training run.

## Hard rules
- Single-player only. Never touch multiplayer or anything with other players; keep leaderboards off.
- Mod a copy of the game (`game_copy/`), never the installed game. Back it up before patching.
- Decompiled game code and game files never go into git, never get published or shared.
- Downloading any tool needs the user's explicit yes first: name the file, the source URL and the size.
- Don't push to GitHub unless the user says so.

# Overlay design — showing what the agent thinks (plan, built after the agent)

Akel's wish: an overlay at the top left/right of the game. Two modes:
1. **Hint mode** — Akel plays, the agent only thinks and suggests.
2. **Play mode** — the agent plays; Akel picks the speed (1× to watch it, faster to just let it run).
A hotkey toggles an "advanced" panel.

## One pipeline for everything
```
 state source ──► observation ──► agent.think() ──► Thought ──► overlay / report
 (sim | bridge | screen)            (same call as in training)        │
                                                                     └─► play mode: action ──► bridge
```
- **Observation** — one format for all sources (`BuckshotEnv.observation()` in `player/buckshot/sim.py`):
  public counts, HP, items, cuffs, saw, round, and the agent's own knowledge (magnifier/phone). Never the
  hidden order, never the dealer's knowledge.
  - simulator: `env.observation()`;
  - real game, lab copy: an adapter turns the bridge's `public` state into the same dict, and tracks the
    agent's own knowledge from events (what it saw with its magnifier/phone);
  - real game, unmodified (later): a screen reader produces the same dict.
- **Thought** (`player/buckshot/thought.py`) — produced by `agent.think(observation, legal)`:
  `choice`, `values` per action, `exploring`, `agent` (which checkpoint), `notes`. The overlay shows
  exactly what the agent used to decide — nothing is recomputed for show.
- **Actions** — the agent speaks in game actions (`shoot_self`, `shoot_dealer`, later `use:<item>`,
  `steal:<item>`, `double_yes`/`double_no`). The bridge adapter maps them to clicks
  (`shoot_self` → `shotgun`, then `text you`).

## What the overlay shows
- Left: shells — live/blank left (order unknown), what the agent knows about the current shell.
- Right: the recommended move and its **chance of success**.
- Advanced panel (hotkey): every legal move with its value, explore vs. best guess, which checkpoint,
  HP/items as the agent read them (helps spot reading errors).
- **Chance of success** must be a real probability. Plan: give the agent a per-round reward (1 = this
  round won, 0 = died), so a move's Q-value *is* its estimated chance to win the round. To check it, compare
  the shown chances with how often it really wins (calibration table in `player.report`).
- The display layer may add plain facts from public counts (e.g. "3 of 5 are live" = 60%), clearly
  labelled as counts — they are **not** fed back to the agent.

## The two modes
| | hint mode | play mode |
|---|---|---|
| who clicks | Akel | the agent through the bridge |
| game | lab copy now; unmodified game later (screen reader) | lab copy only (needs the bridge) |
| speed | 1× (Akel plays) | chosen: 1×, 2×, 5×, 10× |
| pause before a move | — | optional "think pause" (e.g. 1.5 s at 1×) so the thought stays readable |
| leaderboard | off in the lab copy; on the unmodified game play with Steam offline | off |

## Transport and logs
- Thoughts go out as JSON lines on `127.0.0.1:47801`, so the overlay is a separate process (a transparent,
  click-through, always-on-top window). The game needs borderless-windowed mode for that.
- Every Thought is also appended to the game's report, so a game can be replayed later ("why did it shoot
  itself here?") and checkpoints can be compared move by move.

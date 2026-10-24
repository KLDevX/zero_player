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

## Built: overlay v1 (2026-10-23) — lab copy with the bridge
**Retired 2026-10-24:** replaced by the interface drawn inside the game (docs/ui-plan.md, `player/buckshot/ingame.py`).
```
python -m player.buckshot.overlay --agent runs/d1/dqn_100000.pt                          # hint mode
python -m player.buckshot.overlay --agent runs/d1/dqn_100000.pt --mode play --speed 1 --pause 1.5
```
- `player/buckshot/overlay.py`: tkinter window, transparent and click-through (Win32 extended styles),
  always on top. Top left: live/blank left, the chambered shell as far as the player knows (magnifier,
  phone, inverter), last shell out, HP. Top right: the recommended move and "chance to win the round" (Q
  of the move; shown as a chance only for agents trained with the plain reward), or the last move.
  **F8** — all legal moves with their values and how it read the table; **F10** — quit.
- The bridge switches the copy to borderless fullscreen: the game itself uses *exclusive* fullscreen
  (`OptionsManager.gd:143`), which hides every other window.
- `player/buckshot/live.py` builds the simulator's observation from the bridge. The bridge tracks the
  player's own knowledge from what happens on screen: shells leaving the gun, inversions (only the
  chambered shell changed), its magnifier (hands animation), its phone (the message, matched in the
  current language). `_hidden` is never read in Python.
- Play mode: the agent's move becomes clicks (`shoot_self` → `shotgun`, `text you`), each after the
  clickable set has been stable for 0.6 s of game time; menu, pills, doors, waiver and item draw are
  scripted. Every game (both modes) goes to `reports/games.csv`.
- Not yet: the unmodified game (needs a screen reader), the network picture in the F8 panel.

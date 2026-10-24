# In-game AI interface — plan (agreed with Akel 2026-10-24, not started)

Replaces the tkinter overlay: the bridge (a Godot autoload in the lab copy) draws the interface **inside the
game** with the game's own fonts and colours; Python stays the brain (dx1.5 for fast play, x1 for hints)
and sends each thought to the bridge. Lab copy only, leaderboard off, single player.

## Controls
| key | action |
|---|---|
| **F1** | AI on/off. Off at start (you play). When switched on it starts in **step mode** |
| **→** | step mode: the AI makes one move |
| **Space** | auto (moves on its own) ↔ step mode |
| **←** | browse back through the AI's earlier thoughts (the real game can't be rewound) |
| **1–9** | step mode, "what if": pick another move, see the planner's chance for it, confirm to play it |
| **Ctrl+1/2/3/4** | speed ×1 / ×3 / ×10 / ×20 |
| **F8** | hint level: off → advice → full breakdown |
| **I** | full data panel — **left, middle of the screen** |
| **N** | the network drawn with its current numbers — **bottom left**, out of the way |
| **F12** | save the moment: screenshot + thought (later) |
| **Esc → AI** | settings menu: model, speeds, hint level, text size (later) |

## Look
- The game's own fonts (from its pack, e.g. the one on the defibrillator HP display) and colours (live/blank
  from `GlobalVariables.gd`; the colour-blind palette when that setting is on).
- Dark semi-transparent panels like the game's displays, light scan lines, little text on screen; details
  only on I / N / F8. 2–3 style variants as screenshots, Akel picks one.

## Steps (30–60 min each, each ends with something visible)
1. In-game HUD in the bridge: left panel (shells, what you know, shells out, what the dealer used this
   load, HP), right panel (advice / the AI's move + chance), F1 / → / Space / Ctrl+1…4. Python sends
   thoughts to the bridge. 2–3 style variants. Retire the tkinter overlay.
2. Hints: F8 levels, feedback after your move ("you: shoot dealer 71%; best: magnifier 84%; −13%"),
   "what if" on 1–9.
3. I (full data, left middle), N (network, bottom left: layers, strongest weights, lit neurons),
   ← (thought history).
4. Confidence bar over the game, session summary on the death screen (you vs AI, where you left the
   advice), F12 moments, every game saved with who played.
5. Settings menu (Esc → AI), `settings.json`, start-up safety check (lab copy, leaderboard off),
   a simulator sandbox with real undo for reviewing games.
Later: the AI's voice (short spoken-style lines, then the conversation "brain" via API).

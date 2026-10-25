# In-game AI interface — plan (agreed with Akel 2026-10-24; step 1, I, N and developer mode built, UX pass 3)

Replaces the tkinter overlay: the bridge (a Godot autoload in the lab copy) draws the interface **inside the
game** with the game's own fonts and colours; Python stays the brain (dx1.5 for fast play, x1 for hints)
and sends each thought to the bridge. Lab copy only, leaderboard off, single player.

## Controls
| key | action |
|---|---|
| **F1** | AI on/off. Off at start (you play). When switched on it starts in **step mode** |
| **Space** | step mode: the AI makes one move (UX pass 3: the arrows are the game's, they pick items) |
| **Ctrl+Space** | auto (moves on its own) ↔ step mode |
| **←** | browse back through the AI's earlier thoughts — needs another key now (the arrows are the game's) |
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

## Built: step 1 (2026-10-24)
- `player/buckshot/bridge/hud.gd` draws both panels inside the game (a CanvasLayer above it, drawn with
  `_draw()` in the game's 960×540 frame, so it is pixelated like the game). Fonts from the pack with
  Cyrillic: Fake Receipt Cyr («чек»), DOTMATRI Ver2_2 («табло»), RobotoSlab Cyrillic («плита»); F6 cycles
  them until Akel picks one. Shell colours from `GlobalVariables` (colour-blind palette when it is on).
- Left: shells as coloured pips, the chambered shell (also "по счёту" when the unseen ones are one colour —
  interface only, the agent's input is unchanged), known later shells, shells fired, items the dealer used,
  HP, saw/cuffs. Right: AI mode and speed, the advice / the AI's move, chance to win the round, the next
  two moves, status.
- Keys go through `bridge.on_key()`; the HUD layer is kept last under the root, so its keys come before the
  game's and are swallowed (arrows and Space would move the game's controller cursor).
- `player/buckshot/ingame.py` is the brain (replaces the tkinter overlay); `launch.py` starts it.
  Bridge commands added: `thought`, `take_step`, `screenshot`, `key`; the state reply carries `ui`.
  Several Python connections at once (brain + test tools).
- Exclusive fullscreen sometimes opens shifted right/down: the bridge leaves it and enters it again, once
  per game start (Akel's fix). `--mute` / `BRIDGE_MUTE=1` for tests nobody watches.
- Tested on the game (muted): menus walked with F1 on, → made one move (phone → «№2 холостой»), Space at
  ×10 played to the end, game saved as `dx1.5@991956` (3 rounds survived, 52 AI moves). Hint mode with F1
  off shows advice. Screenshots: `reports/ui/` (git-ignored).

## Built: UX pass 2 (2026-10-24, Akel's notes)
- One style: «чек» (Fake Receipt Cyr); the other two and F6 removed. All text is drawn in capitals (the font
  is capitals-only and draws some small letters oddly).
- Fixed panel sizes and fixed rows, text cut with «…»: nothing jumps when the text changes.
- Shells in two lines: «в ружье» (which shells exist) and «порядок» (each shell in turn: grey unknown,
  coloured seen, outline counted, yellow line under the chamber). Cuffs: «на дилере» green / «на тебе» red /
  «нет» grey; saw «да ×2» / «нет».
- Right panel: «ходы почти равны» when the best two moves differ by under 1% (dx's own noise; see the
  medicine moments below), «последний ход» while waiting.
- I (middle left): every legal move with its chance, both sides' items, round / load / DoN cycles, model.
- N (bottom left): 73 → 64 → 64 → 21, dot brightness = how strongly a neuron fires, the 24 strongest
  connections per layer (green adds, red subtracts; into the chosen move only for the last layer).
- Developer mode on Ё/~ (physical key, any layout): console (help, model, models, speed, ai, auto, i, n,
  cheat, mute, unmute, clear, ↑/↓ history), F2/F3 panel boxes, F4 cheats, PgUp/PgDn model. While it is
  open every key and click goes to it, not to the game.
- Cheats show the real order on the «порядок» line (pale shells with a purple mark), on screen only; the
  Python side never receives it, and the game is saved as «… (cheats)».
- Akel's moments (Steam screenshots 17:53–17:57): dx chose medicine over a safe win because its values only
  mean "chance to win this round" — HP doesn't carry over, so with a certain win medicine, cigarettes and the
  shot were all ≈100% (1.007 vs 0.997, inside its noise). An AI fix (prefer the safe/fast move on ties) is
  for later; the interface now says when moves are tied.

## Built: UX pass 3 (2026-10-24, Akel's notes)
- Keys in square brackets everywhere: [F1], [Space] one move, [Ctrl+Space] auto, [Ctrl+1–4], [I], [N],
  [F11] fullscreen ↔ windowed (press twice to fix the shifted picture; no automatic fix), [~] console (the
  "~" is drawn with the fallback font, the receipt font has a dash there). The arrows go to the game.
- [F1] scheme: off = a clean game with only the shell panel; on = the AI's card slides in (0.15 s, real
  time) and starts step by step; while the dealer plays it keeps the last move faded. [I]/[N] only with
  the AI on. F8 is no longer needed: step mode is the advice mode (you can play the move yourself).
- 2D shells like the game's: flat-topped coloured hull, light edge, dark rim, brass base; one size and step
  in all three rows; darker = known by counting; grey = unknown; yellow line = chamber.
- Card: smaller type (10/12/9), the AI's move and chance, its bar yellow and the next two grey, each with
  an error bar = the spread of the neighbouring networks on this table (`explain.siblings`: dx1.N-1,
  dx1.N-2 or the other seeds). Adrenaline shows what it would take: «адреналин (лупа)»
  (`explain.steal_target`, the agent asked about the steal phase in advance).
- [I] "why": integrated gradients from the average table (`player/buckshot/explain.py`; the average of
  the agent's own simulated decisions), reasons grouped (ЖИЗНИ, ПАТРОНЫ, ЗНАНИЕ, ТВОИ, У ДИЛЕРА, СТОЛ,
  ИСТОРИЯ) with small diverging bars and the coefficient in chance points; the line
  «обычный стол + причины + прочее = итог» adds up. Item table on the right, small: item · you · dealer.
- Developer commands (only at the table; table-changing ones only on your move): `hp`, `hp dealer`,
  `kill dealer` (closes the table and runs the game's own dealer-death ending), `shells` (also resets what
  the player and the dealer know), `remove <item> [dealer]` (frees the grid cell like a used item),
  `cheat order`. Games are saved as «(dev)» / «(cheats)»; dev commands are not counted as your moves.
  `give` is not built (adding a 3D item to the table needs more work).
- Tested on the game, muted: all of the above; `kill dealer` went on to round 2 without freezing.

## Built: money line and ach10 (2026-10-25)
- Shell panel header: «приз» (first cycle: «≈» = 70 000 − timer/600 s × 40 000, live) and «раунд a/b» =
  rounds won / rounds needed for a prize over 1 000 000. The timer counts game time from the waiver to the end
  of round 3, so ×20 doesn't help; the bot's own waits and the AI's item use cost prize. Threshold: a first
  prize ≥ 31 250 needs 18 rounds instead of 21.
- `achievement on|off`: the bridge unlocks only "ach10" (DeathManager.gd:143 rule) through Steam when the run
  goes to the death scene with a prize over 1 000 000, and only if [F1] was on all run, no dev commands, no
  cheats (Akel: the achievement should be his own AI's). Leaderboard stays off (using_steam = false).
  Tested: status, the clean/not-clean check; the unlock itself waits for a real AI run.
- Game seed (answered, not built): the game uses Godot's global RNG only (no randomize()/RNG objects), so the
  bridge could seed each load; cosmetic randomness every frame makes later situations differ. Identical
  situations: the simulator's seeds.

## Built: faster AI in game time, restarts (2026-10-25)
- Measured: at ×20 the bot's choices cost 189 game-seconds of the first cycle — every real millisecond of its
  reaction is 20 game ms. Now the game runs at ×1 while the cursor is shown (a move is being chosen) and at
  ×N only during animations (`realtime on|off`); the settle wait is counted in game time at the current scale.
  In achievement mode the bot shows no thinking pause. First cycle: 728 → 424 game-seconds, first prize
  21 078 → 41 711 (one clean AI run). Faster doesn't help ach10 any more: 31 250…62 500 all need 18 rounds.
- Achievement mode restarts a run as soon as the live first-prize estimate falls under 31 250 (the game's own
  reset, the same as holding R; not a dev command). Such games are saved with end «restart».

## Built: busy signal, refused clicks, game records (2026-10-25)
- ×1 only while the first prize's timer runs (Akel: after the first cycle the prize is set).
- The bridge's state reply has `busy`: what keeps the game busy ("" = free) — the camera turning
  (CameraManager never clears `moving`, so `elapsed < dur` is checked) or a one-shot AnimationPlayer animation
  (looping ones and the mood animators — light flicker, post-process fades — don't count). The bot clicks once
  the game has been free 0.1 game-s, instead of the fixed 0.6 s. Raising the shotgun plays 5 s although the
  target can be chosen much earlier: it counts as free after 0.6 game-s (target chosen in 1.1 s instead of 5 s).
- Refused clicks (the game said no, or the key never became clickable) are logged to reports/live_thoughts/
  as «click refused» with the clickable set and the busy reason. Test runs: 0 refusals.
- games.csv: a game ends only when the table scene ends (by scene id: at ×20 the death screen can pass between
  two looks); a moment with no load between rounds no longer cuts a run into pieces. The prize is recorded;
  a window closed with Alt+F4 still saves the game as «closed».

## Built: clicks when the game allows them (2026-10-25, Akel's choice «В+А»)
- How the game decides a click is allowed — for every clickable thing (shotgun, targets, items, briefcase,
  doors, pills, waiver, double or nothing): the thing's `interactionAllowed`, its collider on, the cursor out,
  and per-action guards like `fs_dec` against a double shot. The bridge's clickable list already checks the
  first three. `GrabShotgun()` switches the targets on at once while the 5 s raise animation plays: the game
  lets a human pick the target right away.
- So the bot no longer waits for animations (`busy` stays in the state reply, for the refused-click log only)
  and needs no camera wait either: it clicks things directly, not with the mouse. It clicks once the game has
  allowed the click for 0.05 game-s (a couple of frames). The shotgun exception is gone.
- Tested, one cycle each (Akel: one cycle is enough): 13 and 8 shots, target chosen 0.07 s after the shotgun
  (was 1.1 s, before that 5 s), no hang, 0 refused clicks. First prize with `achievement on`: 51 278
  (21 078 at the start of the day, 41–43 k with the busy wait). The step-0 freeze was not this.

## ach10 by the AI (2026-10-25)
- dx1.5, clean run (F1 on all the way, no dev commands, no cheats), ×20 with choices at ×1 in the first
  cycle: first prize 37 345, 24 rounds won, died with a prize of 4 779 776 at 03:36. The bridge gave ach10;
  Steam confirms it («в Steam: уже получено», reports/ui/ach10_game.png). Hunt: 21 runs since 02:34.
- Video of the whole run: reports/ui/recordings/record_24r_2026-10-25T02-57-24.mp4 (38:51, 834 MB, sound).
- Known problem: at the end of a long recorded run the bridge saves the sound (448 MB WAV) and the frame list
  in one frame, the game stalls over 5 s and Python's 5 s socket timeout drops the brain and the watcher.
  To fix: save in steps / stream the sound, or a longer timeout. The laptop also slept twice: the game now
  keeps the screen on; ffmpeg runs need the session awake too.

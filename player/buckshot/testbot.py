"""Test bot for the feasibility check: plays Double or Nothing on the real game with random legal moves.

Not a learning agent. It only checks that actions work and measures how long one game takes at a given
speed. Navigation (menu, pills, doors, signing the waiver) is scripted; table moves are random.

    python -m player.buckshot.testbot --games 3 --speed 10

Every game is appended to reports/games.csv.
"""
import argparse
import csv
import random
import time
from datetime import datetime
from pathlib import Path

from player.buckshot.bridge.client import Bridge

REPORTS = Path(__file__).resolve().parents[2] / "reports"
GAMES_CSV = REPORTS / "games.csv"
FIELDS = ["finished_at", "bot", "speed", "seconds", "actions", "rounds_beat", "rounds_survived",
          "don_cycles_beat", "don_prize", "end"]
NAME = "b"  # one lowercase letter: the waiver only needs a non-empty name
STUCK_SECONDS = 90
# Act only when the legal moves have not changed for this long (game time), like a human reaction.
# Clicking mid-animation (e.g. shooting 50 ms after grabbing the shotgun) froze the game.
SETTLE_GAME_SECONDS = 0.6


def choose(legal: list[str], public: dict | None, typed: list[str]) -> str:
    """Scripted navigation first, otherwise a random table move."""
    endless = bool(public and public.get("endless"))
    if "pill bottle" in legal and not endless:
        return "pill bottle"  # the pills switch the run to Double or Nothing
    for key in ("menu start", "pill choice yes", "bathroom door", "backroom door", "release form on table",
                "double yes"):
        if key in legal:
            return key
    signs = [k for k in legal if k.startswith("sign:")]
    if signs:
        if len(typed) < len(NAME) and f"sign:{NAME[len(typed)]}" in legal:
            typed.append(NAME[len(typed)])
            return f"sign:{NAME[len(typed) - 1]}"
        return "sign:enter"
    table = [k for k in legal if k not in ("double no", "pill choice no", "pill bottle")]
    return random.choice(table) if table else ""


def save_game(row: dict) -> None:
    REPORTS.mkdir(exist_ok=True)
    new = not GAMES_CSV.exists()
    with GAMES_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--mute", action="store_true")
    args = ap.parse_args()

    bridge = Bridge()
    bridge.speed(args.speed)
    if args.mute:
        bridge.mute(True)
    print(f"connected, speed x{args.speed:g}")

    games = 0
    in_game = False
    started = 0.0
    actions = 0
    last_public: dict = {}
    typed: list[str] = []
    prev_legal: list[str] | None = None
    legal_since = time.time()
    last_progress = time.time()
    while games < args.games:
        st = bridge.state()
        public = st.get("public")
        endless = bool(public and public.get("endless"))
        if endless and not in_game:
            in_game, started, actions, typed = True, time.time(), 0, []
            print("game started")
        if in_game and not endless:
            # Left the table: in Double or Nothing that means death (scene "death" -> new "main").
            in_game = False
            games += 1
            seconds = time.time() - started
            rounds = int(last_public.get("rounds_beat", 0))
            row = {
                "finished_at": datetime.now().isoformat(timespec="seconds"), "bot": "random",
                "speed": args.speed, "seconds": round(seconds, 1), "actions": actions,
                "rounds_beat": rounds, "rounds_survived": max(0, rounds - 1),
                "don_cycles_beat": last_public.get("don_cycles_beat", 0),
                "don_prize": last_public.get("don_prize", 0), "end": "death",
            }
            save_game(row)
            print(f"game {games}: {seconds:.1f} s, {actions} actions, rounds survived {row['rounds_survived']}")
        if endless:
            last_public = public
        legal = st.get("legal", [])
        if legal != prev_legal:
            prev_legal, legal_since = legal, time.time()
        settle = SETTLE_GAME_SECONDS if not any(k.startswith("sign:") for k in legal) else 0.1
        settled = time.time() - legal_since >= settle / args.speed
        key = choose(legal, public, typed) if legal and settled else ""
        if key:
            reply = bridge.act(key)
            prev_legal = None
            if reply.get("ok"):
                actions += in_game
                last_progress = time.time()
                print(f"  {key}")
            time.sleep(0.05)
        else:
            time.sleep(0.02)
        if time.time() - last_progress > STUCK_SECONDS:
            print(f"stuck for {STUCK_SECONDS} s: scene={st.get('scene')} legal={legal} public={public}")
            last_progress = time.time()
    bridge.speed(1.0)
    bridge.close()


if __name__ == "__main__":
    main()

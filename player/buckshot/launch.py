"""One command: start the lab copy of the game with the bridge, wait for it, start the AI's brain.

    python -m player.buckshot.launch                                   # best model (dx1.5), AI off: you play
    python -m player.buckshot.launch --agent runs/d3.1/dqn_100000.pt --speed 10

Uses game_lab/game (a copy of the game; the Steam folder is never touched). Puts override.cfg there if it
is missing, starts the game if it isn't running, waits until the bridge answers, then runs
player.buckshot.ingame. The interface is drawn inside the game: F1 AI on/off, → one move, Space auto,
Ctrl+1…4 speed, F6 style. Ctrl+C here stops the brain; the game keeps running.
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from player.buckshot.bridge.client import PORT
from player.buckshot.ingame import DEFAULT_AGENT

ROOT = Path(__file__).resolve().parents[2]
GAME_DIR = ROOT / "game_lab" / "game"
EXE = GAME_DIR / "Buckshot Roulette.exe"
OVERRIDE = ROOT / "player" / "buckshot" / "bridge" / "override.cfg"


def bridge_up() -> bool:
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
        return True
    except OSError:
        return False


def game_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Buckshot Roulette.exe"], capture_output=True, text=True)
    return "Buckshot Roulette.exe" in out.stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", type=Path, default=DEFAULT_AGENT)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--mute", action="store_true", help="no game sound (tests without a person watching)")
    ap.add_argument("--pause", type=float, default=1.5)
    args = ap.parse_args()

    if not EXE.exists():
        sys.exit(f"no lab copy at {GAME_DIR}: copy the game folder there first (docs/how-to-run.md)")
    if not args.agent.exists():
        sys.exit(f"no checkpoint {args.agent}")
    if not (GAME_DIR / "override.cfg").exists():
        shutil.copy(OVERRIDE, GAME_DIR / "override.cfg")
        print("override.cfg copied into the lab copy")
    if not game_running():
        print("starting the lab copy of the game…")
        env = {**os.environ, "BRIDGE_MUTE": "1"} if args.mute else None
        subprocess.Popen([str(EXE)], cwd=GAME_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    for _ in range(120):
        if bridge_up():
            break
        time.sleep(0.5)
    else:
        sys.exit("the bridge didn't answer in 60 s: is the game open? is override.cfg in game_lab/game?")
    print(f"bridge is up; brain: {args.agent}, speed x{args.speed:g}")
    cmd = [sys.executable, "-m", "player.buckshot.ingame", "--agent", str(args.agent),
           "--speed", str(args.speed), "--pause", str(args.pause)] + (["--mute"] if args.mute else [])
    subprocess.run(cmd, cwd=ROOT)


if __name__ == "__main__":
    main()

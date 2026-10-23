"""One command: start the lab copy of the game with the bridge, wait for it, open the overlay.

    python -m player.buckshot.launch --agent runs/d3.1/dqn_100000.pt --mode play --speed 10
    python -m player.buckshot.launch --agent runs/d3.1/dqn_100000.pt              # hint mode: you play

Uses game_lab/game (a copy of the game; the Steam folder is never touched). Puts override.cfg there if it
is missing, starts the game if it isn't running, waits until the bridge answers, then runs the overlay
(same options as player.buckshot.overlay). F10 closes the overlay; the game keeps running.
"""
import argparse
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from player.buckshot.bridge.client import PORT

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
    ap.add_argument("--agent", type=Path, required=True)
    ap.add_argument("--mode", choices=("hint", "play"), default="hint")
    ap.add_argument("--speed", type=float, default=1.0)
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
        subprocess.Popen([str(EXE)], cwd=GAME_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        if bridge_up():
            break
        time.sleep(0.5)
    else:
        sys.exit("the bridge didn't answer in 60 s: is the game open? is override.cfg in game_lab/game?")
    print(f"bridge is up; overlay: {args.mode} mode, agent {args.agent}, speed x{args.speed:g} (F8 details, F10 quit)")
    cmd = [sys.executable, "-m", "player.buckshot.overlay", "--agent", str(args.agent), "--mode", args.mode,
           "--speed", str(args.speed), "--pause", str(args.pause)]
    subprocess.run(cmd, cwd=ROOT)


if __name__ == "__main__":
    main()

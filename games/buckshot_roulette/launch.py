"""One command: start the lab copy of the game with the bridge, wait for it, start the AI's brain.

    python -m games.buckshot_roulette.launch                                   # best model (dx1.5), AI off: you play
    python -m games.buckshot_roulette.launch --agent runs/d3.1/dqn_100000.pt --speed 10

Uses games/buckshot_roulette/game_copy (a copy of the game; the Steam folder is never touched). Writes override.cfg there if it
is missing, starts the game if it isn't running, waits until the bridge answers, then runs
games.buckshot_roulette.ingame. The interface is drawn inside the game: F1 AI on/off, → one move, Space auto,
Ctrl+1…4 speed, F6 style. Ctrl+C here stops the brain; the game keeps running.
"""
import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from core.protocol import PORT
from games.buckshot_roulette.ingame import DEFAULT_AGENT

ROOT = Path(__file__).resolve().parents[2]
GAME = Path(__file__).resolve().parent  # games/buckshot_roulette: its models, reports, docs, game copy
GAME_DIR = GAME / "game_copy"
EXE = GAME_DIR / "Buckshot Roulette.exe"
OVERRIDE = GAME / "bridge" / "override.cfg"


def write_override() -> None:
    """override.cfg with the absolute path of bridge.gd on this computer (Godot needs an absolute path)."""
    bridge = (GAME / "bridge" / "bridge.gd").resolve().as_posix()
    text = OVERRIDE.read_text(encoding="utf-8").replace("@BRIDGE_PATH@", bridge)
    target = GAME_DIR / "override.cfg"
    if not target.exists() or target.read_text(encoding="utf-8") != text:
        target.write_text(text, encoding="utf-8")
        print(f"override.cfg written into the lab copy (bridge: {bridge})")


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
    write_override()
    if not game_running():
        print("starting the lab copy of the game…")
        env = {**os.environ, "BRIDGE_MUTE": "1"} if args.mute else None
        subprocess.Popen([str(EXE)], cwd=GAME_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    for _ in range(120):
        if bridge_up():
            break
        time.sleep(0.5)
    else:
        sys.exit("the bridge didn't answer in 60 s: is the game open? is override.cfg in games/buckshot_roulette/game_copy?")
    print(f"bridge is up; brain: {args.agent}, speed x{args.speed:g}")
    cmd = [sys.executable, "-m", "games.buckshot_roulette.ingame", "--agent", str(args.agent),
           "--speed", str(args.speed), "--pause", str(args.pause)] + (["--mute"] if args.mute else [])
    subprocess.run(cmd, cwd=ROOT)


if __name__ == "__main__":
    main()

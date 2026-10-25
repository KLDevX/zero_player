"""zero_player: one AI player, one module per game. This file starts the right game with the right model.

    python zero_player.py                          # the games and their models
    python zero_player.py buckshot_roulette        # play with the game's default model
    python zero_player.py buckshot_roulette --model d3.1.3-s2 --speed 10 --mute

Each game lives in games/<name>/ with a game.toml: how to launch it, where its models are, which one is the
default. Everything about a game (its copy, mod, simulator, agents, models, reports, docs) stays in its
folder; core/ holds what every game shares (the agent's Thought, the brain ↔ game protocol).
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GAMES = ROOT / "games"


def games() -> dict[str, dict]:
    out = {}
    for toml in sorted(GAMES.glob("*/game.toml")):
        info = tomllib.loads(toml.read_text(encoding="utf-8"))
        info["dir"] = toml.parent
        out[info["name"]] = info
    return out


def models(info: dict) -> dict[str, Path]:
    """name -> its last checkpoint."""
    out = {}
    for run in sorted(p for p in (info["dir"] / info["models"]).glob("*") if p.is_dir() and p.name != "archive"):
        ckpts = sorted(run.glob("dqn_*.pt"), key=lambda c: int(c.stem.split("_")[1]))
        if ckpts:
            out[run.name] = ckpts[-1]
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    all_games = games()
    if len(sys.argv) < 2 or sys.argv[1] not in all_games:
        print("games:")
        for name, info in all_games.items():
            ready = "" if (info["dir"] / info["game_copy"]).exists() else "  (no game copy yet: see " \
                + str((info["dir"] / info["docs"]).relative_to(ROOT)) + ")"
            v = info.get("version", {})
            print(f"  {name:<18} {info['title']}, game {v.get('game', '?')}{ready}")
            print(f"  {'':<18} models: {', '.join(models(info)) or '—'} (default {info['default_model']})")
        print("\npython zero_player.py <game> [--model <name>] [other options of the game's launcher]")
        return
    info = all_games[sys.argv[1]]
    rest = sys.argv[2:]
    name = info["default_model"]
    if "--model" in rest:
        k = rest.index("--model")
        name = rest[k + 1]
        rest = rest[:k] + rest[k + 2:]
    known = models(info)
    if name not in known:
        sys.exit(f"no model {name!r} for {info['name']}; models: {', '.join(known)}")
    cmd = [sys.executable, "-m", info["launch"], "--agent", str(known[name])] + rest
    print(f"{info['title']}: model {name} ({known[name].relative_to(ROOT)})")
    sys.exit(subprocess.run(cmd, cwd=ROOT).returncode)


if __name__ == "__main__":
    main()

"""Summary of all runs: python -m player.report [--eval-games 10000]

1. Training runs (reports/train_<run>.csv): games, training time, rounds survived, best game, round win
   rate, progress over training.
2. Checkpoints (runs/<run>/q_*.pkl) side by side with a random player: same simulator seed, exploration
   off, same number of games.
3. Games on the real game through the bridge (reports/games.csv).

"Round win rate" = rounds won / rounds played; each game is a run of rounds that ends with one death.
"""
import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

from player.buckshot.qtable import QTableAgent
from player.buckshot.sim import DOUBLE_YES, BuckshotEnv
from player.buckshot.train import play_game

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
RUNS = ROOT / "runs"
EVAL_SEED = 12345


def table(headers: list[str], rows: list[list]) -> str:
    cells = [[str(h) for h in headers]] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    lines = ["  ".join(c.rjust(w) for c, w in zip(r, widths)) for r in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def summarize(rounds: list[int]) -> tuple[float, int, float]:
    won = sum(rounds)
    return won / len(rounds), max(rounds), won / (won + len(rounds))


def training_runs() -> None:
    rows, progress = [], []
    for path in sorted(REPORTS.glob("train_*.csv")):
        run = path.stem.removeprefix("train_")
        with path.open(encoding="utf-8") as f:
            rounds = [int(r["rounds_survived"]) for r in csv.DictReader(f)]
        if not rounds:
            continue
        meta_path = RUNS / run / "meta.json"
        seconds = json.loads(meta_path.read_text(encoding="utf-8"))["training_seconds"] if meta_path.exists() else "?"
        mean, best, win = summarize(rounds)
        tenth = max(1, len(rounds) // 10)
        last_mean = sum(rounds[-tenth:]) / tenth
        rows.append([run, len(rounds), f"{seconds} s", f"{mean:.2f}", f"{last_mean:.2f}", best, f"{win:.1%}"])
        blocks = [rounds[i:i + tenth] for i in range(0, len(rounds), tenth)][:10]
        progress.append(f"{run}: " + "  ".join(f"{sum(b) / len(b):.2f}" for b in blocks))
    if not rows:
        print("no training runs yet (python -m player.buckshot.train)")
        return
    print("TRAINING RUNS (simulator, exploration on)")
    print(table(["run", "games", "time", "rounds/game", "last 10%", "best game", "round win rate"], rows))
    print("\nprogress - mean rounds survived per tenth of training:")
    print("\n".join(progress))


class _Random:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def think(self, obs, legal):
        class T:  # minimal Thought stand-in
            choice = DOUBLE_YES if DOUBLE_YES in legal else self.rng.choice(legal)
        return T()


def checkpoints(eval_games: int) -> None:
    contenders: list[tuple[str, bool, object]] = [("random", False, _Random(EVAL_SEED)),
                                                  ("random", True, _Random(EVAL_SEED))]
    for run_dir in sorted(p for p in RUNS.glob("*") if p.is_dir()):
        meta_path = run_dir / "meta.json"
        items = json.loads(meta_path.read_text(encoding="utf-8")).get("items", False) if meta_path.exists() else False
        for path in sorted(run_dir.glob("q_*.pkl"), key=lambda p: int(p.stem.split("_")[1])):
            contenders.append((f"{run_dir.name}@{path.stem.split('_')[1]}", items,
                               QTableAgent.load(path, seed=EVAL_SEED)))
    if len(contenders) == 2:
        return
    rows = []
    for name, items, agent in contenders:
        env = BuckshotEnv(seed=EVAL_SEED, items=items)
        rounds = [play_game(env, agent, learn=False) for _ in range(eval_games)]
        mean, best, win = summarize(rounds)
        rows.append([name, "yes" if items else "no", f"{mean:.3f}", best, f"{win:.1%}"])
    print(f"\nCHECKPOINTS vs the dealer (simulator, {eval_games} games each, exploration off, seed {EVAL_SEED})")
    print(table(["agent", "items", "rounds/game", "best game", "round win rate"], rows))


def real_games() -> None:
    path = REPORTS / "games.csv"
    if not path.exists():
        return
    groups = defaultdict(list)
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            groups[(r["bot"], r["speed"])].append(r)
    rows = []
    for (bot, speed), rs in sorted(groups.items()):
        rounds = [int(r["rounds_survived"]) for r in rs]
        secs = [float(r["seconds"]) for r in rs]
        rows.append([bot, f"x{float(speed):g}", len(rs), f"{sum(rounds) / len(rounds):.2f}", max(rounds),
                     f"{sum(secs) / len(secs):.1f} s"])
    print("\nREAL GAME through the bridge (reports/games.csv)")
    print(table(["bot", "speed", "games", "rounds/game", "best game", "time/game"], rows))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-games", type=int, default=10_000)
    args = ap.parse_args()
    training_runs()
    checkpoints(args.eval_games)
    real_games()


if __name__ == "__main__":
    main()

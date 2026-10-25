"""Train the same version with several seeds at once (one process per seed, one CPU core each).

    python -m games.buckshot.multiseed --run d4.1.3 --seeds 0 1 2 -- --games 100000 --items --agent dqn \\
        --shaping v4 --obs 2 --gamma 0.99 --n-step 3 --tables 32

Each seed trains as runs/<run>-s<seed> with its own log (reports/train_<run>-s<seed>.log). The seeds tell
how much of a result is luck; compare them with
    python -m games.buckshot.replay runs/<run>-s<seed>/dqn_<games>.pt   (for every seed)
    python -m games.buckshot.viz compare <run>-s0 <run>-s1 <run>-s2
"""
import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAME = Path(__file__).resolve().parent  # games/buckshot: its models, reports, docs, game copy


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("train_args", nargs=argparse.REMAINDER, help="after --: arguments for games.buckshot.train")
    args = ap.parse_args()
    extra = [a for a in args.train_args if a != "--"]

    procs = {}
    for seed in args.seeds:
        run = f"{args.run}-s{seed}"
        log = (GAME / "reports" / f"train_{run}.log").open("w", encoding="utf-8")
        cmd = [sys.executable, "-u", "-m", "games.buckshot.train", "--run", run, "--seed", str(seed), *extra]
        procs[run] = (subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT), log)
        print(f"started {run}: log reports/train_{run}.log", flush=True)
    t0 = time.time()
    while any(p.poll() is None for p, _ in procs.values()):
        time.sleep(5)
    for run, (p, log) in procs.items():
        log.close()
        path = GAME / "reports" / f"train_{run}.csv"
        rounds = [int(r["rounds_survived"]) for r in csv.DictReader(path.open(encoding="utf-8"))] if path.exists() else []
        tenth = max(1, len(rounds) // 10)
        last = sum(rounds[-tenth:]) / tenth if rounds else float("nan")
        print(f"{run}: exit {p.returncode}, {len(rounds)} games, last 10% mean rounds {last:.2f}")
    print(f"all seeds done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

"""dx — a fast network that learns from the x1 planner (supervised "distillation") + DAgger rounds.

Like learning to read digits: the network sees a table (the same 73 numbers a d-agent sees), guesses the
chance to win the round for every legal move, and is corrected by the planner's answer (x1's chances).

    python -m player.buckshot.distill loop          # the whole night plan: lessons, dx1.0, DAgger dx1.1 …
    python -m player.buckshot.distill label --out reports/distill/x1 --games 3000            # lessons only
    python -m player.buckshot.distill train --data reports/distill/x1 --run dx1.0            # one network

DAgger: dx plays by itself, x1 answers on the tables dx reached (including its own mistakes), the answers
join the lessons, dx is trained again. Versions: dx1.0 (from x1's own games), dx1.1, dx1.2, … one per round.
x1 knows only the rules of the world (no tactics), so dx still finds the strategy without our hints.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
from torch import nn

from player.buckshot.dqn import ACTION_INDEX, ACTIONS, DQNAgent, encode_v2
from player.buckshot.sim import BuckshotEnv

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "reports" / "distill"
BASE = ROOT / "runs" / "d3.1.3-s2" / "dqn_100000.pt"
WORKERS = 12
EVAL_GAMES, EVAL_SEED = 5000, 7


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# --- lessons --------------------------------------------------------------------------------

def _label_worker(task: tuple) -> str:
    """One process: play `games`, ask x1 for the chances of every legal move, save them."""
    k, games, seed, base, samples, player, out = task
    from player.buckshot.planner import PlannerAgent
    teacher = PlannerAgent(Path(base), samples=samples, seed=seed)
    actor = DQNAgent.load(Path(player), seed=seed) if player else None
    if actor:
        actor.epsilon = 0.05  # a little variety in the tables it reaches
    env = BuckshotEnv(seed=seed)
    xs, masks, ys = [], [], []
    for _ in range(games):
        obs = env.reset()
        while not env.done:
            legal = env.legal_actions()
            t = teacher.think(obs, legal)
            if t.values:  # real decisions only (not the double-or-nothing yes, not a single legal move)
                y = np.full(len(ACTIONS), np.nan, dtype=np.float32)
                for a, v in t.values.items():
                    y[ACTION_INDEX[a]] = v
                xs.append(encode_v2(obs))
                masks.append(~np.isnan(y))
                ys.append(np.nan_to_num(y))
            move = actor.think(obs, legal).choice if actor else t.choice
            obs, *_ = env.step(move)
    path = Path(out) / f"part_{k:02d}.npz"
    np.savez_compressed(path, x=np.stack(xs), mask=np.stack(masks), y=np.stack(ys))
    return str(path)


def label(out: Path, games: int, seed: int, base: Path = BASE, samples: int = 16, player: Path | None = None,
          workers: int = WORKERS) -> int:
    out.mkdir(parents=True, exist_ok=True)
    per = [games // workers + (1 if k < games % workers else 0) for k in range(workers)]
    tasks = [(k, n, seed * 1000 + k, str(base), samples, str(player) if player else None, str(out))
             for k, n in enumerate(per) if n]
    t0 = time.time()
    with mp.Pool(len(tasks)) as pool:
        for i, path in enumerate(pool.imap_unordered(_label_worker, tasks), 1):
            log(f"lessons: worker done {i}/{len(tasks)} ({time.time() - t0:.0f} s) -> {Path(path).name}")
    n = sum(np.load(p)["x"].shape[0] for p in out.glob("part_*.npz"))
    log(f"lessons in {out.relative_to(ROOT)}: {n} tables, {time.time() - t0:.0f} s")
    return n


def load_lessons(dirs: list[Path]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xs, ms, ys = [], [], []
    for d in dirs:
        for p in sorted(d.glob("part_*.npz")):
            z = np.load(p)
            xs.append(z["x"]), ms.append(z["mask"]), ys.append(z["y"])
    return np.concatenate(xs), np.concatenate(ms), np.concatenate(ys)


# --- the network ----------------------------------------------------------------------------

def train(dirs: list[Path], run: str, init: Path | None = None, epochs: int = 40, seed: int = 0) -> Path:
    """Fit the network to x1's chances (mean squared error on the legal moves only)."""
    x, m, y = load_lessons(dirs)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(x))
    n_val = max(1000, len(x) // 20)
    val, tr = idx[:n_val], idx[n_val:]
    agent = DQNAgent.load(init, seed=seed) if init else DQNAgent(seed=seed, obs_version=2)
    agent.name = run
    net = agent.net
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    X, M, Y = torch.from_numpy(x), torch.from_numpy(m), torch.from_numpy(y)

    def loss_on(ids: np.ndarray) -> torch.Tensor:
        pred = net(X[ids])
        mm = M[ids].float()
        return ((pred - Y[ids]) ** 2 * mm).sum() / mm.sum()

    best, best_state, t0 = float("inf"), None, time.time()
    for ep in range(epochs):
        net.train()
        perm = rng.permutation(tr)
        for i in range(0, len(perm), 512):
            loss = loss_on(perm[i:i + 512])
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        with torch.no_grad():
            v = float(loss_on(val))
        if v < best:
            best, best_state = v, {k: t.clone() for k, t in net.state_dict().items()}
    net.load_state_dict(best_state)
    agent.target.load_state_dict(best_state)
    agent.games_trained = len(x)
    path = ROOT / "runs" / run / f"dqn_{len(x)}.pt"
    agent.save(path, teacher="x1", lessons=len(x), dirs=[str(d.relative_to(ROOT)) for d in dirs],
               val_mse=best, init=str(init) if init else None)
    (path.parent / "meta.json").write_text(json.dumps({
        "run": run, "agent": "dx (distilled from x1)", "items": True, "lessons": len(x), "val_mse": best,
        "teacher": f"x1(16) with base {BASE.parent.name}", "init": str(init) if init else None,
        "training_seconds": round(time.time() - t0, 1)}, indent=2), encoding="utf-8")
    log(f"{run}: trained on {len(x)} tables, validation error {best:.4f} (rmse {best ** 0.5:.3f}), "
        f"{time.time() - t0:.0f} s -> {path.relative_to(ROOT)}")
    return path


def evaluate(ckpt: Path, games: int = EVAL_GAMES) -> dict:
    subprocess.run([sys.executable, "-m", "player.buckshot.replay", str(ckpt), "--games", str(games),
                    "--logs", "5", "--seed", str(EVAL_SEED)], cwd=ROOT, check=True, capture_output=True)
    stats = json.loads((ROOT / "reports" / "replays" / f"{ckpt.parent.name}_{ckpt.stem}" / "stats.json")
                       .read_text(encoding="utf-8"))
    log(f"{ckpt.parent.name}: {stats['rounds_per_game']:.2f} rounds/game, {stats['round_win_rate']:.1%} rounds won, "
        f"best game {stats['best_game']}")
    return stats


# --- the whole plan -------------------------------------------------------------------------

def loop(first_games: int, round_games: int, max_round: int, eval_games: int = EVAL_GAMES,
         final_games: int = 300) -> None:
    summary = []
    lessons = [DATA / "x1"]
    if not list(lessons[0].glob("part_*.npz")):
        log(f"point 1: x1 (base {BASE.parent.name}) plays {first_games} games and writes its chances")
        label(lessons[0], first_games, seed=1)
    ckpt = train(lessons, "dx1.0")
    stats = evaluate(ckpt, eval_games)
    summary.append({"version": "dx1.0", "checkpoint": str(ckpt.relative_to(ROOT)), **_short(stats)})
    best = (stats["rounds_per_game"], ckpt)
    gains = []
    for r in range(1, max_round + 1):
        d = DATA / f"dagger{r}"
        log(f"DAgger round {r}: dx1.{r - 1} plays {round_games} games, x1 answers on its tables")
        label(d, round_games, seed=100 + r, player=ckpt)
        lessons.append(d)
        prev = stats["rounds_per_game"]
        ckpt = train(lessons, f"dx1.{r}", init=ckpt, seed=r)
        stats = evaluate(ckpt, eval_games)
        summary.append({"version": f"dx1.{r}", "checkpoint": str(ckpt.relative_to(ROOT)), **_short(stats)})
        gains.append(stats["rounds_per_game"] - prev)
        if stats["rounds_per_game"] > best[0]:
            best = (stats["rounds_per_game"], ckpt)
        (DATA / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        if len(gains) >= 2 and gains[-1] < 0.1 and gains[-2] < 0.1:
            log(f"stop: the last two rounds gained {gains[-2]:+.2f} and {gains[-1]:+.2f} rounds (< 0.1 = noise)")
            break
    (DATA / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    log(f"best dx: {best[1].parent.name} with {best[0]:.2f} rounds/game")
    log(f"x1 again, with the best dx as its base player ({final_games} games)")
    subprocess.run([sys.executable, "-u", "-m", "player.buckshot.planner", "--games", str(final_games), "--samples", "16",
                    "--base", str(best[1])], cwd=ROOT, check=True)
    log("all done")


def _short(stats: dict) -> dict:
    return {k: stats[k] for k in ("rounds_per_game", "round_win_rate", "best_game", "decisions_per_round")}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    lp = sub.add_parser("loop")
    lp.add_argument("--first-games", type=int, default=3000)
    lp.add_argument("--round-games", type=int, default=1500)
    lp.add_argument("--max-round", type=int, default=5)
    lp.add_argument("--eval-games", type=int, default=EVAL_GAMES)
    lp.add_argument("--final-games", type=int, default=300)
    lb = sub.add_parser("label")
    lb.add_argument("--out", type=Path, required=True)
    lb.add_argument("--games", type=int, default=3000)
    lb.add_argument("--seed", type=int, default=1)
    lb.add_argument("--player", type=Path, default=None, help="DAgger: this network plays, x1 only answers")
    tr = sub.add_parser("train")
    tr.add_argument("--data", type=Path, nargs="+", required=True)
    tr.add_argument("--run", required=True)
    tr.add_argument("--init", type=Path, default=None)
    args = ap.parse_args()
    if args.cmd == "loop":
        loop(args.first_games, args.round_games, args.max_round, args.eval_games, args.final_games)
    elif args.cmd == "label":
        label(args.out, args.games, args.seed, player=args.player)
    else:
        train(args.data, args.run, init=args.init)


if __name__ == "__main__":
    main()

"""Train the Q-table agent in the simulator.

    python -m player.buckshot.train --games 100000 --run q1

Saves frozen checkpoints to runs/<run>/q_<games>.pkl (after 100, 1 000, 10 000, 100 000 … games and at
the end) while the main agent keeps learning, and logs every game to reports/train_<run>.csv.
"""
import argparse
import csv
import json
import time
from pathlib import Path

from player.buckshot.qtable import QTableAgent
from player.buckshot.sim import BuckshotEnv

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
REPORTS = ROOT / "reports"
CHECKPOINTS = (100, 1_000, 10_000, 100_000, 1_000_000)
EPS_START, EPS_END, EPS_DECAY_SHARE = 1.0, 0.05, 0.5  # epsilon falls linearly over the first half


def epsilon_at(game: int, total: int) -> float:
    progress = min(1.0, game / max(1, total * EPS_DECAY_SHARE))
    return EPS_START + (EPS_END - EPS_START) * progress


def play_game(env: BuckshotEnv, agent: QTableAgent, learn: bool) -> int:
    obs = env.reset()
    while not env.done:
        legal = env.legal_actions()
        action = agent.think(obs, legal).choice
        next_obs, reward, done, _ = env.step(action)
        if learn:
            agent.learn(obs, action, reward, next_obs, env.legal_actions(), round_over=reward > 0 or done)
        obs = next_obs
    return env.s.rounds_beat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100_000)
    ap.add_argument("--run", default="q1")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    run_dir = RUNS / args.run
    run_dir.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    env = BuckshotEnv(seed=args.seed)
    agent = QTableAgent(seed=args.seed, name=args.run)
    log_path = REPORTS / f"train_{args.run}.csv"
    t0 = time.perf_counter()
    window: list[int] = []
    with log_path.open("w", newline="", encoding="utf-8") as f:
        log = csv.writer(f)
        log.writerow(["game", "rounds_survived", "epsilon", "states_known"])
        for game in range(1, args.games + 1):
            agent.epsilon = epsilon_at(game, args.games)
            rounds = play_game(env, agent, learn=True)
            agent.games_trained = game
            log.writerow([game, rounds, round(agent.epsilon, 4), len(agent.q)])
            window.append(rounds)
            if game in CHECKPOINTS or game == args.games:
                path = run_dir / f"q_{game}.pkl"
                agent.save(path, seed=args.seed, total_games=args.games)
                print(f"checkpoint saved: {path.relative_to(ROOT)}")
            if game % max(1, args.games // 10) == 0:
                mean = sum(window) / len(window)
                print(f"game {game:>8}: mean rounds survived {mean:.2f} (last {len(window)}), "
                      f"epsilon {agent.epsilon:.2f}, states {len(agent.q)}")
                window = []
    seconds = time.perf_counter() - t0
    meta = {"run": args.run, "games": args.games, "seed": args.seed, "training_seconds": round(seconds, 1),
            "agent": "qtable", "sim": "v1 (no items)"}
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"done in {seconds:.1f} s; log: {log_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

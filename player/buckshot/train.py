"""Train an agent in the simulator.

    python -m player.buckshot.train --games 100000 --run q1                 # Q-table, no items
    python -m player.buckshot.train --games 100000 --run d1 --items --agent dqn

Saves frozen checkpoints to runs/<run>/ (q_<games>.pkl or dqn_<games>.pt after 100, 1 000, 10 000,
100 000 … games and at the end) while the main agent keeps learning, and logs every game to
reports/train_<run>.csv. DQN runs also write TensorBoard logs to runs/<run>/tb:
    tensorboard --logdir runs
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


def _potential(obs: dict) -> float:
    return (obs["hp_player"] - obs["hp_dealer"]) / obs["max_hp"]


def shaped_reward(shaping: str, obs: dict, next_obs: dict, reward: float, round_over: bool, info: dict) -> float:
    """Reward experiments (docs/progress.md). The goal stays the same: +1 per round won.
    none:         just the goal.
    hp_potential: + 0.1 * change of (my HP - dealer HP) / max HP, potential 0 at the end of a round
                  (potential-based shaping: proven not to change which strategy is best).
    hp_speed:     - 0.1 per HP the player lost, - 0.02 per action (faster wins pay more). Akel's test."""
    if shaping == "none" or obs["phase"] == "double":
        return reward
    if shaping == "hp_potential":
        after = 0.0 if round_over else _potential(next_obs)
        return reward + 0.1 * (after - _potential(obs))
    if shaping == "hp_speed":
        return reward - 0.1 * info["hp_lost"] - 0.02
    raise ValueError(shaping)


def play_game(env: BuckshotEnv, agent, learn: bool, shaping: str = "none") -> int:
    obs = env.reset()
    while not env.done:
        legal = env.legal_actions()
        action = agent.think(obs, legal).choice
        next_obs, reward, done, info = env.step(action)
        if learn:
            round_over = reward > 0 or done
            r = shaped_reward(shaping, obs, next_obs, reward, round_over, info)
            agent.learn(obs, action, r, next_obs, env.legal_actions(), round_over=round_over)
        obs = next_obs
    return env.s.rounds_beat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100_000)
    ap.add_argument("--run", default="q1")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--items", action="store_true", help="simulator with items (v2); default: v1 rules")
    ap.add_argument("--agent", choices=("qtable", "dqn"), default="qtable")
    ap.add_argument("--shaping", choices=("none", "hp_potential", "hp_speed"), default="none",
                    help="reward experiment on top of +1 per round won (see shaped_reward)")
    ap.add_argument("--key", choices=("basic", "full"), default="basic",
                    help="what the Q-table keys on: basic = HP + shells, full = the whole observation")
    args = ap.parse_args()

    run_dir = RUNS / args.run
    run_dir.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    env = BuckshotEnv(seed=args.seed, items=args.items)
    writer = None
    if args.agent == "dqn":
        from torch.utils.tensorboard import SummaryWriter

        from player.buckshot.dqn import DQNAgent
        agent = DQNAgent(seed=args.seed, name=args.run)
        writer = SummaryWriter(log_dir=str(run_dir / "tb"))
        prefix, ext = "dqn", "pt"
    else:
        agent = QTableAgent(seed=args.seed, name=args.run, key=args.key)
        prefix, ext = "q", "pkl"
    log_path = REPORTS / f"train_{args.run}.csv"
    t0 = time.perf_counter()
    window: list[int] = []
    rolling: list[int] = []
    with log_path.open("w", newline="", encoding="utf-8") as f:
        log = csv.writer(f)
        log.writerow(["game", "rounds_survived", "epsilon", "size"])
        for game in range(1, args.games + 1):
            agent.epsilon = epsilon_at(game, args.games)
            rounds = play_game(env, agent, learn=True, shaping=args.shaping)
            agent.games_trained = game
            size = len(agent.q) if args.agent == "qtable" else agent.steps
            log.writerow([game, rounds, round(agent.epsilon, 4), size])
            window.append(rounds)
            rolling = (rolling + [rounds])[-1000:]
            if writer and game % 500 == 0:
                writer.add_scalar("rounds survived (last 1000 games)", sum(rolling) / len(rolling), game)
                writer.add_scalar("epsilon", agent.epsilon, game)
                writer.add_scalar("loss", agent.last_loss, game)
            if writer and game % max(1, args.games // 20) == 0:
                for pname, p in agent.net.named_parameters():
                    writer.add_histogram(f"weights/{pname}", p.detach(), game)
            if game in CHECKPOINTS or game == args.games:
                path = run_dir / f"{prefix}_{game}.{ext}"
                agent.save(path, seed=args.seed, total_games=args.games, items=args.items)
                print(f"checkpoint saved: {path.relative_to(ROOT)}", flush=True)
            if game % max(1, args.games // 10) == 0:
                mean = sum(window) / len(window)
                print(f"game {game:>8}: mean rounds survived {mean:.2f} (last {len(window)}), "
                      f"epsilon {agent.epsilon:.2f}, {'states' if args.agent == 'qtable' else 'steps'} {size}, "
                      f"{time.perf_counter() - t0:.0f} s", flush=True)
                window = []
    seconds = time.perf_counter() - t0
    if writer:
        writer.close()
    meta = {"run": args.run, "games": args.games, "seed": args.seed, "training_seconds": round(seconds, 1),
            "agent": args.agent, "shaping": args.shaping, "items": args.items, "sim": "v2 (items)" if args.items else "v1 (no items)"}
    if args.agent == "qtable":
        meta["key"] = args.key
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"done in {seconds:.1f} s; log: {log_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

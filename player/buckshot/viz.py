"""Pictures of training and of the network (matplotlib, saved to reports/*.png).

    python -m player.buckshot.viz curves                 # learning curves of all runs
    python -m player.buckshot.viz network runs/d1/dqn_100000.pt [--seed 3]
                                                         # the network: inputs → hidden → outputs,
                                                         # strongest weights, neurons lit for one situation
Live training charts: tensorboard --logdir runs   (then open http://localhost:6006)
"""
import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"


def curves() -> Path:
    runs = []
    for path in sorted(REPORTS.glob("train_*.csv")):
        with path.open(encoding="utf-8") as f:
            rounds = np.array([int(r["rounds_survived"]) for r in csv.DictReader(f)], dtype=float)
        if len(rounds):
            name = path.stem.removeprefix("train_")
            meta = ROOT / "runs" / name / "meta.json"
            info = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
            kind = f"{info.get('agent', '?')}, {'items' if info.get('items') else 'no items'}"
            runs.append((f"{name}: {kind}", rounds))
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for name, rounds in runs:
        w = max(50, len(rounds) // 100)
        smooth = np.convolve(rounds, np.ones(w) / w, mode="valid")
        ax.plot(np.arange(w, len(rounds) + 1), smooth, label=f"{name} ({len(rounds):,} games)", linewidth=1.8)
    ax.set_xscale("log")
    ax.set_xlabel("games played while training (log scale)")
    ax.set_ylabel("rounds survived per game (moving average)")
    ax.set_title("Learning curves — exploration on (ε falls from 1 to 0.05 over the first half)")
    ax.grid(alpha=0.3)
    ax.legend()
    out = REPORTS / "learning_curves.png"
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    return out


def _example(seed: int):
    """A real situation from the simulator: the first player decision with at least 3 items in hand."""
    from player.buckshot.sim import BuckshotEnv
    env = BuckshotEnv(seed=seed)
    obs = env.reset()
    while sum(obs.get("items_player", {}).values()) < 3 or obs["phase"] != "turn":
        if env.done:
            obs = env.reset()
        legal = env.legal_actions()
        obs, *_ = env.step("shoot_dealer" if "shoot_dealer" in legal else legal[0])
        if env.done:
            obs = env.reset()
    return obs, env.legal_actions()


def network(ckpt: Path, seed: int) -> Path:
    from player.buckshot.dqn import ACTIONS, FEATURES, DQNAgent, encode
    agent = DQNAgent.load(ckpt)
    obs, legal = _example(seed)
    acts = [a.detach().numpy() for a in agent.net.activations(torch.from_numpy(encode(obs)))]
    weights = [agent.net.l1.weight.detach().numpy(), agent.net.l2.weight.detach().numpy(),
               agent.net.out.weight.detach().numpy()]
    sizes = [len(FEATURES), agent.hidden, agent.hidden, len(ACTIONS)]
    xs = [0.0, 1.0, 2.0, 3.0]
    ys = [np.linspace(1, 0, n) for n in sizes]

    fig, ax = plt.subplots(figsize=(16, 13))
    for li, w in enumerate(weights):  # w: [n_out, n_in]
        thr = np.quantile(np.abs(w), 0.94)  # draw only the strongest 6% of connections
        for o, i in zip(*np.nonzero(np.abs(w) >= thr)):
            val = w[o, i]
            ax.plot([xs[li], xs[li + 1]], [ys[li][i], ys[li + 1][o]], color="tab:blue" if val > 0 else "tab:red",
                    alpha=min(0.9, abs(val) / np.abs(w).max() + 0.05), linewidth=0.3 + 2.2 * abs(val) / np.abs(w).max(),
                    zorder=1)
    q = acts[3]
    best = max(legal, key=lambda a: q[ACTIONS.index(a)])
    for li, (n, a) in enumerate(zip(sizes, acts)):
        if li == 3:
            colors = ["gold" if ACTIONS[k] == best else ("white" if ACTIONS[k] in legal else "lightgrey")
                      for k in range(n)]
        else:
            norm = a / (a.max() + 1e-9)
            colors = plt.cm.Greens(0.15 + 0.85 * norm)
        ax.scatter(np.full(n, xs[li]), ys[li], s=55 if li in (1, 2) else 80, c=colors, edgecolors="black",
                   linewidths=0.5, zorder=3)
    for k, name in enumerate(FEATURES):
        ax.text(xs[0] - 0.04, ys[0][k], f"{name} = {acts[0][k]:.2f}", ha="right", va="center", fontsize=7,
                color="black" if acts[0][k] > 0 else "grey")
    for k, name in enumerate(ACTIONS):
        legal_here = name in legal
        label = f"{name}  Q={q[k]:.2f}" if legal_here else f"{name}  (not possible now)"
        ax.text(xs[3] + 0.04, ys[3][k], label, ha="left", va="center", fontsize=8,
                fontweight="bold" if name == best else "normal", color="black" if legal_here else "grey")
    for x, title in zip(xs, ["inputs: what it sees", "hidden layer 1", "hidden layer 2", "outputs: value of each move"]):
        ax.text(x, 1.04, title, ha="center", fontsize=11, fontweight="bold")
    ax.text(1.5, -0.06, "blue line = positive weight, red = negative, thicker = stronger (strongest 6% shown); "
            "green neuron = active for this situation; gold = the move it picks", ha="center", fontsize=9)
    ax.set_xlim(-1.1, 4.1)
    ax.set_ylim(-0.09, 1.08)
    ax.axis("off")
    ax.set_title(f"{ckpt.parent.name}/{ckpt.name}: one real situation from the simulator", fontsize=13)
    out = REPORTS / f"network_{ckpt.parent.name}_{ckpt.stem}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="what", required=True)
    sub.add_parser("curves")
    n = sub.add_parser("network")
    n.add_argument("checkpoint", type=Path)
    n.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()
    out = curves() if args.what == "curves" else network(args.checkpoint, args.seed)
    print(f"saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

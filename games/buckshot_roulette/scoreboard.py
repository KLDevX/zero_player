"""One table of every network we trained: training time, results, move accuracy against the planner,
learning progress, and which tactics each one found.

    python -m games.buckshot_roulette.scoreboard          # prints Markdown, writes docs/models.md

Move accuracy is measured on a fresh test set the networks never saw (reports/distill/test: x1 labels the
chance to win for every legal move in 300 new games): "picks x1's best move" and "loses less than 1/16 of a
win chance" (x1 counts with 16 imagined tables, so smaller differences are within its own noise), plus the
mean chance lost per move. Only clear-cut checks are listed; moves that can be a tactic are left out.
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch

from games.buckshot_roulette.distill import DATA, load_lessons
from games.buckshot_roulette.dqn import DQNAgent

GAME = Path(__file__).resolve().parent  # games/buckshot_roulette: its models, reports, docs, game copy
NETWORKS = ["d1", "d2", "d3", "d2.1", "d3.1", "d4.1", "d4.2.3-s0", "d4.2.3-s1", "d4.2.3-s2",
            "d3.1.3-s0", "d3.1.3-s1", "d3.1.3-s2", "dx1.0", "dx1.1", "dx1.2", "dx1.3", "dx1.4", "dx1.5"]
WHAT = {"d1": "DQN, +1 per round", "d2": "DQN, HP potential", "d3": "DQN, −HP −action",
        "d2.1": "DQN, HP events", "d3.1": "DQN, HP events − item cost", "d4.1": "DQN, v4 reward + n-step",
        "d4.2.3": "DQN, v4 (cigarettes free), 3 seeds × 32 tables", "d3.1.3": "DQN d3.1, 3 seeds × 32 tables",
        "dx1": "network learned from the x1 planner"}
# clear-cut checks only (from the replays): name in stats -> short label, and whether higher is better
CLEAR = [
    ("knows it's live, shoots itself", "shoots itself on a known live", False),
    ("knows it's blank, shoots the dealer (gives the turn away)", "known blank at the dealer", False),
    ("magnifier when it already knows the shell", "magnifier on a known shell", False),
    ("handcuffs on the last shell", "cuffs on the last shell", False),
    ("beer on a known live shell", "beer on a known live", False),
    ("inverter on a known live shell", "inverter on a known live", False),
]


def test_set():
    x, m, y = load_lessons([DATA / "test"])
    keep = ~m[:, -2:].any(axis=1)  # drop the synthetic double-or-nothing rows
    return x[keep], m[keep], y[keep]


def accuracy(ckpt: Path, x: np.ndarray, m: np.ndarray, y: np.ndarray) -> dict:
    agent = DQNAgent.load(ckpt)
    xin = torch.from_numpy(x[:, :len(agent.features)])  # observation v1 = the first 50 numbers of v2
    with torch.no_grad():
        q = agent.net(xin).numpy()
    q = np.where(m, q, -1e9)
    choice = q.argmax(axis=1)
    yy = np.where(m, y, -1e9)
    best = yy.max(axis=1)
    got = y[np.arange(len(y)), choice]
    lost = best - got
    return {"best_move": float((lost < 1e-6).mean()), "near_best": float((lost <= 1 / 16 + 1e-6).mean()),
            "lost_chance": float(lost.mean())}


def curve(run: str) -> str:
    path = GAME / "reports" / f"train_{run}.csv"
    if not path.exists():
        return ""
    rounds = [int(r["rounds_survived"]) for r in csv.DictReader(path.open(encoding="utf-8"))]
    tenth = max(1, len(rounds) // 10)
    return " ".join(f"{sum(rounds[i:i + tenth]) / tenth:.1f}" for i in range(0, tenth * 10, tenth))


def stats(run: str) -> dict:
    hits = sorted((GAME / "reports" / "replays").glob(f"{run}_dqn_*/stats.json"))
    return json.loads(hits[-1].read_text(encoding="utf-8")) if hits else {}


def ckpt(run: str) -> Path:
    return sorted((GAME / "models" / run).glob("dqn_*.pt"), key=lambda p: int(p.stem.split("_")[1]))[-1]


X1_LESSON_SECONDS = 975.0


def dx_minutes() -> dict:
    """Time per dx version from the night log, including x1's lessons (the slow part): cumulative minutes."""
    log = GAME / "reports" / "distill_night.log"
    if not log.exists():
        return {}
    # x1's first 3 000 games (975 s) ran before the night run was restarted, so they are not in this log
    total, out, pending = 0.0, {}, X1_LESSON_SECONDS
    for line in log.read_text(encoding="utf-8").splitlines():
        if "lessons in" in line and " s" in line:
            pending += float(line.rsplit(",", 1)[1].split()[0])
        elif ": trained on" in line:
            run = line.split("] ", 1)[1].split(":")[0]
            total += pending + float(line.split("), ")[1].split()[0])
            pending, out[run] = 0.0, total / 60
    return out


def minutes(run: str) -> str:
    meta = json.loads((GAME / "models" / run / "meta.json").read_text(encoding="utf-8"))
    sec = meta.get("training_seconds")
    return f"{sec / 60:.0f} min" if isinstance(sec, (int, float)) and sec >= 60 else (f"{sec:.0f} s" if sec else "?")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    x, m, y = test_set()
    dx_time = dx_minutes()
    rows = []
    for run in NETWORKS:
        s = stats(run)
        a = accuracy(ckpt(run), x, m, y)
        key = run.split("-s")[0] if "-s" in run else ("dx1" if run.startswith("dx1") else run)
        time = f"{dx_time[run]:.0f} min with lessons" if run in dx_time else minutes(run)
        rows.append({"run": run, "what": WHAT.get(key, ""), "time": time, **a, "stats": s,
                     "curve": curve(run)})
    out = [f"# All trained networks — one table\n", f"Test set: {len(x)} tables from 300 new games labelled by x1 "
           "(never seen in training). Results: 5 000 games, simulator seed 7, exploration off.\n",
           "Accuracy is measured against x1 with base d3.1.3-s2 — the teacher of dx and x1's own base player, so "
           "those two have a head start on it.\n",
           "| network | what | training | rounds/game | rounds won | best game | picks x1's best move | "
           "at most 1/16 below best | chance lost per move |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        s = r["stats"]
        out.append(f"| {r['run']} | {r['what']} | {r['time']} | {s.get('rounds_per_game', 0):.2f} | "
                   f"{100 * s.get('round_win_rate', 0):.1f}% | {s.get('best_game', '')} | {100 * r['best_move']:.0f}% | "
                   f"{100 * r['near_best']:.0f}% | {100 * r['lost_chance']:.1f} pts |")
    out += ["", "## Learning progress (rounds/game per tenth of training, exploration on)", ""]
    out += [f"- **{r['run']}**: {r['curve']}" for r in rows if r["curve"]]
    summary = DATA / "summary.json"
    if summary.exists():
        dx = json.loads(summary.read_text(encoding="utf-8"))
        out.append("- **dx1** (per version, exploration off, 5 000 games): "
                   + " → ".join(f"{v['version']} {v['rounds_per_game']:.2f}" for v in dx))
    out += ["", "## Clear mistakes (share of the cases; lower is better)", "",
            "| network | " + " | ".join(lbl for _, lbl, _ in CLEAR) + " |", "|---|" + "---|" * len(CLEAR)]
    for r in rows:
        mm = {**r["stats"].get("suspicious", {}), **r["stats"].get("missed", {})}
        out.append(f"| {r['run']} | " + " | ".join(f"{100 * mm.get(k, 0):.0f}%" for k, _, _ in CLEAR) + " |")
    out += ["", "## Tactics: who found what", "",
            "| network | inverter tactic done (of chances) | steals the dealer's saw on a known live | "
            "cuffs that paid off | favourite combo |", "|---|---|---|---|---|"]
    for r in rows:
        s = r["stats"]
        t, c, mm = s.get("tactic_inverter", {}), s.get("handcuffs", {}), s.get("missed", {})
        chances = t.get("chances (only lives, inverter, dealer free)", 0)
        done = t.get("then shoots itself with the inverted shell", 0)
        steal = 1 - mm.get("knows it's live, could steal the dealer's saw, doesn't", 1)
        paid = c.get("paid off: the dealer skipped a turn", 0) / max(1, c.get("cuffs used", 1))
        combo = s.get("combos", [["-", 0]])[0]
        out.append(f"| {r['run']} | {done} of {chances} ({100 * done / max(1, chances):.0f}%) | {100 * steal:.0f}% | "
                   f"{100 * paid:.0f}% | {combo[0]} ({combo[1]}×) |")
    text = "\n".join(out) + "\n"
    (GAME / "docs" / "models.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

"""Watch a trained agent play: readable move logs and a summary of its tactics.

    python -m player.buckshot.replay runs/d1/dqn_100000.pt [--games 5000] [--logs 20] [--seed 7]

Writes to reports/replays/<run>_<checkpoint>/:
  game_001.txt …  every move: what it saw, how it valued each legal move, what it chose, what happened
  thoughts.jsonl  every Thought as JSON (the same records the overlay will show)
  tactics.md      what it does in which situation, its favourite item combos
The tactics are measured from its play only; nothing here is fed back to the agent.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from player.buckshot.sim import ADRENALINE, BuckshotEnv, LIVE, STEAL, USE

ROOT = Path(__file__).resolve().parents[2]


def load_agent(path: Path, seed: int):
    if path.suffix == ".pt":
        from player.buckshot.dqn import DQNAgent
        return DQNAgent.load(path, seed=seed)
    from player.buckshot.qtable import QTableAgent
    return QTableAgent.load(path, seed=seed)


def _items(d: dict) -> str:
    return " ".join(f"{k}x{v}" for k, v in d.items()) or "-"


def describe(obs: dict) -> list[str]:
    known = obs.get("known_current") or "?"
    later = ", ".join(f"#{k + 1}={v}" for k, v in sorted(obs.get("known_later", {}).items()))
    flags = [f for f, on in (("SAW ON", obs.get("saw")), ("dealer cuffed", obs.get("dealer_cuffed")),
                             ("you cuffed", obs.get("player_cuffed")), ("current inverted", obs.get("current_inverted")))
             if on]
    return [
        f"round {obs['rounds_beat'] + 1} | HP you {obs['hp_player']}/{obs['max_hp']}, dealer {obs['hp_dealer']}/{obs['max_hp']}"
        f" | gun: {obs['live_left']} live, {obs['blank_left']} blank (last out: {obs.get('last_shell') or '-'})"
        f" | you know: now={known}{', ' + later if later else ''}{' | ' + ', '.join(flags) if flags else ''}",
        f"  items you: {_items(obs.get('items_player', {}))} | dealer: {_items(obs.get('items_dealer', {}))}",
    ]


def situation(obs: dict) -> str:
    """A coarse label of the situation, for the tactics table (analysis only)."""
    if obs["phase"] != "turn":
        return obs["phase"]
    known = obs.get("known_current")
    if known:
        return f"knows it's {known}"
    if obs.get("current_inverted"):
        return "unknown, inverted"
    live, blank = obs["live_left"], obs["blank_left"]
    if live == 0:
        return "only blanks left"
    if blank == 0:
        return "only lives left"
    share = live / (live + blank)
    return "unknown, more blanks" if share < 0.5 else ("unknown, 50/50" if share == 0.5 else "unknown, more lives")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint", type=Path)
    ap.add_argument("--games", type=int, default=5000)
    ap.add_argument("--logs", type=int, default=20, help="how many games to write as readable logs")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the Windows console is cp1251

    agent = load_agent(args.checkpoint, args.seed)
    out = ROOT / "reports" / "replays" / f"{args.checkpoint.parent.name}_{args.checkpoint.stem}"
    out.mkdir(parents=True, exist_ok=True)
    env = BuckshotEnv(seed=args.seed)
    by_situation: dict[str, Counter] = defaultdict(Counter)
    combos, steals, item_context = Counter(), Counter(), defaultdict(Counter)
    rounds_all = []
    # Moves that look wasteful (analysis only): description -> (item, test on the observation)
    suspicious = {
        "cigarettes at full HP": ("cigarettes", lambda o: o["hp_player"] == o["max_hp"]),
        "expired medicine at full HP (can only lose HP)": ("expired medicine", lambda o: o["hp_player"] == o["max_hp"]),
        "magnifier when it already knows the shell": ("magnifying glass", lambda o: o.get("known_current")),
        "handsaw when it knows the shell is blank": ("handsaw", lambda o: o.get("known_current") == "blank"),
    }
    sus_hits, sus_uses = Counter(), Counter()
    best = (-1, 0)
    with (out / "thoughts.jsonl").open("w", encoding="utf-8") as tj:
        for g in range(1, args.games + 1):
            obs = env.reset()
            lines, turn_moves = [], []
            while not env.done:
                legal = env.legal_actions()
                t = agent.think(obs, legal)
                tj.write(t.to_json() + "\n")
                by_situation[situation(obs)][_kind(t.choice)] += 1
                if t.choice.startswith(USE):
                    item_context[t.choice[len(USE):]][situation(obs)] += 1
                if t.choice.startswith(STEAL):
                    steals[t.choice[len(STEAL):]] += 1
                if t.choice.startswith((USE, STEAL)):
                    item = t.choice.split(":", 1)[1]
                    for name, (sus_item, test) in suspicious.items():
                        if item == sus_item:
                            sus_uses[name] += 1
                            sus_hits[name] += bool(test(obs))
                if obs["phase"] in ("turn", "steal"):
                    turn_moves.append(t.choice.replace(USE, "").replace(STEAL, "steal "))
                if t.choice.startswith("shoot"):
                    if len(turn_moves) > 1:
                        combos[" → ".join(turn_moves)] += 1
                    turn_moves = []
                if g <= args.logs:
                    lines += describe(obs)
                    ranked = sorted(t.values.items(), key=lambda kv: -kv[1]) if t.values else []
                    lines.append("  thinks: " + " · ".join(f"{a} {v:.2f}" for a, v in ranked))
                    lines.append(f"  → {t.choice}")
                obs, _, _, info = env.step(t.choice)
                if g <= args.logs:
                    lines += [f"     {e}" for e in info["events"]] + [""]
            rounds_all.append(env.s.rounds_beat)
            best = max(best, (env.s.rounds_beat, g))
            if g <= args.logs:
                header = f"game {g}: survived {env.s.rounds_beat} rounds ({args.checkpoint.parent.name}/{args.checkpoint.name})"
                (out / f"game_{g:03d}.txt").write_text(header + "\n\n" + "\n".join(lines), encoding="utf-8")

    n = len(rounds_all)
    md = [f"# Tactics of {args.checkpoint.parent.name}/{args.checkpoint.name}", "",
          f"{n} games in the simulator, exploration off, seed {args.seed}. "
          f"Mean rounds survived {sum(rounds_all) / n:.2f}, best game {best[0]} rounds (game {best[1]}).", "",
          "## What it does in each situation (share of its moves)", "",
          "| situation | moves | shoot dealer | shoot self | use an item | steal | double yes |", "|---|---|---|---|---|---|---|"]
    for sit, c in sorted(by_situation.items(), key=lambda kv: -sum(kv[1].values())):
        tot = sum(c.values())
        md.append(f"| {sit} | {tot} | " + " | ".join(f"{c[k] / tot:.0%}" for k in
                                                      ("shoot_dealer", "shoot_self", "item", "steal", "double_yes")) + " |")
    md += ["", "## When it uses each item (situation at the moment of use)", ""]
    for item, c in sorted(item_context.items(), key=lambda kv: -sum(kv[1].values())):
        tot = sum(c.values())
        top = ", ".join(f"{s} {v / tot:.0%}" for s, v in c.most_common(3))
        md.append(f"- **{item}** ({tot}×): {top}")
    md += ["", "## Favourite combos in one turn (items, then the shot)", ""]
    md += [f"{i}. {combo} — {cnt}×" for i, (combo, cnt) in enumerate(combos.most_common(15), 1)]
    md += ["", "## What it steals with adrenaline", "", ", ".join(f"{k} {v}×" for k, v in steals.most_common())]
    md += ["", "## Suspicious moves (places to improve)", ""]
    md += [f"- {name}: {sus_hits[name]} of {sus_uses[name]} uses ({sus_hits[name] / max(1, sus_uses[name]):.0%})"
           for name in suspicious]
    (out / "tactics.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\nlogs: {out.relative_to(ROOT)} (game_001.txt … game_{min(args.logs, n):03d}.txt, best game {best[1]})")


def _kind(action: str) -> str:
    if action.startswith(USE):
        return "item"
    if action.startswith(STEAL):
        return "steal"
    return action


if __name__ == "__main__":
    main()

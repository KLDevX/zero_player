"""Check games played on the real game through the overlay: did the agent see the table correctly?

    python -m player.buckshot.livecheck [reports/live_thoughts/<file>.jsonl]   (default: the newest file)

For every logged decision it compares what the agent was given with the raw bridge state and flags
mismatches (a reading problem in the bridge or the adapter, not the agent's fault), then shows what the
agent chose, so it can be compared with its play in the simulator (reports/replays/*/stats.json).
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def checks(rec: dict) -> list[str]:
    obs, pub, legal = rec["thought"]["observation"], rec["bridge_public"] or {}, rec["bridge_legal"] or []
    found = []
    if obs["live_left"] + obs["blank_left"] != pub.get("shells_left"):
        found.append(f"shell count: live {obs['live_left']} + blank {obs['blank_left']} != {pub.get('shells_left')} in the gun")
    if obs["phase"] == "turn":
        for item, n in obs.get("items_player", {}).items():
            if n and f"item:{item}:player" not in legal and item not in ("handsaw", "handcuffs", "adrenaline"):
                found.append(f"has {item} but it isn't clickable")
        for key in legal:
            if key.startswith("item:") and key.endswith(":player"):
                item = key.split(":")[1]
                if not obs.get("items_player", {}).get(item):
                    found.append(f"{item} is clickable but the count says 0")
    info = pub.get("load_info") or {}
    if "fired" in obs and info:
        out = info["loaded_live"] + info["loaded_blank"] - pub.get("shells_left", 0)
        if len(obs["fired"]) != out:
            found.append(f"shells out: {len(obs['fired'])} in the history but {out} left the gun")
    if obs["hp_player"] > obs["max_hp"] or obs["hp_dealer"] > obs["max_hp"]:
        found.append(f"HP above max ({obs['hp_player']}/{obs['hp_dealer']} > {obs['max_hp']})")
    return found


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = sorted((ROOT / "reports" / "live_thoughts").glob("*.jsonl"))
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else (files[-1] if files else None)
    if path is None:
        raise SystemExit("no live games logged yet: play with python -m player.buckshot.overlay")
    recs = [json.loads(line) for line in path.open(encoding="utf-8")]
    problems, choices, offered = Counter(), Counter(), Counter()
    examples = {}
    phone = Counter()
    for prev, r in zip(recs, recs[1:]):
        if prev["thought"]["choice"] in ("use:burner phone", "steal:burner phone"):
            left = (prev["bridge_public"] or {}).get("shells_left", 0)
            if left <= 1:
                phone["used on the last shell (nothing to tell)"] += 1
            elif r["thought"]["observation"].get("known_later"):
                phone["read: the next decision knows a later shell"] += 1
            else:
                phone["NOT read: no later shell known after the phone"] += 1
    used = Counter()
    for r in recs:
        for item, n in (r["thought"]["observation"].get("dealer_used") or {}).items():
            used[item] = max(used[item], n)
    for r in recs:
        for p in checks(r):
            kind = p.split(":")[0] if ":" in p else p.split(" but")[0]
            problems[kind] += 1
            examples.setdefault(kind, (r["time"], p))
        choices[r["thought"]["choice"]] += 1
        offered.update(r["thought"]["legal"])
    print(f"{path.name}: {len(recs)} decisions by {recs[0]['thought']['agent'] if recs else '?'}")
    print("\nreading problems (bridge/adapter):" if problems else "\nno reading problems found")
    for kind, n in problems.most_common():
        print(f"  {n:4d}× {examples[kind][1]}   (first at {examples[kind][0]})")
    print("\nburner phone:", dict(phone) if phone else "not used in this session")
    print("dealer item uses seen (most in one load):", dict(used) if used else "none")
    print("\nhow often it picked a move when it was possible:")
    for a, n in sorted(offered.items(), key=lambda kv: -choices[kv[0]] / kv[1]):
        print(f"  {a:28s} {choices[a] / n:4.0%} of {n}")


if __name__ == "__main__":
    main()

"""Print the bridge log live as short lines: python -m player.buckshot.bridge.watch [--hidden]

Reads the newest reports/live_*.jsonl written by bridge.gd. By default only public info is shown;
--hidden also shows the real shell order (for checking the bridge, never for the agent).
"""
import json
import sys
import time
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[3] / "reports"


def short(state: dict, hidden: bool) -> str:
    if "event" in state:
        return f"--- {state['event']}"
    p = state["public"]
    info = p["load_info"]
    items = lambda d: ",".join(f"{k}x{v}" for k, v in d.items()) or "-"
    line = (
        f"batch {p['batch']} load {p['load']} | loaded {info.get('loaded_live', '?')}L/{info.get('loaded_blank', '?')}B"
        f" left {p['shells_left']} | HP you {p['hp_player']} dealer {p['hp_dealer']}"
        f" | you [{items(p['items_player'])}] dealer [{items(p['items_dealer'])}]"
        f"{' | SAW' if p['saw'] else ''}{' | you cuffed' if p['player_cuffed'] else ''}"
        f"{' | dealer cuffed' if p['dealer_cuffed'] else ''}"
        f" | {'YOUR MOVE' if p['player_input'] else 'wait'}"
        f" | DoN cycles {p['don_cycles_beat']} prize {p['don_prize']} rounds {p['rounds_beat']}"
        f" | x{state['time_scale']:g}"
    )
    if hidden:
        line += f" | hidden {state['_hidden']['sequence']}"
    return line


def main() -> None:
    hidden = "--hidden" in sys.argv
    logs = sorted(REPORTS.glob("live_*.jsonl"))
    if not logs:
        sys.exit(f"no live_*.jsonl in {REPORTS}; start the lab copy of the game first")
    print(f"watching {logs[-1].name} (Ctrl+C to stop)")
    with logs[-1].open(encoding="utf-8") as f:
        while True:
            raw = f.readline()
            if not raw:
                time.sleep(0.2)
                continue
            print(short(json.loads(raw), hidden), flush=True)


if __name__ == "__main__":
    main()

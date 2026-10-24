"""The AI's brain for the interface inside the game (docs/ui-plan.md). The bridge draws; this thinks.

    python -m player.buckshot.ingame --agent runs/dx1.5/dqn_991956.pt      (launch.py runs this for you)

Reads the table through the bridge, asks the agent for its thought and sends it to the in-game panels.
Keys in the game (handled by the bridge): F1 AI on/off (off at start: you play, it advises) · → one move in
step mode · Space auto ↔ step · Ctrl+1…4 speed ×1/×3/×10/×20 · F6 interface style.
With the AI on it also walks the menus (pills, doors, waiver). Every decision is logged to
reports/live_thoughts/, every game to reports/games.csv with who played it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from player.buckshot.bridge.client import Bridge
from player.buckshot.live import LiveGame
from player.buckshot.replay import load_agent
from player.buckshot.testbot import choose, save_game

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AGENT = ROOT / "runs" / "dx1.5" / "dqn_991956.pt"
NAMES = {
    "shoot_self": "выстрел в себя", "shoot_dealer": "выстрел в дилера", "double_yes": "ещё круг (Double)",
    "double_no": "забрать деньги", "handcuffs": "наручники", "beer": "пиво", "magnifying glass": "лупа",
    "cigarettes": "сигареты", "handsaw": "пила", "expired medicine": "лекарство", "inverter": "инвертор",
    "burner phone": "телефон", "adrenaline": "адреналин",
}


def say(action: str) -> str:
    if action.startswith("use:"):
        return NAMES.get(action[4:], action[4:])
    if action.startswith("steal:"):
        return "украсть: " + NAMES.get(action[6:], action[6:])
    return NAMES.get(action, action)


class Brain:
    def __init__(self, agent_path: Path, speed: float, pause: float, mute: bool = False):
        self.agent = load_agent(agent_path, seed=0)
        meta = agent_path.parent / "meta.json"
        info = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        # Q is a chance to win the round only with the plain reward (+1 per round won) and for dx (x1's chances).
        self.q_is_chance = info.get("shaping", "none") == "none"
        self.name = f"{agent_path.parent.name}@{getattr(self.agent, 'games_trained', '?')}"
        self.speed, self.pause, self.mute = speed, pause, mute
        log_dir = ROOT / "reports" / "live_thoughts"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"{datetime.now():%Y-%m-%dT%H-%M-%S}_ingame_{agent_path.parent.name}.jsonl"
        self.sent = ""

    def _log(self, thought, st: dict, ui: dict) -> None:
        record = {"time": datetime.now().isoformat(timespec="milliseconds"),
                  "mode": "play" if ui.get("ai_on") else "hint", "ui": ui,
                  "thought": json.loads(thought.to_json()), "bridge_public": st.get("public"),
                  "bridge_legal": st.get("legal")}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _show(self, bridge: Bridge, thought=None, status: str = "") -> None:
        """Sends what the right panel shows; only when it changed."""
        view = {"agent": self.name, "status": status, "names": NAMES}
        if thought is not None:
            values = thought.values or {}
            chance = lambda a: min(1.0, max(0.0, values[a])) if self.q_is_chance and a in values else None
            others = sorted((a for a in values if a != thought.choice), key=lambda a: -values[a])[:2]
            view |= {"move": say(thought.choice), "chance": chance(thought.choice),
                     "alts": [[say(a), chance(a)] for a in others] if self.q_is_chance else []}
        key = json.dumps(view, ensure_ascii=False, sort_keys=True)
        if key != self.sent:
            self.sent = key
            bridge.thought(view)

    def run(self) -> None:
        bridge = Bridge()
        game = LiveGame(bridge, speed=self.speed)
        bridge.speed(self.speed)
        bridge.mute(self.mute)
        print(f"connected: {self.name}. In the game: F1 AI on/off, → move, Space auto, Ctrl+1…4 speed, F6 style")
        last_key, thought, shown_at, typed, last_choice = None, None, 0.0, [], ""
        started, last_obs, ai_moves, your_moves = None, None, 0, 0
        while True:
            st, obs, legal = game.read()
            ui = st.get("ui", {})
            game.speed = float(ui.get("speed", 1.0)) or 1.0
            if obs is not None and started is None:
                started, ai_moves, your_moves = time.time(), 0, 0
            if obs is None and started is not None and last_obs is not None:  # left the table: game over
                rounds = last_obs["rounds_beat"]
                who = self.name if your_moves == 0 else (f"akel (hints {self.name})" if ai_moves == 0
                                                         else f"akel + {self.name}")
                save_game({"finished_at": datetime.now().isoformat(timespec="seconds"), "bot": who,
                           "speed": game.speed, "seconds": round(time.time() - started, 1),
                           "actions": ai_moves + your_moves, "rounds_beat": rounds + 1, "rounds_survived": rounds,
                           "don_cycles_beat": (st.get("public") or {}).get("don_cycles_beat", 0),
                           "don_prize": 0, "end": "death"})
                print(f"game saved: {who}, rounds survived {rounds} (AI moves {ai_moves}, yours {your_moves})")
                started, last_obs = None, None
            if obs is not None:
                last_obs = obs
            if obs is not None and legal:
                key = json.dumps([obs, legal], sort_keys=True)
                if key != last_key:
                    if last_key is not None:
                        your_moves += 1  # the decision changed without the AI acting: you moved
                    last_key, thought, shown_at = key, self.agent.think(obs, legal), time.time()
                    self._log(thought, st, ui)
                self._show(bridge, thought)
                if ui.get("ai_on"):
                    due = time.time() - shown_at >= self.pause / game.speed
                    if (ui.get("auto") and due) or (not ui.get("auto") and bridge.take_step()):
                        self._show(bridge, thought, status=f"ход: {say(thought.choice)}")
                        if game.perform(thought.choice):
                            ai_moves += 1
                        last_key, last_choice = None, say(thought.choice)
                time.sleep(0.03)
                continue
            if last_key is not None:
                your_moves += 1  # the decision went away without the AI acting: you moved
            last_key = None
            waiting = "жду своего хода…" if obs is not None else "ждём стол (Double or Nothing)…"
            self._show(bridge, None, status=waiting + (f"   последний ход: {last_choice}" if last_choice and obs else ""))
            if ui.get("ai_on"):
                keys = st.get("legal", [])
                nav = [k for k in keys if not k.startswith(("item:", "shotgun", "text ", "double"))]
                step = choose(nav, st.get("public"), typed) if nav else ""
                if step:
                    if step == "release form on table":
                        typed = []  # a new waiver to sign
                    game.click_when_ready(step, timeout=5)
            time.sleep(0.05)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", type=Path, default=DEFAULT_AGENT, help="checkpoint, e.g. runs/dx1.5/dqn_991956.pt")
    ap.add_argument("--speed", type=float, default=1.0, help="starting game speed (Ctrl+1…4 in the game)")
    ap.add_argument("--mute", action="store_true", help="no game sound (tests without a person watching)")
    ap.add_argument("--pause", type=float, default=1.5, help="auto mode: game seconds to show a thought before acting")
    args = ap.parse_args()
    try:
        Brain(args.agent, args.speed, args.pause, args.mute).run()
    except ConnectionError as e:
        print(f"the game closed the connection: {e}")


if __name__ == "__main__":
    main()

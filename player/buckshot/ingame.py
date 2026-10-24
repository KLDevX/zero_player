"""The AI's brain for the interface inside the game (docs/ui-plan.md). The bridge draws; this thinks.

    python -m player.buckshot.ingame --agent runs/dx1.5/dqn_991956.pt      (launch.py runs this for you)

Reads the table through the bridge, asks the agent for its thought and sends it to the in-game panels.
Keys in the game (handled by the bridge): F1 AI on/off (off at start: you play, it advises) · → one move in
step mode · Space auto ↔ step · Ctrl+1…4 speed ×1/×3/×10/×20 · I all data · N the network ·
~ developer mode (console, model switch, cheats that show the shell order on screen only — the agent never
gets them).
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

import numpy as np
import torch

from player.buckshot.bridge.client import Bridge
from player.buckshot.dqn import ACTION_INDEX
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

SHORT = {"shoot_self": "в себя", "shoot_dealer": "в дилера"}  # for the one-line list of next moves


def say(action: str) -> str:
    if action.startswith("use:"):
        return NAMES.get(action[4:], action[4:])
    if action.startswith("steal:"):
        return "украсть: " + NAMES.get(action[6:], action[6:])
    return NAMES.get(action, action)


TIE = 0.01  # moves this close to the best one are "almost equal" (dx's values are noisy by about that much)
EDGES = 24  # strongest connections drawn per layer on the N panel


def models() -> dict[str, Path]:
    """Every trained network in runs/: name -> its last checkpoint."""
    out = {}
    for run in sorted(p for p in (ROOT / "runs").iterdir() if p.is_dir() and p.name != "archive"):
        ckpts = sorted(run.glob("dqn_*.pt"), key=lambda c: int(c.stem.split("_")[1]))
        if ckpts:
            out[run.name] = ckpts[-1]
    return out


class Brain:
    def __init__(self, agent_path: Path, speed: float, pause: float, mute: bool = False):
        self.models = models()
        self._load(agent_path)
        self.speed, self.pause, self.mute = speed, pause, mute
        log_dir = ROOT / "reports" / "live_thoughts"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"{datetime.now():%Y-%m-%dT%H-%M-%S}_ingame_{agent_path.parent.name}.jsonl"
        self.sent = ""

    def _load(self, agent_path: Path) -> None:
        self.agent = load_agent(agent_path, seed=0)
        self.run_name = agent_path.parent.name
        meta = agent_path.parent / "meta.json"
        info = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        # Q is a chance to win the round only with the plain reward (+1 per round won) and for dx (x1's chances).
        self.q_is_chance = info.get("shaping", "none") == "none"
        self.name = f"{self.run_name}@{getattr(self.agent, 'games_trained', '?')}"

    def _dev_info(self, bridge: Bridge) -> None:
        bridge._call(cmd="dev_info", models=list(self.models), current=self.name)

    def _switch(self, bridge: Bridge, run: str) -> None:
        if run not in self.models:
            bridge._call(cmd="dev_log", text=f"нет модели {run}")
            return
        self._load(self.models[run])
        self._dev_info(bridge)
        bridge._call(cmd="dev_log", text=f"загружена {self.name}" + ("" if self.q_is_chance else
                     " (её числа — оценка награды, не шанс)"))
        print(f"model switched: {self.name}")

    def _net(self, thought) -> dict:
        """The N panel: how strongly each neuron fires for this table, and the strongest connections."""
        net = getattr(getattr(self.agent, "net", None), "activations", None)
        if net is None:
            return {}
        with torch.no_grad():
            acts = [a.numpy() for a in net(torch.from_numpy(self.agent.encode(thought.observation)))]
        layers = [acts[0]] + [a / (np.abs(a).max() or 1.0) for a in acts[1:3]]
        layers.append(np.clip(acts[3], 0, 1) if self.q_is_chance else acts[3] / (np.abs(acts[3]).max() or 1.0))
        edges = []
        weights = [self.agent.net.l1.weight, self.agent.net.l2.weight, self.agent.net.out.weight]
        choice = ACTION_INDEX[thought.choice]
        for li, w in enumerate(weights):
            contrib = w.detach().numpy() * acts[li][None, :]  # [to, from]: what each input adds to each neuron
            if li == 2:
                rows = np.zeros_like(contrib)
                rows[choice] = contrib[choice]  # into the chosen move only
                contrib = rows
            top = np.abs(contrib).max() or 1.0
            for k in np.argsort(-np.abs(contrib), axis=None)[:EDGES]:
                j, i = np.unravel_index(k, contrib.shape)
                if contrib[j, i] != 0:
                    edges.append([li, int(i), int(j), round(float(contrib[j, i] / top), 2)])
        return {"layers": [[round(float(v), 2) for v in layer] for layer in layers], "edges": edges,
                "legal": [ACTION_INDEX[a] for a in thought.legal], "choice": choice}

    def _log(self, thought, st: dict, ui: dict) -> None:
        record = {"time": datetime.now().isoformat(timespec="milliseconds"),
                  "mode": "play" if ui.get("ai_on") else "hint", "ui": ui,
                  "thought": json.loads(thought.to_json()), "bridge_public": st.get("public"),
                  "bridge_legal": st.get("legal")}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _show(self, bridge: Bridge, thought=None, status: str = "", ui: dict | None = None, last: str = "") -> None:
        """Sends what the panels show; only when it changed."""
        view = {"agent": self.name, "status": status, "names": NAMES, "last": last}
        if thought is not None:
            values = thought.values or {}
            chance = lambda a: min(1.0, max(0.0, values[a])) if self.q_is_chance and a in values else None
            ranked = sorted(values, key=lambda a: -values[a])
            others = [a for a in ranked if a != thought.choice][:2]
            best = values.get(thought.choice, 0.0)
            view |= {"move": say(thought.choice), "chance": chance(thought.choice),
                     "alts": [[SHORT.get(a, say(a)), chance(a)] for a in others] if self.q_is_chance else [],
                     "all": [[say(a), chance(a)] for a in ranked],
                     "tie": bool(others) and best - values[others[0]] < TIE}
            if (ui or {}).get("panel_n"):
                view["net"] = self._net(thought)
        key = json.dumps(view, ensure_ascii=False, sort_keys=True)
        if key != self.sent:
            self.sent = key
            bridge.thought(view)

    def run(self) -> None:
        bridge = Bridge()
        game = LiveGame(bridge, speed=self.speed)
        bridge.speed(self.speed)
        bridge.mute(self.mute)
        self._dev_info(bridge)
        print(f"connected: {self.name}. In the game: F1 AI on/off, → move, Space auto, Ctrl+1…4 speed, "
              "I data, N network, ~ developer mode")
        last_key, thought, shown_at, typed, last_choice = None, None, 0.0, [], ""
        started, last_obs, ai_moves, your_moves, cheated = None, None, 0, 0, False
        while True:
            st, obs, legal = game.read()
            ui = st.get("ui", {})
            game.speed = float(ui.get("speed", 1.0)) or 1.0
            if ui.get("model_req") and ui["model_req"] != self.run_name:
                self._switch(bridge, ui["model_req"])
                last_key = None  # think again with the new network
            if obs is not None and started is None:
                started, ai_moves, your_moves, cheated = time.time(), 0, 0, False
            cheated = cheated or bool(ui.get("cheat") and obs is not None)
            if obs is None and started is not None and last_obs is not None:  # left the table: game over
                rounds = last_obs["rounds_beat"]
                who = self.name if your_moves == 0 else (f"akel (hints {self.name})" if ai_moves == 0
                                                         else f"akel + {self.name}")
                who += " (cheats)" if cheated else ""
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
                self._show(bridge, thought, ui=ui)
                if ui.get("ai_on"):
                    due = time.time() - shown_at >= self.pause / game.speed
                    if (ui.get("auto") and due) or (not ui.get("auto") and bridge.take_step()):
                        self._show(bridge, thought, status=f"ход: {say(thought.choice)}", ui=ui)
                        if game.perform(thought.choice):
                            ai_moves += 1
                        last_key, last_choice = None, say(thought.choice)
                time.sleep(0.03)
                continue
            if last_key is not None:
                your_moves += 1  # the decision went away without the AI acting: you moved
            last_key = None
            waiting = "жду своего хода…" if obs is not None else "ждём стол (Double or Nothing)…"
            self._show(bridge, None, status=waiting, last=last_choice if obs is not None else "")
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

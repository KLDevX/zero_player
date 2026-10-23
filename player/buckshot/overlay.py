"""Overlay: what the agent thinks, on top of the game (lab copy with the bridge).

    python -m player.buckshot.overlay --agent runs/d1/dqn_100000.pt                 # hint mode: you play
    python -m player.buckshot.overlay --agent runs/d1/dqn_100000.pt --mode play --speed 1 --pause 1.5
                                                                                    # play mode: it plays
Top left: the shells (order unknown) and what it knows. Top right: the move it recommends and its value.
F8: the advanced panel (every legal move with its value, how it read the table). F10: quit.
The window is transparent and lets clicks through. The game is switched to borderless fullscreen, because
exclusive fullscreen hides every other window. Every game is appended to reports/games.csv.
See docs/overlay-design.md.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

from player.buckshot.bridge.client import Bridge
from player.buckshot.live import LiveGame
from player.buckshot.replay import load_agent
from player.buckshot.testbot import choose, save_game

ROOT = Path(__file__).resolve().parents[2]
KEY_COLOUR = "#010101"  # painted pixels in this colour are see-through
PANEL, TEXT, DIM, LIVE_C, BLANK_C, GOOD = "#15171c", "#e8e8e8", "#9aa0a6", "#ff5a5f", "#5b9bff", "#ffd54a"
VK_F8, VK_F10 = 0x77, 0x79
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


def shell_word(s: str | None) -> str:
    return {"live": "боевой", "blank": "холостой"}.get(s or "", "?")


class Brain(threading.Thread):
    """Talks to the bridge and the agent; the window only draws `self.view`."""

    def __init__(self, args):
        super().__init__(daemon=True)
        self.args = args
        self.agent = load_agent(args.agent, seed=0)
        meta = args.agent.parent / "meta.json"
        info = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        # Q is a chance to win the round only with the plain reward (+1 per round won).
        self.q_is_chance = info.get("shaping", "none") == "none"
        self.name = f"{args.agent.parent.name}@{getattr(self.agent, 'games_trained', '?')}"
        self.view: dict = {"status": "подключаюсь к игре…"}
        # Every decision on the real game: what the agent saw and thought + the raw bridge state, so live play
        # can be checked against the screen and the simulator (python -m player.buckshot.livecheck).
        log_dir = ROOT / "reports" / "live_thoughts"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"{datetime.now():%Y-%m-%dT%H-%M-%S}_{args.mode}_{args.agent.parent.name}.jsonl"
        self.last_thought = None  # stays on screen until the next decision
        self.stop = False

    def _log_thought(self, thought, st: dict) -> None:
        record = {"time": datetime.now().isoformat(timespec="milliseconds"), "mode": self.args.mode,
                  "thought": json.loads(thought.to_json()), "bridge_public": st.get("public"),
                  "bridge_legal": st.get("legal")}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def run(self) -> None:
        try:
            bridge = Bridge()
        except OSError:
            self.view = {"status": "мост не отвечает: запусти копию игры из game_lab"}
            return
        game = LiveGame(bridge, speed=self.args.speed)
        bridge.window("borderless")
        bridge.speed(self.args.speed if self.args.mode == "play" else 1.0)
        last_key, thought, shown_at, typed = None, None, 0.0, []
        started, actions, last_obs = None, 0, None
        while not self.stop:
            st, obs, legal = game.read()
            if obs is not None and started is None:
                started, actions = time.time(), 0
            if obs is None and started is not None and last_obs is not None:  # left the table: game over
                rounds = last_obs["rounds_beat"]
                save_game({"finished_at": datetime.now().isoformat(timespec="seconds"),
                           "bot": self.name if self.args.mode == "play" else f"akel (hints {self.name})",
                           "speed": self.args.speed if self.args.mode == "play" else 1.0,
                           "seconds": round(time.time() - started, 1), "actions": actions,
                           "rounds_beat": rounds + 1, "rounds_survived": rounds,
                           "don_cycles_beat": st.get("public", {}).get("don_cycles_beat", 0) if st.get("public") else 0,
                           "don_prize": 0, "end": "death"})
                started, last_obs = None, None
            if obs is not None:
                last_obs = obs
            if obs is not None and legal:
                key = json.dumps([obs, legal], sort_keys=True)
                if key != last_key:
                    last_key, thought, shown_at = key, self.agent.think(obs, legal), time.time()
                    self.last_thought = thought
                    self._log_thought(thought, st)
                self.view = {"obs": obs, "thought": thought, "mode": self.args.mode, "status": ""}
                if self.args.mode == "play" and time.time() - shown_at >= self.args.pause:
                    self.view = {**self.view, "status": f"ход: {say(thought.choice)}"}
                    if game.perform(thought.choice):
                        actions += 1
                    last_key = None
                time.sleep(0.05)
                continue
            self.view = {"obs": obs, "thought": None, "last": self.last_thought if obs is not None else None,
                         "mode": self.args.mode, "status": "жду своего хода…" if obs is not None else "ждём игру…"}
            if self.args.mode == "play":
                keys = st.get("legal", [])
                nav = [k for k in keys if not k.startswith(("item:", "shotgun", "text ", "double"))]
                step = choose(nav, st.get("public"), typed) if nav else ""
                if step:
                    if step == "release form on table":
                        typed = []  # a new waiver to sign
                    game.click_when_ready(step, timeout=5)
            time.sleep(0.05)


class Overlay:
    def __init__(self, brain: Brain):
        self.brain = brain
        self.advanced = False
        self.f8_down = False
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", KEY_COLOUR)
        w, h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+0+0")
        self.root.configure(bg=KEY_COLOUR)
        self.left = self._panel(anchor="nw", x=18, y=18)
        self.right = self._panel(anchor="ne", x=w - 18, y=18)
        self.adv = self._panel(anchor="ne", x=w - 18, y=200, font=("Consolas", 11))
        self.root.update_idletasks()
        self._click_through()
        self.root.after(100, self.tick)

    def _panel(self, anchor: str, x: int, y: int, font=("Segoe UI", 14)) -> tk.Label:
        lab = tk.Label(self.root, text="", justify="left", bg=PANEL, fg=TEXT, font=font, padx=14, pady=10)
        lab.place(x=x, y=y, anchor=anchor)
        return lab

    def _click_through(self) -> None:
        u = ctypes.windll.user32
        hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = -20, 0x80000, 0x20, 0x80, 0x08000000
        style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)

    def tick(self) -> None:
        keys = ctypes.windll.user32.GetAsyncKeyState
        if keys(VK_F10) & 0x8000:
            self.brain.stop = True
            self.root.destroy()
            return
        f8 = bool(keys(VK_F8) & 0x8000)
        if f8 and not self.f8_down:
            self.advanced = not self.advanced
        self.f8_down = f8
        self.draw(self.brain.view)
        self.root.attributes("-topmost", True)
        self.root.after(80, self.tick)

    def draw(self, view: dict) -> None:
        obs, t = view.get("obs"), view.get("thought")
        if obs is None:
            self.left.config(text=f"Buckshot AI · {self.brain.name}\n{view.get('status', '')}")
            self.right.config(text="F8 — подробно · F10 — выход")
            self.adv.place_forget() if not self.advanced else self.adv.config(text="(нет данных)")
            return
        later = ", ".join(f"#{k + 1} {shell_word(v)}" for k, v in sorted(obs.get("known_later", {}).items()))
        lines = [f"ПАТРОНЫ (порядок неизвестен)",
                 f"боевых: {obs['live_left']}    холостых: {obs['blank_left']}",
                 f"в стволе: {shell_word(obs.get('known_current'))}"
                 + ("  (перевёрнут инвертором)" if obs.get("current_inverted") else ""),
                 f"последний вылетел: {shell_word(obs.get('last_shell'))}" if obs.get("last_shell") else "",
                 f"знаю дальше: {later}" if later else "",
                 f"жизни: ты {obs['hp_player']}/{obs['max_hp']} · дилер {obs['hp_dealer']}/{obs['max_hp']}"]
        self.left.config(text="\n".join(x for x in lines if x))
        if t is None:
            last = view.get("last")
            prev = f"\nпоследний ход: {say(last.choice)}" if last is not None else ""
            self.right.config(text=f"{'ИИ играет' if view.get('mode') == 'play' else 'Подсказки'} · {self.brain.name}"
                                   f"{prev}\n{view.get('status', '')}\nF8 — подробно", fg=DIM)
        else:
            best = t.values[t.choice] if t.values else None
            value = (f"шанс выиграть раунд: {min(1, max(0, best)):.0%}" if self.brain.q_is_chance
                     else f"оценка хода: {best:.2f}") if best is not None else ""
            head = "ИИ ходит" if view.get("mode") == "play" else "СОВЕТ"
            self.right.config(text=f"{head}: {say(t.choice)}\n{value}\n"
                                   f"{view.get('status') or ''}{'' if view.get('status') else 'F8 — подробно'}",
                              fg=GOOD)
        t = t or view.get("last")
        if self.advanced and t is not None:
            ranked = sorted((t.values or {}).items(), key=lambda kv: -kv[1])
            top = max((v for _, v in ranked), default=1) or 1
            rows = [f"{say(a):<22} {v:5.2f} {'█' * max(0, int(12 * v / top))}" for a, v in ranked]
            items = lambda d: ", ".join(f"{NAMES.get(k, k)}×{v}" for k, v in d.items()) or "—"
            rows += ["", f"агент: {t.agent}  {'(разведка)' if t.exploring else ''}",
                     f"мои предметы: {items(obs.get('items_player', {}))}",
                     f"у дилера: {items(obs.get('items_dealer', {}))}",
                     f"пила: {'да' if obs.get('saw') else 'нет'} · дилер в наручниках: {'да' if obs.get('dealer_cuffed') else 'нет'}"
                     f" · ты в наручниках: {'да' if obs.get('player_cuffed') else 'нет'}"]
            self.adv.config(text="\n".join(rows))
            self.adv.place(x=self.root.winfo_screenwidth() - 18, y=200, anchor="ne")
        else:
            self.adv.place_forget()

    def run(self) -> None:
        self.brain.start()
        self.root.mainloop()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", type=Path, required=True, help="checkpoint, e.g. runs/d1/dqn_100000.pt")
    ap.add_argument("--mode", choices=("hint", "play"), default="hint")
    ap.add_argument("--speed", type=float, default=1.0, help="play mode: game speed")
    ap.add_argument("--pause", type=float, default=1.5, help="play mode: seconds to show a thought before acting")
    args = ap.parse_args()
    Overlay(Brain(args)).run()


if __name__ == "__main__":
    main()

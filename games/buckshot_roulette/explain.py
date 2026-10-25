"""Why the network picks a move: how much each thing it sees adds to the move's value (the "why" window, I).

Integrated gradients: walk the input from an average table to the real one in small steps and add up how
the move's value changes along the way, number by number. The pieces add up to
value(real table) − value(average table), so every reason gets a coefficient in the move's own units
(for dx: points of the chance to win the round): "the dealer has 1 HP" helps, "you have no saw" hurts,
compared with a usual table. The average table comes from the agent's own games in the simulator.
Yes/no facts that are "no" here (a shell you don't know, cuffs not on) go into "the rest".

Also: the spread of neighbouring networks for the error bars, and what an adrenaline would steal.
"""
from __future__ import annotations

import re

import numpy as np
import torch

from games.buckshot_roulette.dqn import ACTION_INDEX, DQNAgent
from games.buckshot_roulette.sim import ADRENALINE, ITEM_CAPS, STEAL, USE

STEPS = 64
SHOW = 0.01        # reasons smaller than this are left out
ITEM_RU = {"handcuffs": "наручники", "beer": "пиво", "magnifying glass": "лупа", "cigarettes": "сигареты",
           "handsaw": "пила", "expired medicine": "лекарство", "inverter": "инвертор", "burner phone": "телефон",
           "adrenaline": "адреналин"}
SHELL_RU = {"live": "боевой", "blank": "холостой"}
# the game phase is the same for every move of a turn: it goes into the base, not into the reasons
BASE_FEATURES = {"phase: turn", "phase: steal", "phase: double", "max hp"}


def _label(name: str, value: float) -> tuple[str, str] | None:
    """(group, what) for one input number of the network, as a player would say it."""
    n = round(float(value), 2)
    special = {"saw on": ("СТОЛ", "пила надета"), "dealer cuffed": ("СТОЛ", "дилер в наручниках"),
               "me cuffed": ("СТОЛ", "ты в наручниках")}
    if name in special:
        return special[name]
    if name == "hp me":
        return "ЖИЗНИ", f"ты: {round(n * 4)}"
    if name == "hp dealer":
        return "ЖИЗНИ", f"дилер: {round(n * 4)}"
    if name == "live left":
        return "ПАТРОНЫ", f"боевых: {round(n * 8)}"
    if name == "blank left":
        return "ПАТРОНЫ", f"холостых: {round(n * 8)}"
    if name.startswith("last: "):
        what = name[6:]
        return "ПАТРОНЫ", "последний: " + ("—" if what == "none" else SHELL_RU[what])
    if name.startswith("know now: "):
        what = name[10:]
        return "ЗНАНИЕ", "в стволе: " + ("?" if what == "-" else SHELL_RU[what])
    if name == "now inverted":
        return "ЗНАНИЕ", "в стволе перевёрнут"
    m = re.match(r"know #(\d+): (\w+)", name)
    if m:
        return "ЗНАНИЕ", f"№{m[1]}: {SHELL_RU[m[2]]}"
    m = re.match(r"out #(\d+): (\w+)", name)
    if m:
        return "ИСТОРИЯ", f"вылетел №{m[1]}: {SHELL_RU[m[2]]}"
    if name.startswith("dealer used "):
        return "ИСТОРИЯ", "дилер брал: " + ITEM_RU[name[12:]]
    if name.startswith("my "):
        return "ТВОИ", f"{ITEM_RU[name[3:]]}: {round(n * ITEM_CAPS[name[3:]])}"
    if name.startswith("dealer "):
        return "У ДИЛЕРА", f"{ITEM_RU[name[7:]]}: {round(n * ITEM_CAPS[name[7:]])}"
    return None


# numbers that are amounts (shown even when 0); every other input is a yes/no fact
AMOUNTS = {"hp me", "hp dealer", "live left", "blank left"} | {f"my {i}" for i in ITEM_RU}     | {f"dealer {i}" for i in ITEM_RU}


def average_table(agent: DQNAgent, games: int = 120, seed: int = 11) -> np.ndarray:
    """The mean input over the agent's own decisions in simulated games: the "usual table"."""
    from games.buckshot_roulette.sim import BuckshotEnv
    env, xs = BuckshotEnv(seed=seed), []
    for _ in range(games):
        env.reset()
        for _ in range(400):
            legal = env.legal_actions()
            if not legal:
                break
            obs = env.observation()
            xs.append(agent.encode(obs))
            _, _, done, _ = env.step(agent.think(obs, legal).choice)
            if done:
                break
    return np.mean(xs, axis=0).astype(np.float32)


def _attributions(net, x: np.ndarray, base_x: np.ndarray, out: int) -> tuple[np.ndarray, float]:
    xt, bt = torch.from_numpy(x), torch.from_numpy(base_x)
    alphas = (torch.arange(STEPS, dtype=torch.float32)[:, None] + 0.5) / STEPS  # midpoints: a closer sum
    path = (bt + alphas * (xt - bt)).requires_grad_(True)
    net(path)[:, out].sum().backward()
    grads = path.grad.mean(dim=0).numpy()
    with torch.no_grad():
        base = float(net(bt)[out])
    return grads * (x - base_x), base


def why(agent: DQNAgent, obs: dict, action: str, base_x: np.ndarray) -> dict:
    """Reasons for one move: [group, what, coefficient], strongest first; base + reasons + rest = total."""
    x = agent.encode(obs).astype(np.float32)
    contrib, base = _attributions(agent.net, x, base_x, ACTION_INDEX[action])
    reasons, rest = [], 0.0
    for name, value, c in zip(agent.features, x, contrib):
        amount = name in AMOUNTS
        label = _label(name, value) if (amount or value != 0) and name not in BASE_FEATURES else None
        if label and abs(c) >= SHOW:
            reasons.append([label[0], label[1], round(float(c), 3)])
        else:
            rest += float(c)
    reasons.sort(key=lambda r: -abs(r[2]))
    with torch.no_grad():
        total = float(agent.net(torch.from_numpy(x))[ACTION_INDEX[action]])
    return {"reasons": reasons, "base": round(base, 3), "rest": round(rest, 3), "total": round(total, 3)}


def siblings(run: str, available: list[str]) -> list[str]:
    """Neighbouring networks for the error bars: the other seeds (…-s0/-s1/-s2) or the previous dx versions."""
    m = re.match(r"(.+)-s(\d+)$", run)
    if m:
        return [r for r in available if r != run and re.fullmatch(re.escape(m[1]) + r"-s\d+", r)]
    m = re.match(r"(dx\d+)\.(\d+)$", run)
    if m:
        return [f"{m[1]}.{int(m[2]) - k}" for k in (1, 2) if f"{m[1]}.{int(m[2]) - k}" in available]
    return []


def steal_target(agent, obs: dict) -> str | None:
    """What the agent would take with an adrenaline from this table (it decides again after using it)."""
    theirs = [i for i, n in obs.get("items_dealer", {}).items() if n > 0 and i != ADRENALINE]
    if not theirs:
        return None
    mine = dict(obs.get("items_player", {}))
    mine[ADRENALINE] = max(0, mine.get(ADRENALINE, 0) - 1)
    steal_obs = {**obs, "phase": "steal", "items_player": mine}
    return agent.think(steal_obs, [STEAL + i for i in theirs]).choice[len(STEAL):]


def is_adrenaline(action: str) -> bool:
    return action == USE + ADRENALINE

"""Deep Q-Network agent: a small neural network instead of the Q-table.

    observation ──encode()──► 50 numbers ──► 64 neurons ──► 64 neurons ──► 21 outputs (one Q per action)

The network learns Q(state, action) = the chance to win the current round (reward 1 when the round is won,
0 when the player dies), the same target as the Q-table — but similar states share what they learned.
Standard DQN parts: replay memory (learn from random past moves, not just the last one), a target network
(a slowly updated copy that gives stable targets), Double-DQN targets, and masking of illegal actions.
The encoder only scales what the agent observes; it adds no hints or hand-made features.
"""
from __future__ import annotations

import random
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
from torch import nn

from player.buckshot.sim import (
    DOUBLE_NO, DOUBLE_YES, ITEM_CAPS, ITEMS, SHOOT_DEALER, SHOOT_SELF, STEAL, USE, ADRENALINE, BLANK, LIVE,
)
from player.buckshot.thought import Thought

torch.set_num_threads(1)  # tiny network: one thread is fastest

ACTIONS = ([SHOOT_SELF, SHOOT_DEALER] + [USE + i for i in ITEMS] + [STEAL + i for i in ITEMS if i != ADRENALINE]
           + [DOUBLE_YES, DOUBLE_NO])
ACTION_INDEX = {a: i for i, a in enumerate(ACTIONS)}
LATER = range(1, 8)  # positions a burner phone can reveal


def _feature_names() -> list[str]:
    names = ["hp me", "hp dealer", "max hp", "live left", "blank left"]
    names += ["last: none", "last: live", "last: blank", "know now: -", "know now: live", "know now: blank",
              "now inverted"]
    for k in LATER:
        names += [f"know #{k + 1}: live", f"know #{k + 1}: blank"]
    names += [f"my {i}" for i in ITEMS] + [f"dealer {i}" for i in ITEMS]
    names += ["saw on", "dealer cuffed", "me cuffed", "phase: turn", "phase: steal", "phase: double"]
    return names


FEATURES = _feature_names()


def encode(obs: dict) -> np.ndarray:
    """Turn an observation into numbers in [0, 1]. Same information, just scaled."""
    v = [obs["hp_player"] / 4, obs["hp_dealer"] / 4, obs["max_hp"] / 4, obs["live_left"] / 8, obs["blank_left"] / 8]
    last = obs.get("last_shell")
    v += [last is None, last == LIVE, last == BLANK]
    now = obs.get("known_current")
    v += [now is None, now == LIVE, now == BLANK, bool(obs.get("current_inverted"))]
    later = obs.get("known_later", {})
    for k in LATER:
        v += [later.get(k) == LIVE, later.get(k) == BLANK]
    mine, theirs = obs.get("items_player", {}), obs.get("items_dealer", {})
    v += [mine.get(i, 0) / ITEM_CAPS[i] for i in ITEMS] + [theirs.get(i, 0) / ITEM_CAPS[i] for i in ITEMS]
    phase = obs["phase"]
    v += [bool(obs.get("saw")), bool(obs.get("dealer_cuffed")), bool(obs.get("player_cuffed")),
          phase == "turn", phase == "steal", phase == "double"]
    return np.asarray(v, dtype=np.float32)


def _mask(legal: list[str]) -> np.ndarray:
    m = np.zeros(len(ACTIONS), dtype=bool)
    m[[ACTION_INDEX[a] for a in legal]] = True
    return m


class QNet(nn.Module):
    def __init__(self, n_in: int = len(FEATURES), hidden: int = 64, n_out: int = len(ACTIONS)):
        super().__init__()
        self.l1 = nn.Linear(n_in, hidden)
        self.l2 = nn.Linear(hidden, hidden)
        self.out = nn.Linear(hidden, n_out)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.out(torch.relu(self.l2(torch.relu(self.l1(x)))))

    def activations(self, x: torch.Tensor) -> list[torch.Tensor]:
        """Every layer's values for one input — used to draw which neurons "light up"."""
        h1 = torch.relu(self.l1(x))
        h2 = torch.relu(self.l2(h1))
        return [x, h1, h2, self.out(h2)]


class DQNAgent:
    def __init__(self, seed: int | None = None, epsilon: float = 0.0, name: str = "dqn", hidden: int = 64,
                 lr: float = 1e-3, batch: int = 128, memory: int = 100_000, learn_every: int = 4,
                 warmup: int = 5_000, target_every: int = 2_000):
        self.rng = random.Random(seed)
        if seed is not None:
            torch.manual_seed(seed)
        self.name, self.hidden, self.epsilon, self.games_trained = name, hidden, epsilon, 0
        self.net = QNet(hidden=hidden)
        self.target = QNet(hidden=hidden)
        self.target.load_state_dict(self.net.state_dict())
        self.opt = torch.optim.Adam(self.net.parameters(), lr=lr)
        self.batch, self.learn_every, self.warmup, self.target_every = batch, learn_every, warmup, target_every
        self.memory: deque = deque(maxlen=memory)
        self.steps = 0
        self.last_loss = float("nan")

    def q_values(self, obs: dict) -> np.ndarray:
        with torch.no_grad():
            return self.net(torch.from_numpy(encode(obs))).numpy()

    def think(self, observation: dict, legal: list[str]) -> Thought:
        q = self.q_values(observation)
        values = {a: float(q[ACTION_INDEX[a]]) for a in legal}
        exploring = self.rng.random() < self.epsilon
        if exploring:
            choice = self.rng.choice(legal)
        else:
            choice = max(values, key=values.get)
        return Thought(observation=observation, legal=legal, choice=choice, values=values, exploring=exploring,
                       agent=f"{self.name}@{self.games_trained}")

    def learn(self, obs: dict, action: str, reward: float, next_obs: dict, next_legal: list[str],
              round_over: bool) -> None:
        done = round_over or not next_legal
        self.memory.append((encode(obs), ACTION_INDEX[action], reward, encode(next_obs),
                            _mask(next_legal) if not done else np.zeros(len(ACTIONS), dtype=bool), done))
        self.steps += 1
        if len(self.memory) >= self.warmup and self.steps % self.learn_every == 0:
            self._train_batch()
        if self.steps % self.target_every == 0:
            self.target.load_state_dict(self.net.state_dict())

    def _train_batch(self) -> None:
        batch = self.rng.sample(self.memory, self.batch)
        s, a, r, s2, m2, d = zip(*batch)
        s, s2 = torch.from_numpy(np.stack(s)), torch.from_numpy(np.stack(s2))
        a = torch.tensor(a)
        r = torch.tensor(r, dtype=torch.float32)
        m2 = torch.from_numpy(np.stack(m2))
        d = torch.tensor(d, dtype=torch.float32)
        q = self.net(s).gather(1, a[:, None]).squeeze(1)
        with torch.no_grad():
            # Double DQN: the online net picks the best legal next action, the target net values it.
            nq_online = self.net(s2).masked_fill(~m2, -1e9)
            best = nq_online.argmax(1, keepdim=True)
            nq = self.target(s2).gather(1, best).squeeze(1)
            target = r + (1 - d) * nq
        loss = nn.functional.smooth_l1_loss(q, target)
        self.opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.net.parameters(), 10.0)
        self.opt.step()
        self.last_loss = float(loss)

    # --- checkpoints ------------------------------------------------------------------------

    def save(self, path: Path, **meta) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"state_dict": self.net.state_dict(), "hidden": self.hidden, "name": self.name,
                    "games_trained": self.games_trained, "epsilon": self.epsilon, "actions": ACTIONS,
                    "features": FEATURES,
                    "meta": {"saved_at": datetime.now().isoformat(timespec="seconds"), **meta}}, path)

    @classmethod
    def load(cls, path: Path, seed: int | None = None) -> "DQNAgent":
        data = torch.load(path, weights_only=True)
        agent = cls(seed=seed, epsilon=0.0, name=data["name"], hidden=data["hidden"])
        agent.net.load_state_dict(data["state_dict"])
        agent.games_trained = data["games_trained"]
        return agent

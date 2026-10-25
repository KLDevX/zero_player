"""Tabular Q-learning agent.

Q[state][action] = how good the action is in that state. Here: the chance to win the current round
(reward 1 when the round is won, 0 when the player dies), learned only from playing.

Update after every move (Q-learning):
    Q[s][a] += alpha * (target - Q[s][a])
    target = reward                    if the round ended
           = reward + max_a' Q[s'][a'] otherwise (the best value of the next decision)
alpha = 1 / visits(s, a): each value is the running average of its targets.
Exploration: with probability epsilon pick a random legal move, otherwise the best known one.
"""
from __future__ import annotations

import pickle
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from core.thought import Thought

# Observation fields that make up the state. "basic": HP and shells only (v0.1). "full": everything the
# agent observes except progress counters (round number etc.), which don't change the rules.
KEY_FIELDS = ("phase", "hp_player", "hp_dealer", "live_left", "blank_left", "last_shell", "known_current")
NOT_IN_FULL_KEY = ("batch", "rounds_beat")


def _frozen(value):
    return tuple(sorted(value.items())) if isinstance(value, dict) else value


def state_key(obs: dict, mode: str = "basic") -> tuple:
    if mode == "basic":
        return tuple(obs.get(f) for f in KEY_FIELDS)
    return tuple((k, _frozen(v)) for k, v in sorted(obs.items()) if k not in NOT_IN_FULL_KEY)


class QTableAgent:
    def __init__(self, seed: int | None = None, epsilon: float = 0.0, name: str = "qtable", key: str = "basic"):
        self.q: dict[tuple, dict[str, float]] = defaultdict(dict)
        self.visits: dict[tuple, dict[str, int]] = defaultdict(dict)
        self.epsilon = epsilon
        self.games_trained = 0
        self.name = name
        self.key = key
        self.rng = random.Random(seed)

    def think(self, observation: dict, legal: list[str]) -> Thought:
        key = state_key(observation, self.key)
        values = {a: self.q[key].get(a, 0.0) for a in legal}
        exploring = self.rng.random() < self.epsilon
        if exploring:
            choice = self.rng.choice(legal)
        else:
            best = max(values.values())
            choice = self.rng.choice([a for a, v in values.items() if v == best])
        return Thought(
            observation=observation, legal=legal, choice=choice, values=values, exploring=exploring,
            agent=f"{self.name}@{self.games_trained}",
            notes={"visits": {a: self.visits[key].get(a, 0) for a in legal}},
        )

    def learn(self, obs: dict, action: str, reward: float, next_obs: dict, next_legal: list[str],
              round_over: bool) -> None:
        key = state_key(obs, self.key)
        target = reward
        if not round_over and next_legal:
            nkey = state_key(next_obs, self.key)
            target += max(self.q[nkey].get(a, 0.0) for a in next_legal)
        n = self.visits[key].get(action, 0) + 1
        self.visits[key][action] = n
        old = self.q[key].get(action, 0.0)
        self.q[key][action] = old + (target - old) / n

    # --- checkpoints ------------------------------------------------------------------------

    def save(self, path: Path, **meta) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "q": dict(self.q), "visits": dict(self.visits), "games_trained": self.games_trained,
            "epsilon": self.epsilon, "name": self.name, "key": self.key,
            "meta": {"saved_at": datetime.now().isoformat(timespec="seconds"), **meta},
        }
        with path.open("wb") as f:
            pickle.dump(data, f)

    @classmethod
    def load(cls, path: Path, seed: int | None = None) -> "QTableAgent":
        # Only load checkpoints we wrote ourselves: pickle runs code from the file.
        with path.open("rb") as f:
            data = pickle.load(f)
        agent = cls(seed=seed, epsilon=0.0, name=data["name"], key=data.get("key", "basic"))
        agent.q.update(data["q"])
        agent.visits.update(data["visits"])
        agent.games_trained = data["games_trained"]
        return agent

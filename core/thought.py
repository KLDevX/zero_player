"""What an agent "thinks" about one decision — the single source for the overlay and for game reports.

Every agent implements `think(observation, legal) -> Thought`. Training, the hint mode and the play mode
all call the same method, so what the overlay shows is exactly what the agent used to decide.
See docs/overlay-design.md.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field


@dataclass
class Thought:
    observation: dict                   # what the agent saw (public info + its own knowledge only)
    legal: list[str]                    # actions it could take
    choice: str                         # what it picks
    values: dict[str, float] | None = None  # its learned value per action (Q), None if it has none
    exploring: bool = False             # the choice was a random exploration move (ε), not its best guess
    agent: str = ""                     # which agent / checkpoint, e.g. "q@10000"
    notes: dict = field(default_factory=dict)  # anything extra the agent wants to show

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class RandomAgent:
    name = "random"

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def think(self, observation: dict, legal: list[str]) -> Thought:
        return Thought(observation=observation, legal=legal, choice=self.rng.choice(legal), agent=self.name)

"""x1 — a planner, not a learner: the benchmark for "how good can it get?".

Before each move it imagines the parts of the table it can't see — the order of the shells (consistent
with the counts and what it knows), the shells of future loads, the order of the dealer's items, what the
dealer learned with his phone — and plays every legal move out to the end of the round in each imagined
table, with a fast base player (a trained DQN) making the later moves and the dealer playing by his real
rules. It picks the move that wins the round most often; that share is its value, a real chance.
Everything is built from the observation only, so it cannot peek at the real order; it can run live too.

    python -m player.buckshot.planner --games 300 --samples 16              # evaluate in the simulator
    python -m player.buckshot.replay runs/x1                                 # not supported: use --games here

This is a benchmark (CLAUDE.md: never hard-code strategy into the *learning* agent); it knows only the
rules of the world, no tactics.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import time
from pathlib import Path

import numpy as np

from player.buckshot.dqn import ACTION_INDEX, DQNAgent
from player.buckshot.sim import (
    BLANK, DOUBLE_YES, ITEM_CAPS, ITEMS, LIVE, PHONE, ROUND_SLOTS, BuckshotEnv, Slot, State,
)
from player.buckshot.thought import Thought

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = ROOT / "runs" / "d3.1" / "dqn_100000.pt"


class FastPolicy:
    """The base player for the rollouts: a trained DQN evaluated with numpy (much faster for one table)."""

    def __init__(self, path: Path):
        agent = DQNAgent.load(path)
        self.encode = agent.encode
        sd = {k: v.numpy() for k, v in agent.net.state_dict().items()}
        self.w1, self.b1 = sd["l1.weight"].T, sd["l1.bias"]
        self.w2, self.b2 = sd["l2.weight"].T, sd["l2.bias"]
        self.w3, self.b3 = sd["out.weight"].T, sd["out.bias"]

    def choose(self, obs: dict, legal: list[str]) -> str:
        if DOUBLE_YES in legal:
            return DOUBLE_YES
        h = np.maximum(self.encode(obs) @ self.w1 + self.b1, 0)
        h = np.maximum(h @ self.w2 + self.b2, 0)
        q = h @ self.w3 + self.b3
        return max(legal, key=lambda a: q[ACTION_INDEX[a]])


def _flip(shell: str) -> str:
    return BLANK if shell == LIVE else LIVE


def imagine(obs: dict, rng: random.Random) -> BuckshotEnv:
    """A full simulator table consistent with the observation; the hidden parts are sampled."""
    env = BuckshotEnv(seed=rng.random(), items=True)
    s = State()
    s.batch, s.rounds_beat, s.max_hp = obs["batch"], obs["rounds_beat"], obs["max_hp"]
    s.hp_player, s.hp_dealer = obs["hp_player"], obs["hp_dealer"]
    s.live_left, s.blank_left = obs["live_left"], obs["blank_left"]
    s.last_shell, s.current_inverted = obs.get("last_shell"), bool(obs.get("current_inverted"))
    s.saw, s.dealer_cuffed, s.player_cuffed = bool(obs.get("saw")), bool(obs.get("dealer_cuffed")), bool(obs.get("player_cuffed"))
    s.fired, s.dealer_used = list(obs.get("fired", [])), dict(obs.get("dealer_used", {}))
    s.stealing = obs["phase"] == "steal"
    # items: counts are public, the draw order isn't
    s.items_player = [i for i in ITEMS for _ in range(obs.get("items_player", {}).get(i, 0))]
    s.items_dealer = [i for i in ITEMS for _ in range(obs.get("items_dealer", {}).get(i, 0))]
    rng.shuffle(s.items_player)
    rng.shuffle(s.items_dealer)
    # shells: fix what the player knows, deal the rest of the original colours at random
    n = s.live_left + s.blank_left
    knows: list[str | None] = [None] * n
    if n:
        knows[0] = obs.get("known_current")
    for k, v in obs.get("known_later", {}).items():
        if int(k) < n:
            knows[int(k)] = v
    original: list[str | None] = [None] * n
    for i, k in enumerate(knows):
        if k is not None:
            original[i] = _flip(k) if (i == 0 and s.current_inverted) else k
    pool = [LIVE] * (s.live_left - original.count(LIVE)) + [BLANK] * (s.blank_left - original.count(BLANK))
    rng.shuffle(pool)
    for i in range(n):
        if original[i] is None:
            original[i] = pool.pop() if pool else LIVE
    seq = list(original)
    if n and s.current_inverted:
        seq[0] = _flip(seq[0])
    s.sequence, s.player_knows = seq, knows
    # the dealer's phone memory: one random later shell per phone he used this load
    s.dealer_knows = [False] * n
    for _ in range(s.dealer_used.get(PHONE, 0)):
        if n > 1:
            s.dealer_knows[rng.randint(1, n - 1)] = True
    # future loads of this round are unknown: fresh random slots
    s.slots = []
    for _ in range(ROUND_SLOTS):
        total = rng.randint(2, 8)
        live = max(1, total // 2)
        s.slots.append(Slot(hp=s.max_hp, live=live, blank=total - live, items=rng.randint(2, 5)))
    s.loads_in_batch = 1
    env.s, env.done = s, False
    return env


class PlannerAgent:
    def __init__(self, base: Path = DEFAULT_BASE, samples: int = 16, seed: int = 0, max_steps: int = 300):
        self.base = FastPolicy(base)
        self.base_name = f"{base.parent.name}@{base.stem.split('_')[-1]}"
        self.samples, self.max_steps = samples, max_steps
        self.rng = random.Random(seed)
        self.name, self.games_trained = f"x1({samples})", 0

    def _rollout(self, env: BuckshotEnv, first: str) -> int:
        start = env.s.rounds_beat
        env.step(first)
        steps = 0
        while not env.done and env.s.rounds_beat == start and steps < self.max_steps:
            env.step(self.base.choose(env.observation(), env.legal_actions()))
            steps += 1
        return int(env.s.rounds_beat > start)

    def think(self, observation: dict, legal: list[str]) -> Thought:
        if DOUBLE_YES in legal or len(legal) == 1:
            choice = DOUBLE_YES if DOUBLE_YES in legal else legal[0]
            return Thought(observation=observation, legal=legal, choice=choice, agent=self.name)
        wins = dict.fromkeys(legal, 0)
        for _ in range(self.samples):
            world = imagine(observation, self.rng)
            seed = self.rng.random()  # the same luck for every move in this imagined table
            for a in legal:
                e = copy.deepcopy(world)
                e.rng = random.Random(seed)
                wins[a] += self._rollout(e, a)
        values = {a: w / self.samples for a, w in wins.items()}
        best = max(values.values())
        tied = [a for a in legal if values[a] == best]
        # ties: let the base player break them (it has an opinion about equally good moves)
        choice = tied[0] if len(tied) == 1 else self.base.choose(observation, tied)
        return Thought(observation=observation, legal=legal, choice=choice, values=values, agent=self.name,
                       notes={"samples": self.samples, "base": self.base_name})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--base", type=Path, default=DEFAULT_BASE)
    ap.add_argument("--seed", type=int, default=7, help="simulator seed (7 = the replays' seed)")
    args = ap.parse_args()
    agent = PlannerAgent(args.base, args.samples, seed=1)
    env = BuckshotEnv(seed=args.seed)
    rounds, decisions, t0 = [], 0, time.perf_counter()
    for g in range(1, args.games + 1):
        obs = env.reset()
        while not env.done:
            obs, *_ = env.step(agent.think(obs, env.legal_actions()).choice)
            decisions += 1
        rounds.append(env.s.rounds_beat)
        if g % max(1, args.games // 10) == 0:
            print(f"game {g}: mean rounds {sum(rounds) / len(rounds):.2f}, "
                  f"{(time.perf_counter() - t0) / decisions * 1000:.0f} ms per move", flush=True)
    won, n = sum(rounds), len(rounds)
    result = {"agent": agent.name, "base": agent.base_name, "games": n, "seed": args.seed,
              "rounds_per_game": won / n, "round_win_rate": won / (won + n), "best_game": max(rounds),
              "seconds": round(time.perf_counter() - t0, 1)}
    out = ROOT / "reports" / f"x1_s{args.samples}_{agent.base_name}_{n}games.json"
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()

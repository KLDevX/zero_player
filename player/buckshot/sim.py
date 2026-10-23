"""Buckshot Roulette simulator — Double or Nothing (endless), version 1: no items yet.

Holds the rules of the world only (ported from the game's scripts, see docs/feasibility.md §3–§5 and
docs/sim-rules.md); the agent learns the strategy itself. The agent sees only `observation()`: public
counts and its own knowledge — never the hidden shell order, never what the dealer knows.

    env = BuckshotEnv(seed=1)
    obs = env.reset()
    while not env.done:
        obs, reward, done, info = env.step(random.choice(env.legal_actions()))

Run `python -m player.buckshot.sim` for a quick random-vs-dealer check.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

LIVE, BLANK = "live", "blank"
SHOOT_SELF, SHOOT_DEALER = "shoot_self", "shoot_dealer"
DOUBLE_YES, DOUBLE_NO = "double_yes", "double_no"
BATCHES_PER_CYCLE = 3  # RoundManager.gd:488 — after batch index 3 the prize and the double-or-nothing choice
# Shell order quirk (RoundManager.gd:156-157, ShellSpawner.gd:118): a load is shuffled only if its round slot
# has `shufflingArray` set, and the coin flip only ever sets it to true. Unshuffled loads come out
# "all lives, then all blanks". Logs: 28 of 75 two-colour loads were sorted vs ≈12 expected by chance.
# Slot count and the initial flag value come from scene data we can't read yet → estimates.
ROUND_SLOTS = 5
MAX_ROUNDS = 1000  # safety cap on rounds per game


@dataclass
class Load:
    live: int
    blank: int
    sequence: list[str]


@dataclass
class State:
    batch: int = 0                 # 0..2 inside a cycle (playerData.currentBatchIndex)
    rounds_beat: int = 0           # batches won in this game (the main progress metric)
    cycles_beat: int = 0           # full 3-batch cycles (double_or_nothing_rounds_beat)
    max_hp: int = 0
    hp_player: int = 0
    hp_dealer: int = 0
    loads_in_batch: int = 0
    sequence: list[str] = field(default_factory=list)   # hidden
    live_left: int = 0             # public: loaded counts minus shells seen leaving the gun
    blank_left: int = 0
    last_shell: str | None = None  # public: the shell that just left the gun in this load (everyone sees it)
    player_knows: list[str | None] = field(default_factory=list)  # the agent's own knowledge per shell
    dealer_knows: list[bool] = field(default_factory=list)        # hidden from the agent
    awaiting_double: bool = False


class BuckshotEnv:
    def __init__(self, seed: int | None = None, persistent_shuffle_flags: bool = True):
        self.rng = random.Random(seed)
        # True: slot flags survive between games, like resources in one running game process.
        self.persistent_shuffle_flags = persistent_shuffle_flags
        self.shuffle_flags = [False] * ROUND_SLOTS
        self.s = State()
        self.done = True
        self.events: list[str] = []

    # --- public interface -----------------------------------------------------------------

    def reset(self) -> dict:
        if not self.persistent_shuffle_flags:
            self.shuffle_flags = [False] * ROUND_SLOTS
        self.s = State()
        self.done = False
        self.events = []
        self._start_batch()
        return self.observation()

    def legal_actions(self) -> list[str]:
        if self.done:
            return []
        if self.s.awaiting_double:
            return [DOUBLE_YES, DOUBLE_NO]
        return [SHOOT_SELF, SHOOT_DEALER]

    def observation(self) -> dict:
        """What the player can know. Nothing hidden, nothing the dealer learned."""
        s = self.s
        return {
            "phase": "double" if s.awaiting_double else "turn",
            "batch": s.batch,
            "rounds_beat": s.rounds_beat,
            "max_hp": s.max_hp,
            "hp_player": s.hp_player,
            "hp_dealer": s.hp_dealer,
            "live_left": s.live_left,
            "blank_left": s.blank_left,
            "last_shell": s.last_shell,
            "known_current": s.player_knows[0] if s.player_knows else None,
        }

    def step(self, action: str) -> tuple[dict, float, bool, dict]:
        """One player decision; dealer turns and reloads are played out until the player decides again."""
        if action not in self.legal_actions():
            raise ValueError(f"illegal action {action!r}; legal: {self.legal_actions()}")
        self.events = []
        rounds_before = self.s.rounds_beat
        if action == DOUBLE_NO:
            self._log("player takes the prize")
            self.done = True
        elif action == DOUBLE_YES:
            self.s.awaiting_double = False
            self._log("double or nothing: continue")
            self._start_batch()
        else:
            again = self._shoot("player", "self" if action == SHOOT_SELF else "dealer")
            self._advance(player_goes_again=again)
        reward = float(self.s.rounds_beat - rounds_before)
        info = {"events": self.events, "rounds_beat": self.s.rounds_beat, "cycles_beat": self.s.cycles_beat}
        return self.observation(), reward, self.done, info

    # --- rules ------------------------------------------------------------------------------

    def _start_batch(self) -> None:
        """MainBatchSetup + GenerateRandomBatches (RoundManager.gd:87-157): fresh HP, then the first load."""
        s = self.s
        s.max_hp = self.rng.randint(2, 4)
        s.hp_player = s.hp_dealer = s.max_hp
        s.loads_in_batch = 0
        for i in range(ROUND_SLOTS):  # every batch regenerates every slot; the flip only sets True
            if self.rng.randint(0, 1) == 1:
                self.shuffle_flags[i] = True
        self._log(f"round {s.rounds_beat + 1} starts, HP {s.max_hp}")
        self._load()

    def _load(self) -> None:
        """New shells (RoundManager.gd:148-150, ShellSpawner.gd:104-123). The player always moves first."""
        s = self.s
        total = self.rng.randint(2, 8)
        live = max(1, total // 2)
        blank = total - live
        seq = [LIVE] * live + [BLANK] * blank
        if self.shuffle_flags[min(s.loads_in_batch, ROUND_SLOTS - 1)]:
            self.rng.shuffle(seq)
        s.loads_in_batch += 1
        s.sequence = seq
        s.live_left, s.blank_left = live, blank
        s.last_shell = None
        s.player_knows = [None] * total
        s.dealer_knows = [False] * total
        self._log(f"load: {live} live, {blank} blank")

    def _shoot(self, shooter: str, target: str) -> bool:
        """Fire the chambered shell. Returns True if the shooter goes again (blank at self)."""
        s = self.s
        shell = s.sequence.pop(0)
        s.player_knows.pop(0)
        s.dealer_knows.pop(0)
        if shell == LIVE:
            s.live_left -= 1
        else:
            s.blank_left -= 1
        s.last_shell = shell
        victim = shooter if target == "self" else ("dealer" if shooter == "player" else "player")
        self._log(f"{shooter} shoots {'self' if target == 'self' else victim}: {shell}")
        if shell == LIVE:
            if victim == "player":
                s.hp_player = max(0, s.hp_player - 1)
            else:
                s.hp_dealer = max(0, s.hp_dealer - 1)
            return False
        return target == "self"

    def _advance(self, player_goes_again: bool) -> None:
        """Resolve deaths, reloads and dealer turns until the player has to decide (or the game ends)."""
        s = self.s
        turn = "player" if player_goes_again else "dealer"
        while True:
            if s.hp_player == 0:
                self._log("player dies")
                self.done = True
                return
            if s.hp_dealer == 0:
                self._win_batch()
                return
            if not s.sequence:
                self._load()
                turn = "player"
            if turn == "player":
                return
            target = self._dealer_choice()
            again = self._shoot("dealer", target)
            turn = "dealer" if again else "player"

    def _dealer_choice(self) -> str:
        """DealerIntelligence.gd without items: know the shell -> act on it, else majority colour."""
        s = self.s
        live = s.sequence.count(LIVE)  # the dealer counts the real shells (DealerIntelligence.gd:285-292)
        blank = len(s.sequence) - live
        known = None
        if s.dealer_knows[0] or len(s.sequence) == 1 or live == 0 or blank == 0:
            known = s.sequence[0]
        else:
            mem_live = sum(1 for i, k in enumerate(s.dealer_knows) if k and s.sequence[i] == LIVE)
            mem_blank = sum(1 for i, k in enumerate(s.dealer_knows) if k and s.sequence[i] == BLANK)
            if live - mem_live == 0 or blank - mem_blank == 0:
                known = s.sequence[0]  # FigureOutShell: the rest is fully determined
        if known is not None:
            return "self" if known == BLANK else "player"
        if live > blank:  # CoinFlip in endless (DealerIntelligence.gd:421-431)
            return "player"
        if live < blank:
            return "self"
        return "self" if self.rng.randint(0, 1) == 0 else "player"

    def _win_batch(self) -> None:
        s = self.s
        s.rounds_beat += 1
        s.batch += 1
        self._log(f"dealer dies, rounds beat {s.rounds_beat}")
        if s.rounds_beat >= MAX_ROUNDS:
            self.done = True
            return
        if s.batch == BATCHES_PER_CYCLE:
            s.batch = 0
            s.cycles_beat += 1
            s.awaiting_double = True
            self._log(f"cycle {s.cycles_beat} beaten: double or nothing?")
            return
        self._start_batch()

    def _log(self, text: str) -> None:
        self.events.append(text)


def _demo(games: int = 2000, seed: int = 0) -> None:
    import time
    from collections import Counter

    rng = random.Random(seed)
    env = BuckshotEnv(seed=seed)
    survived = Counter()
    t0 = time.perf_counter()
    decisions = 0
    for _ in range(games):
        env.reset()
        while not env.done:
            legal = env.legal_actions()
            action = DOUBLE_YES if DOUBLE_YES in legal else rng.choice(legal)
            env.step(action)
            decisions += 1
        survived[env.s.rounds_beat] += 1
    dt = time.perf_counter() - t0
    print(f"{games} random games vs the dealer in {dt:.2f} s ({games / dt:.0f} games/s, {decisions} decisions)")
    print("rounds survived:", ", ".join(f"{k}: {v}" for k, v in sorted(survived.items())))
    mean = sum(k * v for k, v in survived.items()) / games
    print(f"mean rounds survived {mean:.2f}, best {max(survived)}")


if __name__ == "__main__":
    _demo()

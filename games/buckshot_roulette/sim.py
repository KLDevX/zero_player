"""Buckshot Roulette simulator — Double or Nothing (endless).

v2: items for both sides (draw, caps, all 9 effects, adrenaline steal) and the dealer's item logic.
`items=False` gives the v1 rules (no items) for comparing old agents.

Holds the rules of the world only (ported from the game's scripts and scene data, see docs/sim-rules.md);
the agent learns the strategy itself. The agent sees only `observation()`: public info and its own
knowledge — never the hidden shell order, never what the dealer knows.

    env = BuckshotEnv(seed=1)
    obs = env.reset()
    while not env.done:
        obs, reward, done, info = env.step(random.choice(env.legal_actions()))

Run `python -m games.buckshot_roulette.sim` for a quick random-vs-dealer check.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

LIVE, BLANK = "live", "blank"
SHOOT_SELF, SHOOT_DEALER = "shoot_self", "shoot_dealer"
DOUBLE_YES, DOUBLE_NO = "double_yes", "double_no"
USE, STEAL = "use:", "steal:"
HANDCUFFS, BEER, MAGNIFIER, CIGARETTES, HANDSAW = "handcuffs", "beer", "magnifying glass", "cigarettes", "handsaw"
MEDICINE, INVERTER, PHONE, ADRENALINE = "expired medicine", "inverter", "burner phone", "adrenaline"
# How many of each item one side may hold in Double or Nothing (`amount_don`, main.scn AmountResources).
ITEM_CAPS = {HANDCUFFS: 1, BEER: 2, MAGNIFIER: 3, CIGARETTES: 1, HANDSAW: 3, MEDICINE: 1, INVERTER: 8, PHONE: 1,
             ADRENALINE: 2}
ITEMS = tuple(ITEM_CAPS)
GRID = 8                # item slots per side (ItemManager.gd: numberOfOccupiedGrids != 8)
BATCHES_PER_CYCLE = 3   # RoundManager.gd:488 — after batch index 3 the prize and the double-or-nothing choice
ROUND_SLOTS = 5         # round configs per batch (main.scn); loads after the 5th reuse the last one
MAX_ROUNDS = 1000       # safety cap on rounds per game


def _flip(shell: str) -> str:
    return BLANK if shell == LIVE else LIVE


@dataclass
class Slot:
    hp: int
    live: int
    blank: int
    items: int


@dataclass
class State:
    batch: int = 0                 # 0..2 inside a cycle (playerData.currentBatchIndex)
    rounds_beat: int = 0           # batches won in this game (the main progress metric)
    cycles_beat: int = 0           # full 3-batch cycles (double_or_nothing_rounds_beat)
    slots: list[Slot] = field(default_factory=list)
    max_hp: int = 0
    hp_player: int = 0
    hp_dealer: int = 0
    loads_in_batch: int = 0
    sequence: list[str] = field(default_factory=list)   # hidden: real shells, [0] is chambered
    current_inverted: bool = False  # public: the chambered shell was flipped an odd number of times
    live_left: int = 0             # public: original colours of the shells still in the gun
    blank_left: int = 0
    last_shell: str | None = None  # public: the shell that just left the gun in this load
    player_knows: list[str | None] = field(default_factory=list)  # the agent's own knowledge per shell
    dealer_knows: list[bool] = field(default_factory=list)        # hidden from the agent
    # Items in the order they were drawn: the dealer takes the first one a rule wants (DealerIntelligence.gd:144-201).
    items_player: list[str] = field(default_factory=list)
    items_dealer: list[str] = field(default_factory=list)
    saw: bool = False
    dealer_cuffed: bool = False
    dealer_breaks_free: bool = False  # cuffed dealer already skipped one turn
    player_cuffed: bool = False
    player_breaks_free: bool = False
    stealing: bool = False
    awaiting_double: bool = False
    hp_lost: int = 0               # for reward experiments: player HP lost in this game,
    dealer_hit: int = 0            # dealer HP lost to shots,
    hp_healed: int = 0             # player HP really gained (cigarettes, medicine; capped at max)
    round_end_hp: tuple = ()       # (player, dealer) HP at the moment the last round ended
    step_new_info: int = 0         # this step: shells the player learned that it couldn't know before
    step_wasted: int = 0           # this step: items used with no effect
    fired: list = field(default_factory=list)       # public: shells that left the gun this load, in order
    dealer_used: dict = field(default_factory=dict)  # public: items the dealer used this load


class BuckshotEnv:
    def __init__(self, seed: int | None = None, items: bool = True):
        self.rng = random.Random(seed)
        self.items = items
        self.s = State()
        self.done = True
        self.events: list[str] = []

    # --- public interface -----------------------------------------------------------------

    def reset(self) -> dict:
        self.s = State()
        self.done = False
        self.events = []
        self._start_batch(clear_items=True)
        return self.observation()

    def legal_actions(self) -> list[str]:
        s = self.s
        if self.done:
            return []
        if s.awaiting_double:
            return [DOUBLE_YES, DOUBLE_NO]
        if s.stealing:
            return [STEAL + i for i in ITEMS if i in s.items_dealer and i != ADRENALINE and self._valid(i)]
        acts = [SHOOT_SELF, SHOOT_DEALER]
        acts += [USE + i for i in ITEMS if i in s.items_player and self._valid(i)]
        return acts

    def observation(self) -> dict:
        """What the player can know. Nothing hidden, nothing the dealer learned."""
        s = self.s
        phase = "double" if s.awaiting_double else ("steal" if s.stealing else "turn")
        obs = {
            "phase": phase,
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
        if self.items:
            obs.update({
                "current_inverted": s.current_inverted,
                "known_later": {i: k for i, k in enumerate(s.player_knows) if i > 0 and k is not None},
                "items_player": {i: s.items_player.count(i) for i in ITEMS if i in s.items_player},
                "items_dealer": {i: s.items_dealer.count(i) for i in ITEMS if i in s.items_dealer},
                "saw": s.saw,
                "dealer_cuffed": s.dealer_cuffed,
                "player_cuffed": s.player_cuffed,
                "fired": list(s.fired),
                "dealer_used": dict(s.dealer_used),
            })
        return obs

    def step(self, action: str) -> tuple[dict, float, bool, dict]:
        """One player decision; dealer turns and reloads are played out until the player decides again."""
        if action not in self.legal_actions():
            raise ValueError(f"illegal action {action!r}; legal: {self.legal_actions()}")
        s = self.s
        self.events = []
        rounds_before, lost_before, hit_before, healed_before = s.rounds_beat, s.hp_lost, s.dealer_hit, s.hp_healed
        hp_before = (s.hp_player, s.hp_dealer)
        s.step_new_info = s.step_wasted = 0
        if action == DOUBLE_NO:
            self._log("player takes the prize")
            self.done = True
        elif action == DOUBLE_YES:
            s.awaiting_double = False
            self._log("double or nothing: continue")
            # The last batch of a cycle returns early, so the items stay (RoundManager.gd:488-497, 466-471).
            self._start_batch(clear_items=False)
        elif action.startswith(STEAL):
            item = action[len(STEAL):]
            s.stealing = False
            s.items_dealer.remove(item)
            self._log(f"player steals {item}")
            self._use_item("player", item)
        elif action.startswith(USE):
            item = action[len(USE):]
            s.items_player.remove(item)
            self._use_item("player", item)
        else:
            again = self._shoot("player", "self" if action == SHOOT_SELF else "dealer")
            self._end_turn(player_goes_again=again)
        reward = float(s.rounds_beat - rounds_before)
        # HP change of both sides inside the round this step (a new round resets HP; use the HP it ended with)
        hp_after = s.round_end_hp if (reward > 0 or self.done) and s.round_end_hp else (s.hp_player, s.hp_dealer)
        info = {"events": self.events, "rounds_beat": s.rounds_beat, "cycles_beat": s.cycles_beat,
                "hp_lost": s.hp_lost - lost_before, "dealer_hit": s.dealer_hit - hit_before,
                "hp_healed": s.hp_healed - healed_before,
                "d_hp_player": hp_after[0] - hp_before[0], "d_hp_dealer": hp_after[1] - hp_before[1],
                "died": self.done and action != DOUBLE_NO and s.hp_player == 0,
                "new_info": s.step_new_info, "wasted": s.step_wasted}
        return self.observation(), reward, self.done, info

    # --- rules: rounds and loads ----------------------------------------------------------

    def _start_batch(self, clear_items: bool) -> None:
        """MainBatchSetup + GenerateRandomBatches (RoundManager.gd:87-157): 5 random slots, HP from slot 0."""
        s = self.s
        s.slots = []
        for _ in range(ROUND_SLOTS):
            total = self.rng.randint(2, 8)
            live = max(1, total // 2)
            s.slots.append(Slot(hp=self.rng.randint(2, 4), live=live, blank=total - live,
                                items=self.rng.randint(2, 5)))
        s.max_hp = s.slots[0].hp
        s.hp_player = s.hp_dealer = s.max_hp
        s.loads_in_batch = 0
        s.saw = False
        if clear_items:
            s.items_player = []
            s.items_dealer = []
        self._log(f"round {s.rounds_beat + 1} starts, HP {s.max_hp}")
        self._load()

    def _load(self) -> None:
        """StartRound: cuffs off, items drawn, shells loaded (ShellSpawner.gd:32-93). The player moves first."""
        s = self.s
        slot_index = min(s.loads_in_batch, ROUND_SLOTS - 1)
        slot = s.slots[slot_index]
        s.loads_in_batch += 1
        s.dealer_cuffed = s.dealer_breaks_free = False  # HandcuffManager.RemoveAllCuffsRoutine
        s.player_cuffed = s.player_breaks_free = False
        if self.items:
            no_saw = slot_index == 0 and s.slots[0].hp == 2  # ItemManager.gd:238-239, 356-357
            self._draw_items(s.items_player, slot.items, no_saw)
            self._draw_items(s.items_dealer, slot.items, no_saw)
        seq = [LIVE] * slot.live + [BLANK] * slot.blank
        self.rng.shuffle(seq)  # insertingInRandomOrder is set on every slot (main.scn) → ShellSpawner.gd:89-91
        s.sequence = seq
        s.live_left, s.blank_left = slot.live, slot.blank
        s.current_inverted = False
        s.last_shell = None
        s.fired = []
        s.dealer_used = {}
        s.player_knows = [None] * len(seq)
        s.dealer_knows = [False] * len(seq)
        self._log(f"load: {slot.live} live, {slot.blank} blank")

    def _draw_items(self, hand: list[str], count: int, no_saw: bool) -> None:
        """ItemManager.GrabItem / GrabItems_Enemy: uniform among items below their cap, 8 slots max."""
        for _ in range(count):
            if len(hand) >= GRID:
                return
            pool = [i for i in ITEMS if hand.count(i) < ITEM_CAPS[i] and not (no_saw and i == HANDSAW)]
            hand.append(self.rng.choice(pool))

    # --- rules: shots and turns -----------------------------------------------------------

    def _leave_gun(self) -> str:
        """The chambered shell leaves the gun (shot or beer). Everyone sees its colour."""
        s = self.s
        shell = s.sequence.pop(0)
        original = _flip(shell) if s.current_inverted else shell
        if original == LIVE:
            s.live_left -= 1
        else:
            s.blank_left -= 1
        s.current_inverted = False
        s.last_shell = shell
        s.fired.append(shell)
        s.player_knows.pop(0)
        s.dealer_knows.pop(0)
        return shell

    def _shoot(self, shooter: str, target: str) -> bool:
        """Fire the chambered shell. Returns True if the shooter goes again (blank at self)."""
        s = self.s
        shell = self._leave_gun()
        damage = 2 if s.saw else 1
        s.saw = False  # SegmentManager.GrowBarrel after every shot (RoundManager.gd:269-273)
        victim = shooter if target == "self" else ("dealer" if shooter == "player" else "player")
        self._log(f"{shooter} shoots {'self' if target == 'self' else victim}: {shell}")
        if shell == LIVE:
            if victim == "player":
                s.hp_lost += min(damage, s.hp_player)
                s.hp_player = max(0, s.hp_player - damage)
            else:
                s.dealer_hit += min(damage, s.hp_dealer)
                s.hp_dealer = max(0, s.hp_dealer - damage)
            return False
        return target == "self"

    def _end_turn(self, player_goes_again: bool) -> None:
        """RoundManager.EndTurn and everything after it until the player decides again (or the game ends)."""
        s = self.s
        turn = "player" if player_goes_again else "dealer"
        while True:
            if s.hp_player == 0:
                self._log("player dies")
                s.round_end_hp = (s.hp_player, s.hp_dealer)
                self.done = True
                return
            if s.hp_dealer == 0:
                self._win_batch()
                return
            if not s.sequence:
                self._load()
                turn = "player"
            if turn == "player":
                if s.player_cuffed:  # BeginPlayerTurn: skip one turn, break free on the next
                    if not s.player_breaks_free:
                        s.player_breaks_free = True
                        self._log("player is cuffed, skips the turn")
                        turn = "dealer"
                        continue
                    s.player_cuffed = s.player_breaks_free = False
                    self._log("player breaks free")
                return
            if s.dealer_cuffed:  # DealerIntelligence.DealerCheckHandCuffs
                if not s.dealer_breaks_free:
                    s.dealer_breaks_free = True
                    self._log("dealer is cuffed, skips the turn")
                    turn = "player"
                    continue
                s.dealer_cuffed = s.dealer_breaks_free = False
                self._log("dealer breaks free")
            turn = "dealer" if self._dealer_turn() else "player"

    # --- rules: items ---------------------------------------------------------------------

    def _valid(self, item: str) -> bool:
        """PermissionManager.SetStackInvalidIndicators: no second saw, no cuffs on a cuffed dealer."""
        s = self.s
        if item == HANDSAW:
            return not s.saw
        if item == HANDCUFFS:
            return not s.dealer_cuffed
        if item == ADRENALINE:
            return not s.stealing
        return True

    def _use_item(self, user: str, item: str) -> None:
        """ItemInteraction.InteractWith for the player (ItemInteraction.gd:105-185)."""
        s = self.s
        self._log(f"{user} uses {item}")
        # bookkeeping for reward experiments: items with no effect, and new knowledge
        # Cigarettes are not on this list: whether smoking at full HP is useful depends on the
        # future (e.g. a dealer with adrenaline stealing them), so the consequences teach it.
        if (item == MEDICINE and s.hp_player == s.max_hp) \
                or (item == MAGNIFIER and self._player_can_tell_current()) \
                or (item == HANDCUFFS and len(s.sequence) == 1) or (item == HANDSAW and s.hp_dealer == 1):
            s.step_wasted += 1
        elif item == MAGNIFIER:
            s.step_new_info += 1
        if item == HANDCUFFS:
            s.dealer_cuffed, s.dealer_breaks_free = True, False
        elif item == BEER:
            shell = self._leave_gun()
            self._log(f"beer ejects: {shell}")
            if not s.sequence:
                self._load()
        elif item == MAGNIFIER:
            s.player_knows[0] = s.sequence[0]
            self._log(f"magnifier: {s.sequence[0]}")
        elif item == CIGARETTES:
            s.hp_healed += min(s.max_hp, s.hp_player + 1) - s.hp_player
            s.hp_player = min(s.max_hp, s.hp_player + 1)
        elif item == HANDSAW:
            s.saw = True
        elif item == MEDICINE:  # Medicine.UseMedicine: 50% lose 1, 50% heal 2 (capped)
            if self.rng.random() < 0.5:
                s.hp_healed += min(s.max_hp, s.hp_player + 2) - s.hp_player
                s.hp_player = min(s.max_hp, s.hp_player + 2)
                self._log("medicine: +2")
            else:
                s.hp_lost += 1
                s.hp_player -= 1
                self._log("medicine: -1")
                if s.hp_player <= 0:
                    s.hp_player = 0
                    self._end_turn(player_goes_again=True)  # resolves the death
        elif item == INVERTER:
            s.sequence[0] = _flip(s.sequence[0])
            s.current_inverted = not s.current_inverted
            if s.player_knows[0] is not None:
                s.player_knows[0] = _flip(s.player_knows[0])
        elif item == PHONE:  # BurnerPhone.SendDialogue: a random later shell, index 7 is reported as 6
            n = len(s.sequence)
            if n > 1:
                k = self.rng.randint(1, n - 1)
                if k in (7, 8):
                    k -= 1
                if s.player_knows[k] is None:
                    s.step_new_info += 1
                s.player_knows[k] = s.sequence[k]
                self._log(f"phone: shell {k + 1} is {s.sequence[k]}")
            else:
                self._log("phone: how unfortunate")
        elif item == ADRENALINE:
            if any(i != ADRENALINE and self._valid(i) for i in s.items_dealer):
                s.stealing = True
            else:
                self._log("nothing to steal")

    def _player_can_tell_current(self) -> bool:
        """The player already knows the chambered shell, or can work it out from the counts and the phone."""
        s = self.s
        if s.player_knows and s.player_knows[0] is not None:
            return True
        live = s.live_left - sum(1 for k in s.player_knows[1:] if k == LIVE)
        blank = s.blank_left - sum(1 for k in s.player_knows[1:] if k == BLANK)
        return live == 0 or blank == 0

    # --- the dealer -----------------------------------------------------------------------

    def _dealer_turn(self) -> bool:
        """DealerIntelligence.BeginDealerTurn + DealerChoice (DealerIntelligence.gd:65-281): items, then a shot.

        Returns True if the dealer goes again (blank at himself). If his beer empties the gun, returns False
        and the caller reloads (the player moves first after a load)."""
        s = self.s
        using_medicine = using_saw = False
        knows, known, target = False, None, None  # dealerKnowsShell, knownShell, dealerTarget: one turn only
        while True:
            if not s.sequence:
                return False
            if not knows and self._dealer_figures_out():
                knows, known = True, s.sequence[0]
                target = "self" if known == BLANK else "player"
            if len(s.sequence) == 1:
                knows, known = True, s.sequence[0]
                target = "self" if known == BLANK else "player"
            own = s.items_dealer
            # With adrenaline in hand the dealer also considers the player's items (DealerIntelligence.gd:121-142).
            pool = own + (s.items_player if ADRENALINE in own else [])
            want = None
            n = len(s.sequence)
            for item in pool:
                if item == MAGNIFIER and not knows and n != 1:
                    want, knows, known = item, True, s.sequence[0]
                    target = "self" if known == BLANK else "player"
                    break
                if item == CIGARETTES and s.hp_dealer < s.max_hp:
                    want = item
                    break
                if item == MEDICINE and s.hp_dealer < s.max_hp and CIGARETTES not in pool and not using_medicine:
                    if s.hp_dealer != 1:
                        want, using_medicine = item, True
                        break
                if item == BEER and known != LIVE and n != 1:
                    want, knows, known = item, False, None  # the target he had stays (DealerIntelligence.gd:170-176)
                    break
                if item == HANDCUFFS and not s.player_cuffed and n != 1:
                    want = item
                    break
                if item == HANDSAW and not s.saw and known == LIVE:
                    want, using_saw = item, True
                    break
                if item == PHONE and n > 2:
                    want = item
                    break
                if item == INVERTER and knows and known == BLANK:
                    want, known, target = item, LIVE, "player"
                    break
            if want is None and not using_saw and HANDSAW in pool and not s.saw and known != BLANK:
                # DealerIntelligence.gd:205-215: coin flip — saw and shoot the player, or shoot himself
                if self._coin_flip() == 0:
                    target = "self"
                else:
                    want, target, using_saw = HANDSAW, "player", True
            if want is None:
                break
            if want in own:
                own.remove(want)
            else:  # take it from the player with adrenaline (DealerIntelligence.gd:242-257)
                own.remove(ADRENALINE)
                s.items_player.remove(want)
                self._log(f"dealer uses adrenaline and steals {want}")
            self._log(f"dealer uses {want}")
            s.dealer_used[want] = s.dealer_used.get(want, 0) + 1
            self._dealer_item_effect(want)
        if target is None:
            target = "self" if self._coin_flip() == 0 else "player"  # ChooseWhoToShootRandomly
        return self._shoot("dealer", target)

    def _dealer_item_effect(self, item: str) -> None:
        s = self.s
        if item == CIGARETTES:
            s.hp_dealer = min(s.max_hp, s.hp_dealer + 1)
        elif item == MEDICINE:  # DealerIntelligence.gd:230-235, HealthCounter.gd:126-135
            if self.rng.random() < 0.5:
                s.hp_dealer = min(s.max_hp, s.hp_dealer + 2)
                self._log("dealer medicine: +2")
            else:
                s.hp_dealer -= 1  # only taken at 2+ HP, so it can't kill him
                self._log("dealer medicine: -1")
        elif item == BEER:
            self._log(f"beer ejects: {self._leave_gun()}")
        elif item == HANDCUFFS:
            s.player_cuffed, s.player_breaks_free = True, False
        elif item == HANDSAW:
            s.saw = True
        elif item == PHONE:  # DealerIntelligence.gd:187-193
            k = self.rng.randint(1, len(s.sequence) - 1)
            if k == 8:
                k -= 1
            s.dealer_knows[k] = True
        elif item == INVERTER:
            s.sequence[0] = _flip(s.sequence[0])
            s.current_inverted = not s.current_inverted
            if s.player_knows[0] is not None:
                s.player_knows[0] = _flip(s.player_knows[0])
        # magnifier: only the dealer's knowledge for this turn (set by the caller)

    def _dealer_figures_out(self) -> bool:
        """FigureOutShell (DealerIntelligence.gd:282-303), endless mode: real counts + his phone memory."""
        s = self.s
        if s.dealer_knows[0]:
            return True
        live = s.sequence.count(LIVE)  # the dealer counts the real shells
        blank = len(s.sequence) - live
        if live == 0 or blank == 0:
            return True
        for i, k in enumerate(s.dealer_knows):
            if k:
                if s.sequence[i] == LIVE:
                    live -= 1
                else:
                    blank -= 1
        return live == 0 or blank == 0

    def _coin_flip(self) -> int:
        """CoinFlip in endless (DealerIntelligence.gd:421-431): 1 = player/saw if more live, 0 if more blank."""
        live = self.s.sequence.count(LIVE)
        blank = len(self.s.sequence) - live
        if live > blank:
            return 1
        if live < blank:
            return 0
        return self.rng.randint(0, 1)

    def _win_batch(self) -> None:
        s = self.s
        s.round_end_hp = (s.hp_player, s.hp_dealer)
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
        self._start_batch(clear_items=True)  # EndMainBatch sets newBatchHasBegun → items cleared

    def _log(self, text: str) -> None:
        self.events.append(text)


def _demo(games: int = 2000, seed: int = 0) -> None:
    import time
    from collections import Counter

    for items in (False, True):
        rng = random.Random(seed)
        env = BuckshotEnv(seed=seed, items=items)
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
        mean = sum(k * v for k, v in survived.items()) / games
        print(f"items={items}: {games} random games in {dt:.2f} s ({games / dt:.0f} games/s, {decisions} decisions), "
              f"mean rounds survived {mean:.2f}, best {max(survived)}")


if __name__ == "__main__":
    _demo()

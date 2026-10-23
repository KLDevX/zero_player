import random

from player.buckshot.sim import BLANK, ITEM_CAPS, ITEMS, LIVE, SHOOT_DEALER, SHOOT_SELF, BuckshotEnv

HIDDEN_WORDS = ("sequence", "dealer_knows")


def play_random(env: BuckshotEnv, rng: random.Random) -> None:
    env.reset()
    while not env.done:
        obs = env.observation()
        assert not any(w in key for key in obs for w in HIDDEN_WORDS)
        s = env.s
        if obs["phase"] == "turn":
            # public counts = original colours in the gun; only the chambered shell can be inverted
            original = list(s.sequence)
            if s.current_inverted:
                original[0] = BLANK if original[0] == LIVE else LIVE
            assert s.live_left == original.count(LIVE)
            assert s.blank_left == original.count(BLANK)
            assert s.live_left >= 1 or s.blank_left >= 1
            assert all(0 <= s.items_player.get(i, 0) <= ITEM_CAPS[i] for i in ITEMS)
            assert sum(s.items_player.values()) <= 8 and sum(s.items_dealer.values()) <= 8
        env.step(rng.choice(env.legal_actions()))


def test_random_games_keep_invariants():
    rng = random.Random(1)
    for items in (False, True):
        env = BuckshotEnv(seed=1, items=items)
        for _ in range(500):
            play_random(env, rng)


def test_load_sizes_follow_the_game():
    env = BuckshotEnv(seed=2)
    for _ in range(2000):
        env.reset()
        live, blank = env.s.live_left, env.s.blank_left
        total = live + blank
        assert 2 <= total <= 8 and live == max(1, total // 2) and 2 <= env.s.max_hp <= 4


def test_blank_at_self_keeps_the_turn():
    env = BuckshotEnv(seed=3)
    env.reset()
    env.s.sequence = [BLANK, LIVE, LIVE]
    env.s.live_left, env.s.blank_left = 2, 1
    env.s.player_knows = [None] * 3
    env.s.dealer_knows = [False] * 3
    _, _, _, info = env.step(SHOOT_SELF)
    assert info["events"] == ["player shoots self: blank"]


def test_dealer_shoots_player_when_lives_are_the_majority():
    env = BuckshotEnv(seed=4)
    env.reset()
    env.s.sequence = [BLANK, LIVE, LIVE, LIVE]
    env.s.live_left, env.s.blank_left = 3, 1
    env.s.player_knows = [None] * 4
    env.s.dealer_knows = [False] * 4
    env.s.hp_player = env.s.hp_dealer = 4
    _, _, _, info = env.step(SHOOT_DEALER)  # blank at the dealer → dealer's turn, 3 lives left
    assert info["events"][1] == "dealer shoots player: live"


def _set_gun(env: BuckshotEnv, seq: list[str]) -> None:
    env.s.sequence = list(seq)
    env.s.live_left, env.s.blank_left = seq.count(LIVE), seq.count(BLANK)
    env.s.current_inverted = False
    env.s.player_knows = [None] * len(seq)
    env.s.dealer_knows = [False] * len(seq)


def test_saw_doubles_damage_once():
    env = BuckshotEnv(seed=5)
    env.reset()
    env.s.hp_player = env.s.hp_dealer = env.s.max_hp = 4
    env.s.items_player = {i: 0 for i in ITEMS} | {"handsaw": 1}
    _set_gun(env, [LIVE, BLANK, BLANK, BLANK])
    env.step("use:handsaw")
    assert "use:handsaw" not in env.legal_actions()
    env.step(SHOOT_DEALER)
    assert env.s.hp_dealer == 2 and not env.s.saw


def test_handcuffs_skip_one_dealer_turn():
    env = BuckshotEnv(seed=6)
    env.reset()
    env.s.hp_player = env.s.hp_dealer = env.s.max_hp = 4
    env.s.items_player = {i: 0 for i in ITEMS} | {"handcuffs": 1}
    _set_gun(env, [BLANK, BLANK, LIVE, LIVE, LIVE])
    env.step("use:handcuffs")
    _, _, _, info = env.step(SHOOT_DEALER)  # blank; the cuffed dealer skips, the player goes again
    assert info["events"][-1] == "dealer is cuffed, skips the turn"
    _, _, _, info = env.step(SHOOT_DEALER)  # blank again; now the dealer breaks free and shoots
    assert "dealer breaks free" in info["events"]


def test_inverter_hides_the_change_from_the_counts():
    env = BuckshotEnv(seed=7)
    env.reset()
    env.s.items_player = {i: 0 for i in ITEMS} | {"inverter": 1}
    _set_gun(env, [BLANK, LIVE])
    obs, *_ = env.step("use:inverter")
    assert obs["live_left"] == 1 and obs["blank_left"] == 1 and obs["current_inverted"]
    assert env.s.sequence == [LIVE, LIVE]

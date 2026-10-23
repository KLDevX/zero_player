import random

from player.buckshot.sim import BLANK, LIVE, SHOOT_DEALER, SHOOT_SELF, BuckshotEnv

HIDDEN_WORDS = ("sequence", "dealer_knows")


def play_random(env: BuckshotEnv, rng: random.Random) -> None:
    env.reset()
    while not env.done:
        obs = env.observation()
        assert not any(w in key for key in obs for w in HIDDEN_WORDS)
        s = env.s
        if obs["phase"] == "turn":
            # public counts always match the real gun (no items yet, so nothing can change a shell)
            assert s.live_left == s.sequence.count(LIVE)
            assert s.blank_left == s.sequence.count(BLANK)
            assert s.live_left >= 1 or s.blank_left >= 1
        env.step(rng.choice(env.legal_actions()))


def test_random_games_keep_invariants():
    rng = random.Random(1)
    env = BuckshotEnv(seed=1)
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

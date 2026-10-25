import random

from games.buckshot_roulette.sim import BLANK, ITEM_CAPS, ITEMS, LIVE, SHOOT_DEALER, SHOOT_SELF, BuckshotEnv

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
            assert all(s.items_player.count(i) <= ITEM_CAPS[i] for i in ITEMS)
            assert len(s.items_player) <= 8 and len(s.items_dealer) <= 8
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
    env.s.items_player, env.s.items_dealer = [], []
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
    env.s.items_player, env.s.items_dealer = [], []
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
    env.s.items_player, env.s.items_dealer = ["handsaw"], []
    _set_gun(env, [LIVE, BLANK, BLANK, BLANK])
    env.step("use:handsaw")
    assert "use:handsaw" not in env.legal_actions()
    env.step(SHOOT_DEALER)
    assert env.s.hp_dealer == 2 and not env.s.saw


def test_handcuffs_skip_one_dealer_turn():
    env = BuckshotEnv(seed=6)
    env.reset()
    env.s.hp_player = env.s.hp_dealer = env.s.max_hp = 4
    env.s.items_player, env.s.items_dealer = ["handcuffs"], []
    _set_gun(env, [BLANK, BLANK, LIVE, LIVE, LIVE])
    env.step("use:handcuffs")
    _, _, _, info = env.step(SHOOT_DEALER)  # blank; the cuffed dealer skips, the player goes again
    assert info["events"][-1] == "dealer is cuffed, skips the turn"
    _, _, _, info = env.step(SHOOT_DEALER)  # blank again; now the dealer breaks free and shoots
    assert "dealer breaks free" in info["events"]


def test_inverter_hides_the_change_from_the_counts():
    env = BuckshotEnv(seed=7)
    env.reset()
    env.s.items_player, env.s.items_dealer = ["inverter"], []
    _set_gun(env, [BLANK, LIVE])
    obs, *_ = env.step("use:inverter")
    assert obs["live_left"] == 1 and obs["blank_left"] == 1 and obs["current_inverted"]
    assert env.s.sequence == [LIVE, LIVE]


def _dealer_setup(seed: int, seq: list[str], dealer: list[str], player: list[str], hp: int = 4) -> BuckshotEnv:
    env = BuckshotEnv(seed=seed)
    env.reset()
    env.s.hp_player = env.s.hp_dealer = env.s.max_hp = hp
    env.s.items_player, env.s.items_dealer = list(player), list(dealer)
    _set_gun(env, seq)
    return env


def test_dealer_magnifier_then_acts_on_it():
    # player's blank at the dealer passes the turn; the dealer looks, sees live, shoots the player
    env = _dealer_setup(8, [BLANK, LIVE, BLANK, BLANK], dealer=["magnifying glass"], player=[])
    _, _, _, info = env.step(SHOOT_DEALER)
    assert info["events"][1:3] == ["dealer uses magnifying glass", "dealer shoots player: live"]


def test_dealer_smokes_when_hurt_and_takes_your_item_with_adrenaline():
    env = _dealer_setup(9, [BLANK, BLANK, LIVE, LIVE, LIVE], dealer=["adrenaline", "cigarettes"], player=["magnifying glass"])
    env.s.hp_dealer = 3
    _, _, _, info = env.step(SHOOT_DEALER)
    ev = info["events"]
    assert ev[1] == "dealer uses cigarettes" and env.s.hp_dealer >= 3
    assert "dealer uses adrenaline and steals magnifying glass" in ev
    assert env.s.items_player == [] and env.s.items_dealer == []


def test_dqn_encoder_covers_every_legal_action():
    from games.buckshot_roulette.dqn import ACTION_INDEX, FEATURES, encode

    rng = random.Random(10)
    env = BuckshotEnv(seed=10)
    for _ in range(200):
        obs = env.reset()
        while not env.done:
            v = encode(obs)
            assert len(v) == len(FEATURES) and 0.0 <= v.min() and v.max() <= 1.0
            legal = env.legal_actions()
            assert all(a in ACTION_INDEX for a in legal)
            obs, *_ = env.step(rng.choice(legal))


def test_step_reports_hp_lost():
    env = _dealer_setup(11, [BLANK, LIVE, LIVE, LIVE], dealer=[], player=[], hp=4)
    _, _, _, info = env.step(SHOOT_DEALER)  # blank; the dealer sees 3 lives, shoots the player
    assert info["hp_lost"] >= 1 and env.s.hp_player == 4 - info["hp_lost"]


def test_step_reports_damage_and_healing():
    env = _dealer_setup(12, [LIVE, BLANK, BLANK], dealer=[], player=["cigarettes"], hp=4)
    env.s.hp_player = 3
    _, _, _, info = env.step("use:cigarettes")
    assert info["hp_healed"] == 1
    _, _, _, info = env.step("use:cigarettes") if "use:cigarettes" in env.legal_actions() else env.step(SHOOT_DEALER)
    assert info["dealer_hit"] == 1


def test_info_and_waste_flags():
    env = _dealer_setup(13, [LIVE, BLANK, BLANK], dealer=[], player=["magnifying glass", "magnifying glass", "cigarettes"])
    _, _, _, info = env.step("use:magnifying glass")
    assert info["new_info"] == 1 and info["wasted"] == 0
    _, _, _, info = env.step("use:magnifying glass")  # already known
    assert info["wasted"] == 1
    _, _, _, info = env.step("use:cigarettes")  # full HP: not waste (option 2), simply no HP change
    assert info["wasted"] == 0 and info["d_hp_player"] == 0


def test_hp_changes_count_both_sides():
    env = _dealer_setup(14, [BLANK, LIVE, LIVE, LIVE], dealer=["cigarettes"], player=[], hp=4)
    env.s.hp_dealer = 3
    _, _, _, info = env.step(SHOOT_DEALER)  # blank; the hurt dealer smokes, then shoots the player (3 lives left)
    assert info["d_hp_dealer"] == 1 and info["d_hp_player"] == -1


def test_dqn_n_step_returns():
    import numpy as np

    from games.buckshot_roulette.dqn import DQNAgent

    env = BuckshotEnv(seed=15)
    obs = env.reset()
    agent = DQNAgent(seed=15, obs_version=2, gamma=0.5, n_step=3, warmup=10**9)
    legal = env.legal_actions()
    agent.learn(obs, legal[0], 0.0, obs, legal, round_over=False)
    agent.learn(obs, legal[0], 1.0, obs, legal, round_over=False)
    assert len(agent.memory) == 0  # waits for 3 moves
    agent.learn(obs, legal[0], 2.0, obs, [], round_over=True)
    returns = [m[2] for m in agent.memory]
    assert np.allclose(returns, [0 + 0.5 * 1 + 0.25 * 2, 1 + 0.5 * 2, 2]) and all(m[5] for m in agent.memory)


def test_training_on_several_tables_finishes_games():
    from games.buckshot_roulette.dqn import DQNAgent
    from games.buckshot_roulette.train import table_games

    agent = DQNAgent(seed=16, obs_version=2, gamma=0.99, n_step=3, warmup=10**9)
    envs = [BuckshotEnv(seed=16 * 1000 + i) for i in range(4)]
    rounds = [r for _, r in zip(range(20), table_games(envs, agent, "v4", 20))]
    assert len(rounds) == 20 and len(agent.pending) <= 4 and len(agent.memory) > 0


def test_smoking_at_full_hp_is_never_counted_as_waste():
    for dealer in ([], ["adrenaline"]):
        env = _dealer_setup(17, [LIVE, BLANK, BLANK], dealer=dealer, player=["cigarettes"], hp=3)
        _, _, _, info = env.step("use:cigarettes")
        assert info["wasted"] == 0 and info["d_hp_player"] == 0


def test_planner_imagines_only_from_the_observation():
    from games.buckshot_roulette.planner import imagine

    a = _dealer_setup(18, [LIVE, BLANK, LIVE, BLANK], dealer=["beer"], player=["magnifying glass"])
    b = _dealer_setup(18, [BLANK, LIVE, BLANK, LIVE], dealer=["beer"], player=["magnifying glass"])
    assert a.observation() == b.observation()  # different hidden order, same view
    ia, ib = imagine(a.observation(), random.Random(3)), imagine(b.observation(), random.Random(3))
    assert ia.s.sequence == ib.s.sequence  # so the imagined tables can't depend on the real order


def test_planner_keeps_what_the_player_knows():
    from games.buckshot_roulette.planner import imagine

    env = _dealer_setup(19, [LIVE, BLANK, BLANK, LIVE, BLANK], dealer=[], player=["magnifying glass", "inverter"])
    env.step("use:magnifying glass")  # knows: live
    env.step("use:inverter")          # now a blank, and it knows that
    obs = env.observation()
    for k in range(50):
        s = imagine(obs, random.Random(k)).s
        assert s.sequence[0] == BLANK and s.current_inverted
        original = [s.sequence[0] == BLANK and LIVE or BLANK] + s.sequence[1:]
        assert original.count(LIVE) == obs["live_left"] and original.count(BLANK) == obs["blank_left"]


def test_why_adds_up_and_uses_only_the_observation():
    from games.buckshot_roulette.dqn import DQNAgent
    from games.buckshot_roulette.explain import why

    agent = DQNAgent(seed=0, obs_version=2)
    base_x = agent.encode(BuckshotEnv(seed=5).reset()) * 0.5  # any reference table
    env = _dealer_setup(20, [LIVE, BLANK, LIVE], dealer=["handsaw"], player=["magnifying glass"])
    obs = env.observation()
    w = why(agent, obs, SHOOT_DEALER, base_x)
    listed = sum(r[2] for r in w["reasons"])
    assert abs(w["base"] + listed + w["rest"] - w["total"]) < 0.01  # the reasons explain the whole value
    other = _dealer_setup(20, [BLANK, LIVE, LIVE], dealer=["handsaw"], player=["magnifying glass"])
    assert why(agent, other.observation(), SHOOT_DEALER, base_x) == w  # the hidden order changes nothing

"""The real game (lab copy) as the agent sees it: bridge state → the simulator's observation format,
bridge clicks ↔ the agent's actions.

The agent gets exactly the fields of `BuckshotEnv.observation()`; the bridge builds them from what the
player can see (docs/overlay-design.md). Hidden data from the bridge (`_hidden`) is never used here.
"""
from __future__ import annotations

import time

from player.buckshot.bridge.client import Bridge
from player.buckshot.sim import DOUBLE_NO, DOUBLE_YES, ITEMS, SHOOT_DEALER, SHOOT_SELF, STEAL, USE

# One agent action = these clicks, in order (bridge action keys).
SHOT_CLICKS = {SHOOT_SELF: ["shotgun", "text you"], SHOOT_DEALER: ["shotgun", "text dealer"]}
SETTLE_GAME_SECONDS = 0.6  # wait until the clickable set is stable, like a human reaction (feasibility §8)


def observation(public: dict, legal_keys: list[str]) -> tuple[dict | None, list[str]]:
    """Returns (observation, legal agent actions). Legal is empty when it isn't the player's decision."""
    if not public or not public.get("endless") or not public.get("load_info"):
        return None, []
    if "double yes" in legal_keys:
        phase, legal = "double", [DOUBLE_YES, DOUBLE_NO]
    elif public.get("stealing"):
        phase = "steal"
        legal = [STEAL + i for i in ITEMS if f"item:{i}:dealer" in legal_keys and i != "adrenaline"]
    else:
        phase = "turn"
        legal = []
        if "shotgun" in legal_keys:
            legal = [SHOOT_SELF, SHOOT_DEALER] + [USE + i for i in ITEMS if f"item:{i}:player" in legal_keys]
    obs = {
        "phase": phase,
        "batch": public["batch"],
        "rounds_beat": max(0, public["rounds_beat"] - 1),  # the game's counter includes the current round
        "max_hp": public["load_info"]["max_hp"],
        "hp_player": public["hp_player"],
        "hp_dealer": public["hp_dealer"],
        "live_left": public["live_left"],
        "blank_left": public["blank_left"],
        "last_shell": public["last_shell"] or None,
        "known_current": public["known_current"] or None,
        "current_inverted": public["current_inverted"],
        "known_later": {int(k): v for k, v in public.get("known_later", {}).items()},
        "items_player": public["items_player"],
        "items_dealer": public["items_dealer"],
        "saw": public["saw"],
        "dealer_cuffed": public["dealer_cuffed"],
        "player_cuffed": public["player_cuffed"],
        "fired": public.get("fired", []),
        "dealer_used": public.get("dealer_used", {}),
    }
    return obs, legal


def clicks_for(action: str) -> list[str]:
    if action in SHOT_CLICKS:
        return SHOT_CLICKS[action]
    if action.startswith(USE):
        return [f"item:{action[len(USE):]}:player"]
    if action.startswith(STEAL):
        return [f"item:{action[len(STEAL):]}:dealer"]
    return {DOUBLE_YES: ["double yes"], DOUBLE_NO: ["double no"]}[action]


class LiveGame:
    def __init__(self, bridge: Bridge, speed: float = 1.0):
        self.bridge = bridge
        self.speed = speed

    def read(self) -> tuple[dict, dict | None, list[str]]:
        st = self.bridge.state()
        obs, legal = observation(st.get("public"), st.get("legal", []))
        return st, obs, legal

    def click_when_ready(self, key: str, timeout: float = 20.0) -> bool:
        """Wait until `key` is clickable and the clickable set has been stable for a moment, then click.
        The moment is in game time: the bridge says how fast the game runs right now (×1 while choosing)."""
        prev, since, start = None, time.time(), time.time()
        while time.time() - start < timeout:
            st = self.bridge.state()
            legal = st.get("legal", [])
            scale = float(st.get("ui", {}).get("scale_now", self.speed)) or self.speed
            if legal != prev:
                prev, since = legal, time.time()
            if key in legal and time.time() - since >= SETTLE_GAME_SECONDS / scale:
                return bool(self.bridge.act(key).get("ok"))
            time.sleep(0.02)
        return False

    def perform(self, action: str) -> bool:
        return all(self.click_when_ready(k) for k in clicks_for(action))

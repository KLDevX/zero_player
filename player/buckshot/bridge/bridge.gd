extends Node
# Bridge autoload for Buckshot Roulette (stage 1, step 0, part 2): reads the game state and logs it.
# Loaded through override.cfg next to the exe of the lab copy in game_lab/ (never the Steam original).
# Writes one JSON line per state change to reports/live_<date>.jsonl.
# "public" = what a player can know; "_hidden" is for checking the bridge only, never for the agent.

const RM_PATH := "res://scripts/RoundManager.gd"
const SCAN_INTERVAL_MS := 500

var rm: Node = null
var log_file: FileAccess
var last_state := ""
var last_scan := 0


func _ready() -> void:
	# Offline: bot or test play must never reach the Steam leaderboard or achievements.
	GlobalVariables.using_steam = false
	# Developer speed keys from GlobalVariables.gd: "." = 10x, "," = 1x.
	GlobalVariables.mp_debug_keys_enabled = true
	var reports_dir: String = get_script().resource_path.get_base_dir().path_join("../../../reports").simplify_path()
	DirAccess.make_dir_recursive_absolute(reports_dir)
	var stamp := Time.get_datetime_string_from_system().replace(":", "-")
	var path := reports_dir.path_join("live_%s.jsonl" % stamp)
	log_file = FileAccess.open(path, FileAccess.WRITE)
	print("[bridge] loaded, offline mode, logging to ", path)
	_write({"event": "bridge loaded"})


func _process(_delta: float) -> void:
	if rm == null or not is_instance_valid(rm):
		rm = null
		var now := Time.get_ticks_msec()
		if now - last_scan < SCAN_INTERVAL_MS:
			return
		last_scan = now
		rm = _find_round_manager(get_tree().root)
		if rm != null:
			print("[bridge] found RoundManager at ", rm.get_path())
			_write({"event": "round manager found"})
		return
	var state := _snapshot()
	var key := JSON.stringify(state)
	if key != last_state:
		last_state = key
		_write(state)


func _find_round_manager(node: Node) -> Node:
	var script = node.get_script()
	if script != null and script.resource_path == RM_PATH:
		return node
	for child in node.get_children():
		var found := _find_round_manager(child)
		if found != null:
			return found
	return null


func _snapshot() -> Dictionary:
	var load_info := {}
	if rm.currentRound < rm.roundArray.size():
		var r = rm.roundArray[rm.currentRound]
		load_info = {"max_hp": r.startingHealth, "loaded_live": r.amountLive, "loaded_blank": r.amountBlank}
	var items_player := {}
	var items_dealer := {}
	for res in rm.amounts.array_amounts:
		if res.amount_player > 0:
			items_player[res.itemName] = res.amount_player
		if res.amount_dealer > 0:
			items_dealer[res.itemName] = res.amount_dealer
	return {
		"public": {
			"endless": rm.endless,
			"batch": rm.playerData.currentBatchIndex,
			"load": rm.currentRound,
			"load_info": load_info,
			"shells_left": rm.shellSpawner.sequenceArray.size(),
			"hp_player": rm.health_player,
			"hp_dealer": rm.health_opponent,
			"items_player": items_player,
			"items_dealer": items_dealer,
			"saw": rm.barrelSawedOff,
			"player_cuffed": rm.playerCuffed,
			"dealer_cuffed": rm.dealerCuffed,
			"player_input": rm.deskUI_shotgun.visible,
			"don_cycles_beat": rm.double_or_nothing_rounds_beat,
			"don_prize": rm.double_or_nothing_score,
			"rounds_beat": rm.brief.ending.endless_roundsbeat,
		},
		"_hidden": {
			"sequence": rm.shellSpawner.sequenceArray.duplicate(),
			"dealer_knows": rm.dealerAI.sequenceArray_knownShell.duplicate(),
		},
	}


func _write(data: Dictionary) -> void:
	data["t_ms"] = Time.get_ticks_msec()
	data["time_scale"] = Engine.time_scale
	log_file.store_line(JSON.stringify(data))
	log_file.flush()

extends Node
# Bridge autoload for Buckshot Roulette (stage 1, step 0): reads the game state, logs it, and takes
# commands from Python over localhost.
# Loaded through override.cfg next to the exe of the lab copy in game_lab/ (never the Steam original).
# Log: one JSON line per state change to reports/live_<date>.jsonl.
# "public" = what a player can know; "_hidden" is for checking the bridge only, never for the agent.
#
# Protocol (JSON lines on 127.0.0.1:PORT):
#   {"cmd": "state"}             -> {"scene", "public", "legal": [action keys]}
#   {"cmd": "act", "key": "..."} -> {"ok": true} or {"ok": false, "error": "..."}
#   {"cmd": "speed", "x": 10}    -> keeps Engine.time_scale at x (overrides the game's slow-mo)
#   {"cmd": "mute", "on": true}  -> mutes the master audio bus
# An action is one click the player could make right now, performed through the game's own
# InteractionManager.MainInteractionEvent(), the same path a mouse click takes.

const PORT := 47800
const SCAN_INTERVAL_MS := 500
const RM_PATH := "res://scripts/RoundManager.gd"
const IM_PATH := "res://scripts/InteractionManager.gd"
const CURSOR_PATH := "res://scripts/CursorManager.gd"
const MENU_PATH := "res://scripts/MenuManager.gd"
const ITEMS_PATH := "res://scripts/ItemInteraction.gd"
const TIMESCALE_PATH := "res://scripts/TimeScaleManager.gd"
const BRANCH_PATH := "res://scripts/InteractionBranch.gd"
# Clicks the bridge may make. Everything else (CRT, credits, heaven, menus) is left alone.
const ALLOWED_ALIASES := [
	"shotgun", "text you", "text dealer", "briefcase intake", "item", "double yes", "double no",
	"pill bottle", "pill choice yes", "pill choice no", "bathroom door", "backroom door",
	"release form on table", "signature machine button",
]

var rm: Node = null
var im: Node = null
var cursor: Node = null
var menu: Node = null
var item_interaction: Node = null
var timescale_managers: Array = []
var scene: Node = null
var scene_id := 0
var branches: Array = []
var branches_ms := 0
var log_file: FileAccess
var last_state := ""
var last_scan := 0
var server := TCPServer.new()
var peer: StreamPeerTCP = null
var inbox := ""
var target_scale := 1.0
var observed_scale := 1.0  # time scale the last frame really ran at (before we set ours)
var menu_started := false


func _ready() -> void:
	# Run after the game's own nodes each frame, so our time scale is the last one set.
	process_priority = 10000
	# Offline: bot or test play must never reach the Steam leaderboard or achievements.
	GlobalVariables.using_steam = false
	# Developer speed keys from GlobalVariables.gd: "." = 10x, "," = 1x.
	GlobalVariables.mp_debug_keys_enabled = true
	var reports_dir: String = get_script().resource_path.get_base_dir().path_join("../../../reports").simplify_path()
	DirAccess.make_dir_recursive_absolute(reports_dir)
	var stamp := Time.get_datetime_string_from_system().replace(":", "-")
	var path := reports_dir.path_join("live_%s.jsonl" % stamp)
	log_file = FileAccess.open(path, FileAccess.WRITE)
	var err := server.listen(PORT, "127.0.0.1")
	print("[bridge] loaded, offline mode, logging to ", path, ", listening on 127.0.0.1:", PORT, " (", err, ")")
	_write({"event": "bridge loaded"})


func _process(_delta: float) -> void:
	observed_scale = Engine.time_scale
	_serve()
	if target_scale != 1.0 and Engine.time_scale != 0.0:
		# TimeScaleManager's slow-mo after a dealer kill never clears its "moving" flag and keeps
		# setting Engine.time_scale back to 1.0 every frame (TimeScaleManager.gd:21-27).
		for tsm in timescale_managers:
			if is_instance_valid(tsm):
				tsm.moving = false
		Engine.time_scale = target_scale
	if not _scene_ok():
		_rescan()
		return
	if rm == null:
		return
	var state := {"public": _public(), "_hidden": _hidden()}
	var key := JSON.stringify(state)
	if key != last_state:
		last_state = key
		_write(state)


func _rescan() -> void:
	var now := Time.get_ticks_msec()
	if now - last_scan < SCAN_INTERVAL_MS:
		return
	last_scan = now
	scene = get_tree().current_scene
	scene_id = scene.get_instance_id() if scene != null else 0
	branches = []
	branches_ms = 0
	rm = null
	im = null
	cursor = null
	menu = null
	item_interaction = null
	timescale_managers = []
	menu_started = false
	if scene == null:
		return
	for node in scene.find_children("*", "", true, false):
		var script = node.get_script()
		if script == null:
			continue
		if script.resource_path == BRANCH_PATH:
			branches.append(node)
		match script.resource_path:
			RM_PATH: rm = node
			IM_PATH: im = node
			CURSOR_PATH: cursor = node
			MENU_PATH: menu = node
			ITEMS_PATH: item_interaction = node
			TIMESCALE_PATH: timescale_managers.append(node)
	print("[bridge] scene ", scene.name, " rm=", rm != null, " im=", im != null, " menu=", menu != null)
	_write({"event": "scene " + scene.name})


# --- commands -------------------------------------------------------------------------------

func _serve() -> void:
	if server.is_connection_available():
		peer = server.take_connection()
		inbox = ""
		print("[bridge] python connected")
	if peer == null:
		return
	peer.poll()
	if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		peer = null
		return
	var n := peer.get_available_bytes()
	if n > 0:
		inbox += peer.get_utf8_string(n)
	while inbox.find("\n") != -1:
		var cut := inbox.find("\n")
		var line := inbox.substr(0, cut)
		inbox = inbox.substr(cut + 1)
		var msg = JSON.parse_string(line)
		var reply: Dictionary = _handle(msg) if msg is Dictionary else {"ok": false, "error": "bad json"}
		peer.put_data((JSON.stringify(reply) + "\n").to_utf8_buffer())


func _handle(msg: Dictionary) -> Dictionary:
	match msg.get("cmd", ""):
		"state":
			if not _scene_ok():
				return {"ok": true, "scene": "", "legal": []}
			var reply := {"ok": true, "scene": scene.name if scene != null else "", "legal": _legal().keys()}
			if rm != null:
				reply["public"] = _public()
			return reply
		"act":
			return _act(str(msg.get("key", "")))
		"speed":
			target_scale = float(msg.get("x", 1.0))
			Engine.time_scale = target_scale
			Engine.max_physics_steps_per_frame = maxi(8, ceili(target_scale) * 2)
			return {"ok": true, "x": target_scale}
		"mute":
			AudioServer.set_bus_mute(0, bool(msg.get("on", true)))
			return {"ok": true}
	return {"ok": false, "error": "unknown cmd"}


# Returns {action key: InteractionBranch node} for every click the player could make right now.
func _legal() -> Dictionary:
	var legal := {}
	if not _scene_ok():
		return legal
	if menu != null and not menu_started:
		legal["menu start"] = null
	if scene == null or im == null or cursor == null or not cursor.cursor_visible:
		return legal
	_refresh_branches()
	var stealing: bool = item_interaction != null and item_interaction.stealing
	for node in branches:
		if not is_instance_valid(node):
			continue
		if not node.interactionAllowed or node.interactionInvalid or not _clickable(node):
			continue
		var key := _key(node)
		if key == "":
			continue
		# Adrenaline: the camera faces the dealer's items, so a player cannot click their own.
		if stealing and key.begins_with("item:") and key.ends_with(":player"):
			continue
		legal[key] = node
	return legal


func _scene_ok() -> bool:
	var cur := get_tree().current_scene
	return cur != null and scene_id != 0 and cur.get_instance_id() == scene_id


# Items are spawned at run time, so the branch list is refreshed now and then.
func _refresh_branches() -> void:
	var now := Time.get_ticks_msec()
	if now - branches_ms < 250:
		return
	branches_ms = now
	branches = []
	for node in scene.find_children("*", "", true, false):
		var script = node.get_script()
		if script != null and script.resource_path == BRANCH_PATH:
			branches.append(node)


func _key(b: Node) -> String:
	if b.isGrid:
		return "grid:%d" % b.gridIndex
	if not ALLOWED_ALIASES.has(b.interactionAlias):
		return ""
	match b.interactionAlias:
		"item":
			if b.itemName == "":
				return ""
			return "item:%s:%s" % [b.itemName, "player" if b.isPlayerSide else "dealer"]
		"signature machine button":
			return "sign:" + (b.signatureButton_letterAlias if b.signatureButton_letterAlias != "" else b.signatureButton_specialAlias)
	return b.interactionAlias


# The mouse ray hits a collider next to the branch; a click is possible only if that collider is on.
func _clickable(b: Node) -> bool:
	var parent := b.get_parent()
	if parent is Node3D and not parent.is_visible_in_tree():
		return false
	for c in parent.get_children():
		if c is CollisionObject3D:
			if c.collision_layer == 0:
				return false
			for s in c.get_children():
				if s is CollisionShape3D and s.disabled:
					return false
	return true


func _act(key: String) -> Dictionary:
	var legal := _legal()
	if not legal.has(key):
		return {"ok": false, "error": "not legal now: " + key}
	if key == "menu start":
		menu_started = true
		menu.Start()
		return {"ok": true}
	im.activeInteractionBranch = legal[key]
	im.MainInteractionEvent()
	return {"ok": true}


# --- state ----------------------------------------------------------------------------------

func _public() -> Dictionary:
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
	}


func _hidden() -> Dictionary:
	return {
		"sequence": rm.shellSpawner.sequenceArray.duplicate(),
		"dealer_knows": rm.dealerAI.sequenceArray_knownShell.duplicate(),
	}


func _write(data: Dictionary) -> void:
	data["t_ms"] = Time.get_ticks_msec()
	data["time_scale"] = observed_scale
	log_file.store_line(JSON.stringify(data))
	log_file.flush()

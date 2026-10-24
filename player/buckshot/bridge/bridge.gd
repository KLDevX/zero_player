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
#   {"cmd": "thought", "thought": {...}} -> what the in-game interface shows on the right (hud.gd)
#   {"cmd": "take_step"}         -> {"go": true} once per → press in step mode (the AI may make one move)
#   {"cmd": "screenshot", "path": "C:/.../x.png"} -> saves the game's frame with the interface
#   {"cmd": "key", "key": "F1", "ctrl": false} -> presses an interface key, as if typed (tests)
# The state reply also carries "ui": AI on/off, auto or step mode, speed — set by the keys in the game:
#   F1 AI on/off · → one move · Space auto/step · Ctrl+1…4 speed ×1/×3/×10/×20 · F6 interface style
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
const PHONE_PATH := "res://scripts/BurnerPhone.gd"
const BRANCH_PATH := "res://scripts/InteractionBranch.gd"
const SPEEDS := [1.0, 3.0, 10.0, 20.0]
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
var peers: Array = []  # [{"tcp", "inbox", "brain"}]: the AI's brain plus test tools at once
var serving: Dictionary = {}  # the peer whose command is being handled
var target_scale := 1.0
var observed_scale := 1.0  # time scale the last frame really ran at (before we set ours)
var menu_started := false
var phone: Node = null
# What the player can know, tracked from what happens on screen (the same fields as the simulator's
# observation): shells seen leaving the gun, inversions, the player's own magnifier and phone.
var k_prev: Array = []        # the gun last frame
var k_knows: Array = []       # per shell: "", "live" or "blank" — what the player has seen
var k_inverted := false       # the chambered shell was flipped an odd number of times
var k_last := ""              # the shell that last left the gun in this load
var k_live := 0               # original colours still in the gun
var k_blank := 0
var k_anim := ""              # the player's hands animation last frame
var k_phone_wait := false     # burner phone used: read its message
var k_fired: Array = []       # shells that left the gun this load, in order (public)
var k_dealer_used := {}       # items the dealer used this load (public: you watch him do it)
var k_table_prev := {}        # {"player": {...}, "dealer": {...}} item counts on the table last frame
# The in-game interface (docs/ui-plan.md): drawn on a layer above the game, kept last under the root so
# its keys are seen before the game's own (input goes to the last node first).
var hud_layer: CanvasLayer
var hud: Control
var ui := {"ai_on": false, "auto": false, "steps": 0}
var window_fix_at := -1  # when to re-enter fullscreen (ms); -1 = not yet planned, 0 = done


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
	if OS.get_environment("BRIDGE_MUTE") == "1":
		AudioServer.set_bus_mute(0, true)  # tests nobody watches: silent from the first frame
	hud_layer = CanvasLayer.new()
	hud_layer.layer = 100
	hud = load(get_script().resource_path.get_base_dir().path_join("hud.gd")).new()
	hud.bridge = self
	hud.thought = {"status": "мозг ИИ не подключён: python -m player.buckshot.launch"}
	hud_layer.add_child(hud)
	get_tree().root.add_child.call_deferred(hud_layer)
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
	hud.ui = _ui_state()
	_keep_window()
	if not _scene_ok():
		hud.public = {}
		_rescan()
		return
	if rm == null:
		hud.public = {}
		return
	_track_knowledge()
	var state := {"public": _public(), "_hidden": _hidden()}
	hud.public = state["public"] if rm.endless else {}
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
	if window_fix_at == -1 and scene != null:
		window_fix_at = now + 1000
	branches = []
	branches_ms = 0
	rm = null
	im = null
	cursor = null
	menu = null
	item_interaction = null
	timescale_managers = []
	phone = null
	k_prev = []
	k_knows = []
	k_fired = []
	k_dealer_used = {}
	k_table_prev = {}
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
			PHONE_PATH: phone = node
	if hud_layer.get_parent() == get_tree().root:
		get_tree().root.move_child(hud_layer, -1)
	print("[bridge] scene ", scene.name, " rm=", rm != null, " im=", im != null, " menu=", menu != null)
	_write({"event": "scene " + scene.name})


# --- commands -------------------------------------------------------------------------------

func _serve() -> void:
	while server.is_connection_available():
		peers.append({"tcp": server.take_connection(), "inbox": "", "brain": false})
		print("[bridge] python connected (", peers.size(), ")")
	for c in peers.duplicate():
		var tcp: StreamPeerTCP = c["tcp"]
		tcp.poll()
		if tcp.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			peers.erase(c)
			if c["brain"]:
				hud.thought = {"status": "мозг ИИ отключился"}
				ui["ai_on"] = false
			continue
		var n := tcp.get_available_bytes()
		if n > 0:
			c["inbox"] += tcp.get_utf8_string(n)
		while c["inbox"].find("\n") != -1:
			var cut: int = c["inbox"].find("\n")
			var line: String = c["inbox"].substr(0, cut)
			c["inbox"] = c["inbox"].substr(cut + 1)
			var msg = JSON.parse_string(line)
			serving = c
			var reply: Dictionary = _handle(msg) if msg is Dictionary else {"ok": false, "error": "bad json"}
			tcp.put_data((JSON.stringify(reply) + "\n").to_utf8_buffer())


func _handle(msg: Dictionary) -> Dictionary:
	match msg.get("cmd", ""):
		"state":
			if not _scene_ok():
				return {"ok": true, "scene": "", "legal": [], "ui": _ui_state()}
			var reply := {"ok": true, "scene": scene.name if scene != null else "", "legal": _legal().keys(), "ui": _ui_state()}
			if rm != null:
				reply["public"] = _public()
			return reply
		"act":
			return _act(str(msg.get("key", "")))
		"speed":
			_set_speed(float(msg.get("x", 1.0)))
			return {"ok": true, "x": target_scale}
		"thought":
			var t = msg.get("thought", {})
			hud.thought = t if t is Dictionary else {}
			serving["brain"] = true  # the peer that sends thoughts is the brain
			return {"ok": true}
		"screenshot":
			# The game's own frame with the interface on it (no other windows): for checking the look.
			var img := get_viewport().get_texture().get_image()
			var err := img.save_png(str(msg.get("path", "")))
			return {"ok": err == OK, "size": [img.get_width(), img.get_height()], "vp": get_viewport().get_visible_rect().size}
		"key":
			# Press an interface key as if typed in the game (for tests): {"key": "F1", "ctrl": false}
			var ev := InputEventKey.new()
			ev.keycode = OS.find_keycode_from_string(str(msg.get("key", "")))
			ev.ctrl_pressed = bool(msg.get("ctrl", false))
			ev.pressed = true
			Input.parse_input_event(ev)
			return {"ok": ev.keycode != KEY_NONE}
		"take_step":
			if ui["steps"] > 0:
				ui["steps"] -= 1
				return {"ok": true, "go": true}
			return {"ok": true, "go": false}
		"mute":
			AudioServer.set_bus_mute(0, bool(msg.get("on", true)))
			return {"ok": true}
		"window":
			# Exclusive fullscreen (OptionsManager.gd:143) hides every other window; borderless lets an
			# overlay sit on top. Lab copy only.
			var modes := {"borderless": DisplayServer.WINDOW_MODE_FULLSCREEN,
						  "windowed": DisplayServer.WINDOW_MODE_WINDOWED}
			var mode := str(msg.get("mode", "borderless"))
			if modes.has(mode):
				DisplayServer.window_set_mode(modes[mode])
			var screen := DisplayServer.window_get_current_screen()
			return {"ok": true, "mode": DisplayServer.window_get_mode(), "pos": DisplayServer.window_get_position(),
					"size": DisplayServer.window_get_size(), "screen_pos": DisplayServer.screen_get_position(screen),
					"screen_size": DisplayServer.screen_get_size(screen), "screen_scale": DisplayServer.screen_get_scale(screen)}
	return {"ok": false, "error": "unknown cmd"}


# The game's exclusive fullscreen (OptionsManager.gd:143) can open shifted right and down, with part of the
# picture off screen. Akel's fix: leave fullscreen and enter it again. Only once per game start, a second
# after the first scene loads (the menu applies the game's window setting); windowed mode is left alone.
func _keep_window() -> void:
	if window_fix_at <= 0 or Time.get_ticks_msec() < window_fix_at:
		return
	window_fix_at = 0
	if DisplayServer.window_get_mode() == DisplayServer.WINDOW_MODE_EXCLUSIVE_FULLSCREEN:
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_WINDOWED)
		DisplayServer.window_set_mode.call_deferred(DisplayServer.WINDOW_MODE_EXCLUSIVE_FULLSCREEN)


func _set_speed(x: float) -> void:
	target_scale = x
	Engine.time_scale = target_scale
	Engine.max_physics_steps_per_frame = maxi(8, ceili(target_scale) * 2)


func _ui_state() -> Dictionary:
	return {"ai_on": ui["ai_on"], "auto": ui["auto"], "steps": ui["steps"], "speed": target_scale}


# Keys of the in-game interface (hud.gd passes every key press here first). Returns true if the key was ours,
# so the game doesn't also act on it (arrows and Space move the game's controller cursor otherwise).
func on_key(event: InputEventKey) -> bool:
	if not event.pressed or event.echo:
		return false
	if event.ctrl_pressed and event.keycode >= KEY_1 and event.keycode <= KEY_4:
		_set_speed(SPEEDS[event.keycode - KEY_1])
		return true
	match event.keycode:
		KEY_F1:
			ui["ai_on"] = not ui["ai_on"]
			ui["auto"] = false
			ui["steps"] = 0
			return true
		KEY_F6:
			hud.style_index = (hud.style_index + 1) % hud.STYLES.size()
			return true
		KEY_RIGHT:
			if ui["ai_on"] and not ui["auto"]:
				ui["steps"] = 1
				return true
		KEY_SPACE:
			if ui["ai_on"]:
				ui["auto"] = not ui["auto"]
				ui["steps"] = 0
				return true
	return false


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



# --- what the player can know -------------------------------------------------------------

func _flip(shell: String) -> String:
	return "blank" if shell == "live" else "live"


func _track_knowledge() -> void:
	var seq: Array = rm.shellSpawner.sequenceArray
	if seq.size() > k_prev.size():
		# a new load: the shells shown on the table are the public counts
		var r = rm.roundArray[rm.currentRound]
		k_fired = []
		k_dealer_used = {}
		k_knows = []
		k_knows.resize(seq.size())
		k_knows.fill("")
		k_inverted = false
		k_last = ""
		k_live = r.amountLive
		k_blank = r.amountBlank
	elif seq.size() == k_prev.size() - 1 and k_prev.size() > 0:
		# a shell left the gun (shot or beer); everyone sees its colour
		var shell: String = k_prev[0]
		var original: String = _flip(shell) if k_inverted else shell
		if original == "live":
			k_live -= 1
		else:
			k_blank -= 1
		k_last = shell
		k_fired.append(shell)
		k_inverted = false
		if k_knows.size() > 0:
			k_knows.pop_front()
	elif seq.size() == k_prev.size() and seq.size() > 0 and seq[0] != k_prev[0] and seq.slice(1) == k_prev.slice(1):
		# only the chambered shell changed: an inverter was used (by either side; both see it)
		k_inverted = not k_inverted
		if k_knows.size() > 0 and k_knows[0] != "":
			k_knows[0] = _flip(k_knows[0])
	var anim := ""
	if item_interaction != null and item_interaction.animator_playerHands != null:
		anim = item_interaction.animator_playerHands.current_animation
	if anim != k_anim:
		if anim == "player use magnifier" and seq.size() > 0 and k_knows.size() > 0:
			k_knows[0] = seq[0]  # the player sees the chambered shell
		if anim == "player use burner phone":
			k_phone_wait = true
	k_anim = anim
	if k_phone_wait:
		_read_phone(seq)
	k_prev = seq.duplicate()
	_track_dealer_items(seq)


# The dealer used an item = exactly one of his items left the table while the player's items stayed and the
# player isn't stealing. A table clear (new round) removes many at once and is ignored. Known gap: when the
# dealer steals the player's item with adrenaline, only the adrenaline is counted.
func _track_dealer_items(seq: Array) -> void:
	var now := _table_items()
	if not k_table_prev.is_empty() and seq.size() > 0:
		var before: Dictionary = k_table_prev["dealer"]
		var drops := []
		for item in before:
			for i in range(before[item] - now["dealer"].get(item, 0)):
				drops.append(item)
		var stealing: bool = item_interaction != null and item_interaction.stealing
		if drops.size() == 1 and now["player"] == k_table_prev["player"] and not stealing:
			k_dealer_used[drops[0]] = k_dealer_used.get(drops[0], 0) + 1
	k_table_prev = now


func _table_items() -> Dictionary:
	var player := {}
	var dealer := {}
	for c in rm.itemManager.itemSpawnParent.get_children():
		if c.get_child_count() < 2:
			continue
		var b = c.get_child(1)
		if b.get_script() == null or b.get_script().resource_path != BRANCH_PATH or b.itemName == "":
			continue
		var side: Dictionary = player if b.isPlayerSide else dealer
		side[b.itemName] = side.get(b.itemName, 0) + 1
	return {"player": player, "dealer": dealer}


# The phone's message names a position and a colour (BurnerPhone.gd:6-35); match it in the current language.
func _read_phone(seq: Array) -> void:
	if phone == null or phone.dia == null or phone.dia.dialogueUI == null:
		k_phone_wait = false
		return
	var text: String = phone.dia.dialogueUI.text
	if text == "" or not phone.dia.dialogueUI.is_visible_in_tree():
		return
	if text.begins_with(tr("UNFORTUNATE")):
		k_phone_wait = false
		return
	for k in range(2, 8):
		if text.begins_with(tr("SEQUENCE%d" % k)):
			var idx := k - 1
			var colour: String = "blank" if text.contains((tr("BLANKROUND") % "").strip_edges()) else "live"
			if idx < k_knows.size():
				k_knows[idx] = colour
			k_phone_wait = false
			return

# --- state ----------------------------------------------------------------------------------

func _public() -> Dictionary:
	var load_info := {}
	if rm.currentRound < rm.roundArray.size():
		var r = rm.roundArray[rm.currentRound]
		# HP for the whole round comes from slot 0 (HealthCounter.gd:39-40)
		load_info = {"max_hp": rm.roundArray[0].startingHealth, "loaded_live": r.amountLive, "loaded_blank": r.amountBlank}
	# Count the items lying on the table, as the player sees them. The game's own counters (amount_player)
	# go wrong after an adrenaline steal: the stolen item is subtracted twice (ItemInteraction.gd:84-86, 107-111).
	var table := _table_items()
	var items_player: Dictionary = table["player"]
	var items_dealer: Dictionary = table["dealer"]
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
		"live_left": k_live,
		"blank_left": k_blank,
		"last_shell": k_last,
		"current_inverted": k_inverted,
		"known_current": k_knows[0] if k_knows.size() > 0 else "",
		"known_later": _known_later(),
		"stealing": item_interaction != null and item_interaction.stealing,
		"fired": k_fired.duplicate(),
		"dealer_used": k_dealer_used.duplicate(),
	}


func _known_later() -> Dictionary:
	var later := {}
	for i in range(1, k_knows.size()):
		if k_knows[i] != "":
			later[str(i)] = k_knows[i]
	return later


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

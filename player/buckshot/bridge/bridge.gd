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
#   F1 AI on/off · Space one move · Ctrl+Space auto/step · Ctrl+1…4 speed ×1/×3/×10/×20 · I why · N network
#   F11 fullscreen ↔ windowed · ~ developer mode: console (help), F2/F3 panels, PgUp/PgDn model
# The arrows are left to the game (they pick items with the keyboard).
#   {"cmd": "dev_info", "models": [...], "current": "dx1.5@…"} -> the models the brain can load
#   {"cmd": "dev_log", "text": "..."} -> a line in the developer console
# Keys are matched by their place on the keyboard (physical), so they work in the Russian layout too.
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
const RESET_PATH := "res://scripts/ResetManager.gd"
const CAMERA_PATH := "res://scripts/CameraManager.gd"
const AMBIENT := ["light", "animator_pp"]  # animators that play now and then for the mood (flicker, fades)
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
var reset_manager: Node = null  # the game's own restart (hold R for 0.8 s)
var camera: Node = null         # CameraManager: `moving` while the camera turns (to the dealer, back home)
var anim_players: Array = []    # every AnimationPlayer: a one-shot animation playing = the game is busy
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
var ui := {"ai_on": false, "auto": false, "steps": 0, "panel_i": false, "panel_n": false, "cheat": false,
		   "model_req": "", "dev_changes": 0, "achievement": false, "restarts": 0, "realtime": true, "record": false}
# Recording record runs (Akel): every run is recorded — the game's frames (JPG, 4 per second, 15 when slow) and
# its sound (AudioEffectRecord on the Master bus) — and kept only if it beat the record (12 rounds or more);
# otherwise it is deleted. Near a record the game slows to ×1 so the video can be watched. A kept run is a
# folder reports/ui/recordings/record_<N>r_<date>/ with frames, times.txt and sound.wav;
# `python -m player.buckshot.recordings` makes an MP4 from it.
const REC_MIN_ROUNDS := 12
const REC_FAST_MS := 250
const REC_SLOW_MS := 66
var rec_dir := ""          # this run's folder while recording, "" = not recording
var rec_frames := 0
var rec_last_ms := 0
var rec_t0 := 0
var rec_times: PackedStringArray = []
var rec_audio: AudioEffectRecord = null
var rec_best := 0          # rounds of the kept record (read from reports/ui/recordings/record.json)
var run_won := 0           # rounds won in this run, for the recording
var rec_scene := 0         # the scene whose run is (or was) recorded
# The one achievement the bridge may give (Akel's choice): "ach10", dying in Double or Nothing with a prize
# over 1 000 000 — the game's own rule (DeathManager.gd:143). The game itself can't give it here, because the
# bridge switches Steam off (using_steam = false) so nothing reaches the leaderboard; the leaderboard stays
# off. Only with `achievement on`, and only for the AI's own run: [F1] on all the way, no table-changing
# commands, no cheats.
const ACH_PRIZE := 1000000
var run_dev_at := 0        # dev_changes when this run (the main scene) began
var run_cheat := false     # `cheat order` was on at the table during this run
var run_ai := true         # the AI was on ([F1]) the whole run: only then it's the AI's achievement
var run_endless := false   # what the last frame of the run looked like
var run_prize := 0
# Akel: while hunting ach10, a run whose first prize will end under 31 250 is restarted at once (from that
# prize on, 18 rounds are enough instead of 21). The first prize only falls while its timer runs, so the
# moment the live estimate drops under the line the run can't make it.
const RESTART_BELOW := 31250
const HELP := """model <имя> · models · speed <x> · ai on|off · auto on|off
hp <n> · hp dealer <n> · kill dealer (в твой ход)
shells live blank … · remove <предмет> [dealer]
cheat order — видеть порядок патронов · i · n
achievement on|off — выдать «1 000 000 и умер» за чистую партию
realtime on|off — выбор хода на ×1 (анимации на ×N)
record on|off — записывать раны, оставлять рекордные (от 12 раундов) · mute · unmute · clear"""
const ITEM_NAMES := {"наручники": "handcuffs", "пиво": "beer", "лупа": "magnifying glass", "сигареты": "cigarettes",
		"пила": "handsaw", "лекарство": "expired medicine", "инвертор": "inverter", "телефон": "burner phone",
		"адреналин": "adrenaline"}


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
	var want := _wanted_scale()
	if target_scale != 1.0 and Engine.time_scale != 0.0:
		# TimeScaleManager's slow-mo after a dealer kill never clears its "moving" flag and keeps
		# setting Engine.time_scale back to 1.0 every frame (TimeScaleManager.gd:21-27).
		for tsm in timescale_managers:
			if is_instance_valid(tsm):
				tsm.moving = false
		Engine.time_scale = want
	hud.ui = _ui_state()
	if not _scene_ok():
		hud.public = {}
		_rescan()
		return
	if rm == null:
		hud.public = {}
		return
	_track_knowledge()
	run_endless = rm.endless
	run_prize = int(rm.endscore) if rm.endscore != null else 0
	run_cheat = run_cheat or (ui["cheat"] and rm.endless)
	run_ai = run_ai and (ui["ai_on"] or not rm.endless)
	_restart_if_slow()
	run_won = maxi(0, int(rm.brief.ending.endless_roundsbeat) - 1) if rm.endless else 0
	_rec_frame()
	var state := {"public": _public(), "_hidden": _hidden()}
	hud.public = state["public"] if rm.endless else {}
	if rm.endless:
		# for the money line only (not part of what the agent sees): the first prize and its timer
		# (RoundManager.gd:385-396: 70 000 − timer / 600 s × 40 000, counted from the waiver to the 3rd round)
		var shown: Dictionary = state["public"].duplicate()  # (Dictionary.merged() is newer than Godot 4.1)
		shown.merge({"don_initial": rm.double_or_nothing_initial_score, "don_timer": rm.initial_time,
				"don_counting": rm.counting})
		hud.public = shown
	# cheats: the real order, for the screen only — never in a reply to Python
	hud.cheat_order = state["_hidden"]["sequence"] if ui["cheat"] and rm.endless else []
	var key := JSON.stringify(state)
	if key != last_state:
		last_state = key
		_write(state)


func _rescan() -> void:
	# The death check comes first, on the very first frame of a new scene: at ×20 the death screen can be gone
	# before the next scan (it was: main → death → main with no scan in between).
	var next := get_tree().current_scene
	if next != null and next.get_instance_id() != scene_id:
		if rec_dir != "":
			_rec_stop(run_won)
		if run_endless and (next.name.to_lower().contains("death") or next.scene_file_path.contains("death")):
			_check_achievement()
		run_endless = false  # (a null scene is the moment between two scenes: keep the run until the next one)
	var now := Time.get_ticks_msec()
	if now - last_scan < SCAN_INTERVAL_MS:
		return
	last_scan = now
	scene = next
	scene_id = scene.get_instance_id() if scene != null else 0
	branches = []
	branches_ms = 0
	rm = null
	im = null
	cursor = null
	menu = null
	item_interaction = null
	timescale_managers = []
	phone = null
	reset_manager = null
	camera = null
	anim_players = []
	k_prev = []
	k_knows = []
	k_fired = []
	k_dealer_used = {}
	k_table_prev = {}
	menu_started = false
	if scene == null:
		return
	for node in scene.find_children("*", "", true, false):
		if node is AnimationPlayer:
			anim_players.append(node)
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
			RESET_PATH: reset_manager = node
			CAMERA_PATH: camera = node
	if hud_layer.get_parent() == get_tree().root:
		get_tree().root.move_child(hud_layer, -1)
	if rm != null:
		run_dev_at = ui["dev_changes"]  # a new run begins
		run_cheat = false
		run_ai = true
		run_prize = 0
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
			var reply := {"ok": true, "scene": scene.name if scene != null else "", "legal": _legal().keys(), "ui": _ui_state(),
						  "busy": _busy(), "scene_id": scene_id}
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
			ev.physical_keycode = ev.keycode
			ev.unicode = int(msg.get("char", 0))  # a typed character, for console tests
			ev.ctrl_pressed = bool(msg.get("ctrl", false))
			ev.pressed = true
			Input.parse_input_event(ev)
			return {"ok": ev.keycode != KEY_NONE}
		"dev_info":
			hud.models = msg.get("models", [])
			hud.model_current = str(msg.get("current", ""))
			return {"ok": true}
		"dev_log":
			hud.log_line(str(msg.get("text", "")))
			return {"ok": true}
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


# F11: fullscreen ↔ windowed. The game's exclusive fullscreen (OptionsManager.gd:143) sometimes opens
# shifted right and down; pressing F11 twice (windowed, then fullscreen again) puts it back (Akel's fix).
func _toggle_fullscreen() -> void:
	if DisplayServer.window_get_mode() == DisplayServer.WINDOW_MODE_WINDOWED:
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_EXCLUSIVE_FULLSCREEN)
	else:
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_WINDOWED)


# While the first prize's timer runs (waiver → end of round 3), speed-up is for the game's animations only:
# when the cursor is shown somebody is choosing a move, and the game runs at its normal ×1, so a choice costs
# as much game time as it takes (at ×20 every real millisecond of the bot's reaction cost 20 ms of the prize
# timer; 189 game-seconds per first cycle). After that the prize is set and everything runs at ×N (Akel).
# `realtime off` in the console switches it off.
func _wanted_scale() -> float:
	if ui["record"] and rec_dir != "" and rm != null and _scene_ok() and rm.endless \
			and run_won >= maxi(REC_MIN_ROUNDS - 1, rec_best):
		return 1.0  # going for a record: normal speed, so the video can be watched
	if ui["realtime"] and rm != null and _scene_ok() and rm.counting and cursor != null and is_instance_valid(cursor) 			and cursor.cursor_visible:
		return 1.0
	return target_scale


func _set_speed(x: float) -> void:
	target_scale = x
	Engine.time_scale = target_scale
	Engine.max_physics_steps_per_frame = maxi(8, ceili(target_scale) * 2)


func _ui_state() -> Dictionary:
	return {"ai_on": ui["ai_on"], "auto": ui["auto"], "steps": ui["steps"], "speed": target_scale,
			"panel_i": ui["panel_i"], "panel_n": ui["panel_n"], "cheat": ui["cheat"], "model_req": ui["model_req"],
			"dev_changes": ui["dev_changes"], "achievement": ui["achievement"], "restarts": ui["restarts"],
			"scale_now": Engine.time_scale}


# Keys of the in-game interface (hud.gd passes every key press here first). Returns true if the key was ours,
# so the game doesn't also act on it. I and N work only with the AI on (they explain its move).
func on_key(event: InputEventKey) -> bool:
	if not event.pressed:
		return false
	var key := event.physical_keycode
	if key == KEY_QUOTELEFT:
		if not event.echo:
			hud.dev_open = not hud.dev_open
		return true
	if hud.dev_open:
		_dev_key(event, key)
		return true  # while the console is open every key is ours
	if event.echo:
		return false
	if event.ctrl_pressed and key >= KEY_1 and key <= KEY_4:
		_set_speed(SPEEDS[key - KEY_1])
		return true
	match key:
		KEY_F1:
			ui["ai_on"] = not ui["ai_on"]
			ui["auto"] = false
			ui["steps"] = 0
			return true
		KEY_F11:
			_toggle_fullscreen()
			return true
		KEY_I, KEY_N:
			if ui["ai_on"]:
				var k := "panel_i" if key == KEY_I else "panel_n"
				ui[k] = not ui[k]
				return true
		KEY_SPACE:
			if ui["ai_on"]:
				if event.ctrl_pressed:
					ui["auto"] = not ui["auto"]
					ui["steps"] = 0
				elif ui["auto"]:
					ui["auto"] = false  # Space during auto: stop and go on step by step
				else:
					ui["steps"] = 1
				return true
	return false


func _dev_key(event: InputEventKey, key: int) -> void:
	match key:
		KEY_F2:
			if not event.echo:
				ui["panel_i"] = not ui["panel_i"]
		KEY_F3:
			if not event.echo:
				ui["panel_n"] = not ui["panel_n"]
		KEY_PAGEUP, KEY_PAGEDOWN:
			if not hud.models.is_empty():
				var i: int = hud.models.find(ui["model_req"] if ui["model_req"] != "" else hud.model_current.split("@")[0])
				i = (i + (1 if key == KEY_PAGEDOWN else -1) + hud.models.size()) % hud.models.size()
				ui["model_req"] = hud.models[i]
				hud.log_line("модель → " + hud.models[i])
		KEY_ENTER, KEY_KP_ENTER:
			var line: String = hud.console_line.strip_edges()
			hud.console_line = ""
			if line != "":
				hud.console_history.append(line)
				hud.history_at = hud.console_history.size()
				hud.log_line("> " + line)
				_console(line)
		KEY_BACKSPACE:
			hud.console_line = hud.console_line.substr(0, maxi(0, hud.console_line.length() - 1))
		KEY_UP, KEY_DOWN:
			if not hud.console_history.is_empty():
				hud.history_at = clampi(hud.history_at + (-1 if key == KEY_UP else 1), 0, hud.console_history.size())
				hud.console_line = hud.console_history[hud.history_at] if hud.history_at < hud.console_history.size() else ""
		KEY_ESCAPE:
			hud.dev_open = false
		_:
			if event.unicode >= 32:
				hud.console_line += char(event.unicode)


func _console(line: String) -> void:
	var words := line.split(" ", false)
	var cmd := words[0].to_lower()
	var arg := words[1].to_lower() if words.size() > 1 else ""
	var on := arg != "off"
	match cmd:
		"help":
			hud.log_line(HELP)
		"models":
			hud.log_line(", ".join(hud.models) if not hud.models.is_empty() else "мозг ИИ не подключён")
		"model":
			if not hud.models.has(arg):
				hud.log_line("нет модели «%s»: models — список" % arg)
			else:
				ui["model_req"] = arg
				hud.log_line("загружаю " + arg)
		"speed":
			if arg.is_valid_float() and float(arg) > 0:
				_set_speed(float(arg))
				hud.log_line("скорость ×" + arg)
			else:
				hud.log_line("speed <число>, например speed 5")
		"ai":
			ui["ai_on"] = on
			ui["steps"] = 0
			hud.log_line("ИИ " + ("включён" if on else "выключен"))
		"auto":
			ui["auto"] = on
			ui["steps"] = 0
			hud.log_line("авто " + ("вкл" if on else "выкл"))
		"i", "n":
			var k := "panel_" + cmd
			ui[k] = (not ui[k]) if arg == "" else on
			hud.log_line("панель %s %s" % [cmd.to_upper(), "вкл" if ui[k] else "выкл"])
		"cheat":
			var last: String = words[words.size() - 1].to_lower() if words.size() > 1 else ""
			ui["cheat"] = (not ui["cheat"]) if last in ["", "order"] else last != "off"
			hud.log_line("порядок патронов " + ("виден (только тебе, ИИ — нет)" if ui["cheat"] else "скрыт"))
		"hp":
			_cmd_hp(words)
		"kill":
			_cmd_kill()
		"shells":
			_cmd_shells(words.slice(1))
		"remove":
			_cmd_remove(words.slice(1))
		"achievement":
			if arg == "on" or arg == "off":
				ui["achievement"] = arg == "on"
			var state := "выкл"
			if ui["achievement"]:
				state = "вкл"
			hud.log_line("достижение «1 000 000 и умер»: " + state + " · партия " + ("засчитается" if _run_clean() else
					"не засчитается: " + _run_problem()))
			hud.log_line("с ним: ран перезапускается, если первый приз будет меньше %d (перезапусков: %d)"
					% [RESTART_BELOW, ui["restarts"]])
			if Engine.has_singleton("Steam"):
				var got: Dictionary = Steam.getAchievement("ach10")
				hud.log_line("в Steam: " + ("уже получено" if got.get("achieved", false) else "ещё нет"))
		"realtime":
			ui["realtime"] = arg != "off"
			hud.log_line("выбор хода на ×1, анимации на ×N: " + ("вкл" if ui["realtime"] else "выкл"))
		"record":
			if arg == "on" or arg == "off":
				ui["record"] = arg == "on"
			if arg == "test":
				ui["record"] = true
				ui["rec_test"] = true  # keep the next run whatever its rounds, aside from the record
			_rec_load_best()
			hud.log_line("запись рекордных ранов: %s · рекорд %d раунд. (сохраняется от %d)"
					% ["вкл" if ui["record"] else "выкл", rec_best, REC_MIN_ROUNDS])
		"mute", "unmute":
			AudioServer.set_bus_mute(0, cmd == "mute")
			hud.log_line("звук " + ("выкл" if cmd == "mute" else "вкл"))
		"clear":
			hud.console_log = []
		_:
			hud.log_line("неизвестная команда: " + cmd + " (help)")


func _first_prize_estimate() -> int:
	return maxi(10, 70000 - int(rm.initial_time / 600.0 * 40000.0))


func _restart_if_slow() -> void:
	if not (ui["achievement"] and ui["ai_on"] and rm.endless and rm.counting) or reset_manager == null:
		return
	if rm.double_or_nothing_initial_score > 0 or _first_prize_estimate() >= RESTART_BELOW:
		return
	ui["restarts"] += 1
	var text := "первый приз будет меньше %d — перезапуск рана (%d)" % [RESTART_BELOW, ui["restarts"]]
	print("[bridge] ", text)
	hud.log_line(text)
	_write({"event": text})
	run_endless = false  # a restart is not a death with a prize
	reset_manager.Reset()  # the same as holding R


# --- recording record runs ------------------------------------------------------------------

func _rec_root() -> String:
	return get_script().resource_path.get_base_dir().path_join("../../../reports/ui/recordings").simplify_path()


func _rec_load_best() -> void:
	var f := FileAccess.open(_rec_root().path_join("record.json"), FileAccess.READ)
	if f != null:
		var d = JSON.parse_string(f.get_as_text())
		if d is Dictionary:
			rec_best = int(d.get("rounds", 0))


func _rec_start() -> void:
	if not ui["record"] or rm == null or not rm.endless:
		return
	_rec_load_best()
	for stray in DirAccess.get_directories_at(_rec_root()) if DirAccess.dir_exists_absolute(_rec_root()) else []:
		if stray.begins_with("run_"):
			_rec_delete(_rec_root().path_join(stray))  # left by a game that was closed mid-run
	var stamp := Time.get_datetime_string_from_system().replace(":", "-")
	rec_dir = _rec_root().path_join("run_" + stamp)
	DirAccess.make_dir_recursive_absolute(rec_dir)
	rec_frames = 0
	rec_last_ms = 0
	rec_t0 = Time.get_ticks_msec()
	rec_times = []
	var bus := AudioServer.get_bus_index("Master")
	if rec_audio == null:
		rec_audio = AudioEffectRecord.new()
		AudioServer.add_bus_effect(bus, rec_audio)
	rec_audio.set_recording_active(false)
	rec_audio.set_recording_active(true)


func _rec_frame() -> void:
	if rec_dir == "":
		# the run turns into Double or Nothing at the pills, inside this scene: start then, once per scene
		if ui["record"] and rm.endless and rec_scene != scene_id:
			rec_scene = scene_id
			_rec_start()
		return
	var now := Time.get_ticks_msec()
	var every := REC_SLOW_MS if Engine.time_scale <= 1.0 else REC_FAST_MS
	if now - rec_last_ms < every:
		return
	rec_last_ms = now
	rec_frames += 1
	var fname := "f_%06d.jpg" % rec_frames
	get_viewport().get_texture().get_image().save_jpg(rec_dir.path_join(fname), 0.85)
	rec_times.append("%s %d" % [fname, now - rec_t0])


func _rec_stop(won: int) -> void:
	var dir := rec_dir
	rec_dir = ""
	var wav: AudioStreamWAV = null
	if rec_audio != null:
		wav = rec_audio.get_recording()
		rec_audio.set_recording_active(false)
	var test: bool = ui.get("rec_test", false)
	if not test and (won < REC_MIN_ROUNDS or won <= rec_best):
		_rec_delete(dir)
		return
	if wav != null:
		wav.save_to_wav(dir.path_join("sound.wav"))
	var f := FileAccess.open(dir.path_join("times.txt"), FileAccess.WRITE)
	f.store_string("\n".join(rec_times) + "\n")
	f.close()
	var root := _rec_root()
	if test:  # `record test`: keep this one run aside, the record is not touched
		ui["rec_test"] = false
		DirAccess.rename_absolute(dir, root.path_join("test_%dr_%s" % [won, dir.get_file().trim_prefix("run_")]))
		_write({"event": "test run kept: %d rounds" % won})
		return
	# the new record replaces the old one
	for old in DirAccess.get_directories_at(root):
		if old.begins_with("record_"):
			_rec_delete(root.path_join(old))
	var stamp := dir.get_file().trim_prefix("run_")
	var kept := root.path_join("record_%dr_%s" % [won, stamp])
	DirAccess.rename_absolute(dir, kept)
	rec_best = won
	var j := FileAccess.open(root.path_join("record.json"), FileAccess.WRITE)
	j.store_string(JSON.stringify({"rounds": won, "folder": kept.get_file(), "prize": run_prize}))
	j.close()
	_write({"event": "record kept: %d rounds" % won, "folder": kept})
	print("[bridge] record kept: ", won, " rounds -> ", kept)


func _rec_delete(dir: String) -> void:
	if dir == "" or not DirAccess.dir_exists_absolute(dir):
		return
	for f in DirAccess.get_files_at(dir):
		DirAccess.remove_absolute(dir.path_join(f))
	DirAccess.remove_absolute(dir)


func _run_clean() -> bool:
	return ui["dev_changes"] == run_dev_at and not run_cheat and run_ai


func _run_problem() -> String:
	if ui["dev_changes"] != run_dev_at:
		return "были команды (dev)"
	if run_cheat:
		return "были читы"
	if not run_ai:
		return "ИИ был выключен"
	return ""


# Called when the run's main scene gives way to the death scene.
func _check_achievement() -> void:
	_write({"event": "run over (death)", "prize": run_prize, "achievement_mode": ui["achievement"],
			"counts": _run_clean()})
	var text := ""
	if run_prize <= ACH_PRIZE:
		return  # the game wouldn't give it either
	if not ui["achievement"]:
		text = "приз %d, но выдача выключена (achievement on)" % run_prize
	elif not _run_clean():
		text = "приз %d, но не засчитано: %s" % [run_prize, _run_problem()]
	elif not Engine.has_singleton("Steam"):
		text = "Steam недоступен"
	else:
		Steam.setAchievement("ach10")
		Steam.storeStats()
		text = "выдано достижение «1 000 000 и умер» (приз %d)" % run_prize
	print("[bridge] ach10: ", text)
	hud.log_line(text)
	_write({"event": "ach10: " + text})


# --- developer commands that change the table (the game is then saved as «(dev)») ---------------

func _at_table() -> bool:
	if rm == null or not _scene_ok() or not rm.endless:
		hud.log_line("только за столом (Double or Nothing)")
		return false
	return true


func _your_turn() -> bool:
	# while animations run the game's own code may be in the middle of something; only on your move
	if not _at_table():
		return false
	if not rm.deskUI_shotgun.visible or (item_interaction != null and item_interaction.stealing):
		hud.log_line("только в твой ход (когда можно взять ружьё)")
		return false
	return true


func _cmd_hp(words: Array) -> void:
	if not _at_table():
		return
	var dealer := words.has("dealer") or words.has("дилер")
	var n := -1
	for w in words:
		if str(w).is_valid_int():
			n = int(w)
	if n < 1:
		hud.log_line("hp <число> или hp dealer <число>")
		return
	var max_hp: int = rm.roundArray[0].startingHealth
	n = clampi(n, 1, max_hp)  # the defibrillator display has no room for more
	if dealer:
		rm.health_opponent = n
	else:
		rm.health_player = n
	rm.healthCounter.UpdateDisplay()
	ui["dev_changes"] += 1
	hud.log_line("%s: %d жизн." % ["дилер" if dealer else "ты", n])


func _cmd_kill() -> void:
	if not _your_turn():
		return
	# the same ending as a fatal shot: the table is closed, the dealer's HP hits 0, the round ends
	item_interaction.DisablePermissions()
	rm.health_opponent = 0
	rm.healthCounter.UpdateDisplay()
	rm.OutOfHealth("dealer")
	ui["dev_changes"] += 1
	hud.log_line("дилер убит")


func _cmd_shells(words: Array) -> void:
	if not _your_turn():
		return
	var seq: Array[String] = []
	for w in words:
		var x := str(w).to_lower()
		if x in ["live", "l", "б", "боевой"]:
			seq.append("live")
		elif x in ["blank", "b", "х", "холостой"]:
			seq.append("blank")
		else:
			hud.log_line("не понял «%s»: shells live blank live …" % x)
			return
	if seq.is_empty() or seq.size() > 8:
		hud.log_line("от 1 до 8 патронов: shells live blank live")
		return
	rm.shellSpawner.sequenceArray = seq
	var known: Array[bool] = []
	known.resize(seq.size())
	known.fill(false)
	rm.dealerAI.sequenceArray_knownShell = known
	# the new shells are public (you put them in): the counts are reset, nothing is known
	k_prev = seq.duplicate()
	k_knows = []
	k_knows.resize(seq.size())
	k_knows.fill("")
	k_inverted = false
	k_live = seq.count("live")
	k_blank = seq.count("blank")
	ui["dev_changes"] += 1
	hud.log_line("патроны: %d боев. · %d холост." % [k_live, k_blank])


func _cmd_remove(words: Array) -> void:
	if not _your_turn():
		return
	var dealer := words.has("dealer") or words.has("дилер")
	var item := ""
	for w in words:
		var x := str(w).to_lower()
		if ITEM_NAMES.has(x):
			item = ITEM_NAMES[x]
		elif ITEM_NAMES.values().has(x):
			item = x
	if item == "":
		hud.log_line("remove <предмет> [dealer], например remove лупа")
		return
	for c in rm.itemManager.itemSpawnParent.get_children():
		if c.get_child_count() < 2:
			continue
		var b = c.get_child(1)
		if b.get_script() == null or b.get_script().resource_path != BRANCH_PATH:
			continue
		if b.itemName != item or b.isPlayerSide == dealer:
			continue
		for res in rm.itemManager.amounts.array_amounts:
			if res.itemName == item:
				if dealer:
					res.amount_dealer -= 1
				else:
					res.amount_player -= 1
		if not dealer:
			item_interaction.RemovePlayerItemFromGrid(c)  # frees its cell on the grid
		c.queue_free()
		k_table_prev = {}  # don't count it as the dealer using an item
		ui["dev_changes"] += 1
		hud.log_line("убрано: %s (%s)" % [item, "дилер" if dealer else "ты"])
		return
	hud.log_line("на столе нет: %s (%s)" % [item, "дилер" if dealer else "ты"])


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


# What keeps the game busy right now: "" when it is free. Hands, dealer, items and camera turns are played
# by AnimationPlayers and the CameraManager; looping ones (lights, idle sway) are background and don't count.
# Reported for the logs only: the bot clicks when the game allows it (the clickable list), like a human.
func _busy() -> String:
	# CameraManager never clears `moving` (CameraManager.gd:84-95): the turn is over when elapsed reaches dur
	if camera != null and is_instance_valid(camera) and camera.moving and camera.elapsed < camera.dur:
		return "camera"
	for ap in anim_players:
		if not is_instance_valid(ap) or not ap.is_playing() or AMBIENT.any(func(a): return ap.name.contains(a)):
			continue
		var anim: Animation = ap.get_animation(ap.current_animation) if ap.current_animation != "" else null
		if anim != null and anim.loop_mode == Animation.LOOP_NONE:
			return "%s:%s" % [ap.name, ap.current_animation]
	return ""


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

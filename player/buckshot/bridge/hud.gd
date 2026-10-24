extends Control
# The AI's interface drawn inside the game (docs/ui-plan.md). The bridge owns this node and feeds it every
# frame: `public` (what the player can know), `thought` (sent by Python), `ui` (AI on/off, mode, speed,
# panels) and, only when cheats are on in developer mode, `cheat_order` (the real shell order; never sent to the
# agent). Panels have fixed sizes, so nothing jumps when the text changes.
#   top left: shells        top right: advice / the AI's move        middle left (I): all data
#   bottom left (N): the network                                     bottom right (~): developer mode
# Drawn with _draw() in the game's own 960×540 frame, with its receipt font and shell colours.

const FONT := "res://fonts/Fake Receipt Cyr Ver2_2.ttf"
const FALLBACK_FONT := "res://fonts/fonts language/NotoSans-Regular_new.ttf"
const PANEL := Color(0.04, 0.04, 0.04, 0.82)
const EDGE := Color(0.85, 0.85, 0.8, 0.35)
const TEXT := Color(0.93, 0.92, 0.88)
const DIM := Color(0.6, 0.6, 0.57)
const ACCENT := Color(1.0, 0.86, 0.45)
const GOOD := Color(0.45, 0.9, 0.45)
const BAD := Color(1.0, 0.35, 0.33)
const OFF := Color(0.45, 0.45, 0.43)
const UNKNOWN := Color(0.42, 0.42, 0.4)
const CHEAT := Color(0.85, 0.45, 1.0)
const BRASS := Color(0.85, 0.68, 0.3)
const M := 12.0         # margin from the screen edge
const PAD := 8.0
const S := 12           # font sizes
const SMALL := 10
const BIG := 15
const LEFT_W := 290.0
const RIGHT_W := 350.0
const DEV_W := 430.0
const NET_H := 128.0

var bridge: Node = null
var public: Dictionary = {}
var cheat_order: Array = []
var thought: Dictionary = {}
var ui: Dictionary = {}
var dev_open := false
var console_line := ""
var console_log: Array = ["help — список команд"]
var console_history: Array = []
var history_at := 0
var models: Array = []
var model_current := ""
var font: Font


func _ready() -> void:
	set_anchors_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	# A variation, so the game's own font resource is never changed.
	var f := FontVariation.new()
	f.base_font = load(FONT)
	var fallback = load(FALLBACK_FONT)
	if fallback != null:
		f.fallbacks = [fallback]
	font = f


func _process(_delta: float) -> void:
	queue_redraw()


func _input(event: InputEvent) -> void:
	if bridge == null:
		return
	if dev_open and event is InputEventMouseButton:
		get_viewport().set_input_as_handled()  # clicks mustn't reach the table while you type
		return
	if event is InputEventKey and bridge.on_key(event):
		get_viewport().set_input_as_handled()


func log_line(text: String) -> void:
	for line in text.split("\n"):
		console_log.append(line)
	while console_log.size() > 7:
		console_log.pop_front()


# --- colours and words -----------------------------------------------------------------------

func _live() -> Color:
	return GlobalVariables.colorblind_color_live if GlobalVariables.colorblind else GlobalVariables.default_color_live


func _blank() -> Color:
	return GlobalVariables.colorblind_color_blank if GlobalVariables.colorblind else GlobalVariables.default_color_blank


func _shell(s: String) -> Color:
	return _live() if s == "live" else _blank()


func _flip(s: String) -> String:
	return "blank" if s == "live" else "live"


func _name(item: String) -> String:
	return str(thought.get("names", {}).get(item, item))


func _items(d: Dictionary) -> String:
	var out := []
	for k in d:
		out.append(_name(k) + ("×%d" % d[k] if d[k] > 1 else ""))
	return ", ".join(out) if not out.is_empty() else "—"


# What every slot of the gun looks like to the player: {"c": colour or null, "how": "seen" | "counted"}.
# "counted": the unseen shells are all one colour, so these are that colour (anyone can count it; for the
# interface only — the agent gets its own observation and works it out itself).
func _order() -> Array:
	var p := public
	var n := int(p.get("shells_left", 0))
	var known := []
	known.resize(n)
	known.fill("")
	if n > 0:
		known[0] = str(p.get("known_current", ""))
	var later: Dictionary = p.get("known_later", {})
	for k in later:
		if int(k) < n:
			known[int(k)] = later[k]
	var inverted: bool = p.get("current_inverted", false)
	var lives := int(p.get("live_left", 0))  # original colours still in the gun
	var blanks := int(p.get("blank_left", 0))
	for i in range(n):
		if known[i] != "":
			var original: String = _flip(known[i]) if i == 0 and inverted else known[i]
			if original == "live":
				lives -= 1
			else:
				blanks -= 1
	var counted := ""
	if lives > 0 and blanks == 0:
		counted = "live"
	elif blanks > 0 and lives == 0:
		counted = "blank"
	var out := []
	for i in range(n):
		if known[i] != "":
			out.append({"c": _shell(known[i]), "how": "seen"})
		elif counted != "":
			out.append({"c": _shell(_flip(counted) if i == 0 and inverted else counted), "how": "counted"})
		else:
			out.append({"c": null, "how": ""})
	return out


# --- drawing helpers -------------------------------------------------------------------------

func _box(r: Rect2, title := "") -> void:
	draw_rect(r, PANEL)
	draw_rect(r, EDGE, false, 1.0)


func _fit(text: String, size: int, max_w: float) -> String:
	if max_w <= 0 or font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, size).x <= max_w:
		return text
	while text.length() > 1 and font.get_string_size(text + "…", HORIZONTAL_ALIGNMENT_LEFT, -1, size).x > max_w:
		text = text.substr(0, text.length() - 1)
	return text + "…"


func _lh(size: int) -> float:
	return font.get_height(size) + 3.0


# Draws text with its top at y; returns the width used.
func _text(x: float, y: float, text: String, size: int, c: Color, max_w := -1.0) -> float:
	text = _fit(text.to_upper(), size, max_w)
	draw_string(font, Vector2(x, y + font.get_ascent(size)), text, HORIZONTAL_ALIGNMENT_LEFT, -1, size, c)
	return font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, size).x


func _text_r(right: float, y: float, text: String, size: int, c: Color) -> void:
	text = text.to_upper()
	var w := font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, size).x
	_text(right - w, y, text, size, c)


# A shell standing on its brass end, like the ones shown on the table.
func _pip(x: float, y: float, w: float, h: float, c, how := "seen", current := false) -> void:
	if c == null:
		draw_rect(Rect2(x, y, w, h * 0.78), UNKNOWN)
	elif how == "counted":
		draw_rect(Rect2(x + 0.5, y + 0.5, w - 1, h * 0.78 - 1), c, false, 1.0)
	elif how == "cheat":
		draw_rect(Rect2(x, y, w, h * 0.78), Color(c, 0.45))
		draw_rect(Rect2(x + w * 0.3, y - 3, w * 0.4, 2), CHEAT)
	else:
		draw_rect(Rect2(x, y, w, h * 0.78), c)
	draw_rect(Rect2(x, y + h * 0.78, w, h * 0.22), BRASS)
	if current:
		draw_rect(Rect2(x - 1, y + h + 2, w + 2, 2), ACCENT)


func _hp(x: float, y: float, n: int, max_hp: int) -> float:
	for i in range(max_hp):
		draw_rect(Rect2(x + i * 8, y + 3, 6, 9), TEXT if i < n else Color(DIM, 0.3))
	return max_hp * 8.0


func _bar(x: float, y: float, w: float, frac: float, c: Color) -> void:
	draw_rect(Rect2(x, y + 5, w, 4), Color(DIM, 0.3))
	draw_rect(Rect2(x, y + 5, w * clampf(frac, 0.0, 1.0), 4), c)


# --- panels ----------------------------------------------------------------------------------

func _draw() -> void:
	var vp := get_viewport_rect().size
	var left_bottom := M
	if not public.is_empty():
		left_bottom = _left(Vector2(M, M))
	_right(Vector2(vp.x - M - RIGHT_W, M))
	var net_top := vp.y - M - NET_H
	if ui.get("panel_n", false) and not thought.get("net", {}).is_empty():
		_net(Rect2(M, net_top, LEFT_W, NET_H))
	else:
		net_top = vp.y - M
	if ui.get("panel_i", false):
		_info(left_bottom + 8, net_top - 8, vp)
	if dev_open:
		_dev(vp)


func _left(at: Vector2) -> float:
	var p := public
	var lh := _lh(S)
	var r := Rect2(at, Vector2(LEFT_W, PAD * 2 + lh * 7 + 6))
	_box(r)
	var x := at.x + PAD
	var col := x + 104
	var y := at.y + PAD
	_text(x, y, "ПАТРОНЫ", SMALL, DIM)
	_text_r(r.end.x - PAD, y, "боевых: %d · холостых: %d" % [p.get("live_left", 0), p.get("blank_left", 0)], SMALL, TEXT)
	y += lh
	# 1) which shells are in the gun at all
	_text(x, y, "в ружье:", S, DIM)
	var px := col
	for i in range(int(p.get("live_left", 0))):
		_pip(px, y + 1, 7, 13, _live())
		px += 10
	for i in range(int(p.get("blank_left", 0))):
		_pip(px, y + 1, 7, 13, _blank())
		px += 10
	y += lh
	# 2) their order: grey = unknown, coloured = known, outline = counted; the yellow line is the chamber
	_text(x, y, "порядок:", S, DIM)
	var order := _order()
	px = col
	for i in range(order.size()):
		var s: Dictionary = order[i]
		if s["c"] == null and i < cheat_order.size():
			_pip(px, y + 1, 9, 13, _shell(cheat_order[i]), "cheat", i == 0)
		else:
			_pip(px, y + 1, 9, 13, s["c"], s["how"], i == 0)
		px += 13
	if p.get("current_inverted", false):
		_text(px + 4, y, "инвертор", SMALL, DIM)
	if not cheat_order.is_empty():
		_text_r(r.end.x - PAD, y, "ЧИТ", SMALL, CHEAT)
	y += lh + 6
	_text(x, y, "вылетели:", S, DIM)
	var fired: Array = p.get("fired", [])
	px = col
	for s in fired:
		_pip(px, y + 2, 6, 11, _shell(s))
		px += 9
	if fired.is_empty():
		_text(col, y, "—", S, OFF)
	y += lh
	var max_hp := int(p.get("load_info", {}).get("max_hp", 0))
	_text(x, y, "жизни:", S, DIM)
	var w := _text(col, y, "ты ", S, DIM)
	_hp(col + w, y, int(p.get("hp_player", 0)), max_hp)
	w = _text(col + 70, y, "дилер ", S, DIM)
	_hp(col + 70 + w, y, int(p.get("hp_dealer", 0)), max_hp)
	y += lh
	# cuffs: on the dealer = good for you (green), on you = red, none = grey
	_text(x, y, "наручники:", S, DIM)
	if p.get("dealer_cuffed", false):
		_text(col, y, "на дилере", S, GOOD)
	elif p.get("player_cuffed", false):
		_text(col, y, "на тебе", S, BAD)
	else:
		_text(col, y, "нет", S, OFF)
	_text(col + 96, y, "пила:", S, DIM)
	if p.get("saw", false):
		_text(col + 144, y, "да ×2", S, ACCENT)
	else:
		_text(col + 144, y, "нет", S, OFF)
	y += lh
	_text(x, y, "дилер брал:", S, DIM)
	var used: Dictionary = p.get("dealer_used", {})
	_text(col, y, _items(used), S, TEXT if not used.is_empty() else OFF, r.end.x - PAD - col)
	return r.end.y


func _right(at: Vector2) -> void:
	var lh := _lh(S)
	var r := Rect2(at, Vector2(RIGHT_W, PAD * 2 + lh * 4 + _lh(BIG) + _lh(SMALL)))
	_box(r)
	var x := at.x + PAD
	var inner := RIGHT_W - 2 * PAD
	var y := at.y + PAD
	var on: bool = ui.get("ai_on", false)
	var mode := "ВЫКЛ — играешь ты"
	if on:
		mode = "АВТО" if ui.get("auto", false) else "ПОШАГОВО"
	_text(x, y, "ИИ: " + mode, S, DIM)
	_text_r(r.end.x - PAD, y, "×%s" % _num(ui.get("speed", 1.0)), S, DIM)
	y += lh
	var move: String = thought.get("move", "")
	if move != "":
		var w := _text(x, y, "ход ИИ: " if on else "совет: ", BIG, DIM)
		_text(x + w, y, move, BIG, ACCENT, inner - w)
	else:
		_text(x, y, str(thought.get("status", "")), BIG, TEXT, inner)
	y += _lh(BIG)
	var ch = thought.get("chance")
	if move != "" and ch != null:
		var w := _text(x, y, "шанс выиграть раунд", S, DIM)
		_bar(x + w + 8, y, inner - w - 8 - 40, float(ch), ACCENT)
		_text_r(r.end.x - PAD, y, "%d%%" % roundi(100.0 * float(ch)), S, TEXT)
	y += lh
	var alts: Array = thought.get("alts", [])
	if move != "" and not alts.is_empty():
		var parts := []
		for a in alts:
			parts.append("%s %d%%" % [a[0], roundi(100.0 * float(a[1]))])
		_text(x, y, "дальше: " + " · ".join(parts), S, DIM, inner)
	y += lh
	var note := ""
	var note_c := DIM
	if move != "" and thought.get("tie", false):
		note = "ходы почти равны (разница < 1%)"
	if on and not ui.get("auto", false) and move != "":
		note = "→  сделать этот ход"
		note_c = ACCENT
	elif move != "" and str(thought.get("status", "")) != "":
		note = str(thought["status"])
	elif move == "" and str(thought.get("last", "")) != "":
		note = "последний ход: " + str(thought["last"])
	_text(x, y, note, S, note_c, inner)
	y += lh
	_text(x, y, "F1 ИИ  → ход  Пробел авто  Ctrl+1–4  I  N  Ё", SMALL, DIM, inner)


func _info(top: float, bottom: float, vp: Vector2) -> void:
	var p := public
	var lh := _lh(S)
	var rows := 10
	var h := PAD * 2 + lh * rows
	var y0 := clampf(vp.y * 0.5 - h * 0.5, top, maxf(top, bottom - h))
	var r := Rect2(M, y0, LEFT_W, h)
	_box(r)
	var x := M + PAD
	var inner := LEFT_W - 2 * PAD
	var y := y0 + PAD
	_text(x, y, "ВСЕ ДАННЫЕ", SMALL, DIM)
	_text_r(r.end.x - PAD, y, "I", SMALL, DIM)
	y += lh
	var moves: Array = thought.get("all", [])
	for i in range(5):
		if i < moves.size():
			var m: Array = moves[i]
			var c := ACCENT if i == 0 else TEXT
			_text(x, y, str(m[0]), S, c, 150)
			if m[1] != null:
				_bar(x + 156, y, inner - 156 - 40, float(m[1]), c)
				_text_r(r.end.x - PAD, y, "%d%%" % roundi(100.0 * float(m[1])), S, c)
		elif i == 0:
			_text(x, y, "сейчас не твой ход", S, OFF)
		y += lh
	if p.is_empty():
		return
	_text(x, y, "твои: " + _items(p.get("items_player", {})), S, TEXT, inner)
	y += lh
	_text(x, y, "у дилера: " + _items(p.get("items_dealer", {})), S, TEXT, inner)
	y += lh
	_text(x, y, "раунд %d · заряд %d · циклов DoN %d" % [maxi(1, int(p.get("rounds_beat", 1))),
			int(p.get("load", 0)) + 1, int(p.get("don_cycles_beat", 0))], S, DIM, inner)
	y += lh
	_text(x, y, "модель: " + str(thought.get("agent", "—")), S, DIM, inner)


func _net(r: Rect2) -> void:
	_box(r)
	var net: Dictionary = thought.get("net", {})
	var layers: Array = net.get("layers", [])
	var x := r.position.x + PAD
	_text(x, r.position.y + PAD, "НЕЙРОСЕТЬ", SMALL, DIM)
	var sizes := []
	for l in layers:
		sizes.append(str(l.size()))
	_text_r(r.end.x - PAD, r.position.y + PAD, " → ".join(sizes) + "   N", SMALL, DIM)
	if layers.size() != 4:
		return
	var top := r.position.y + PAD + _lh(SMALL)
	var area_h := r.end.y - PAD - top
	# columns of dots: input, hidden 1, hidden 2, moves; brightness = how strongly it fires
	var cols := [5, 4, 4, 1]
	var xs := [x, x + 62, x + 112, x + 162]
	var pos := []
	for li in range(4):
		var vals: Array = layers[li]
		var per_col := ceili(float(vals.size()) / cols[li])
		var step := area_h / per_col
		var lp := []
		for i in range(vals.size()):
			lp.append(Vector2(xs[li] + (i / per_col) * 8 + 2, top + (i % per_col) * step + step * 0.5))
		pos.append(lp)
	for e in net.get("edges", []):
		var a: Vector2 = pos[int(e[0])][int(e[1])]
		var b: Vector2 = pos[int(e[0]) + 1][int(e[2])]
		var c := GOOD if float(e[3]) > 0 else BAD
		draw_line(a, b, Color(c, 0.15 + 0.5 * absf(float(e[3]))), 1.0)
	var legal: Array = net.get("legal", [])
	var choice := int(net.get("choice", -1))
	for li in range(4):
		var vals: Array = layers[li]
		for i in range(vals.size()):
			var v := clampf(float(vals[i]), 0.0, 1.0)
			var c := Color(TEXT, 0.12 + 0.88 * v)
			if li == 3:
				c = ACCENT if i == choice else (Color(TEXT, 0.25 + 0.6 * v) if legal.has(i) else Color(OFF, 0.25))
			draw_rect(Rect2(pos[li][i] - Vector2(1.5, 1.5), Vector2(3, 3)), c)
	if choice >= 0:
		var at: Vector2 = pos[3][choice]
		_text(at.x + 8, at.y - 7, str(thought.get("move", "")), SMALL, ACCENT, r.end.x - PAD - at.x - 8)


func _dev(vp: Vector2) -> void:
	var lh := _lh(S)
	var h := PAD * 2 + lh * (5 + 7)
	var r := Rect2(vp.x - M - DEV_W, vp.y - M - h, DEV_W, h)
	draw_rect(r, Color(0.02, 0.02, 0.02, 0.92))
	draw_rect(r, ACCENT, false, 1.0)
	var x := r.position.x + PAD
	var inner := DEV_W - 2 * PAD
	var y := r.position.y + PAD
	_text(x, y, "РЕЖИМ РАЗРАБОТЧИКА", S, ACCENT)
	_text_r(r.end.x - PAD, y, "Ё (~) — закрыть", SMALL, DIM)
	y += lh
	var boxes := [["F2", "panel_i", "I — все данные"], ["F3", "panel_n", "N — нейросеть"],
				  ["F4", "cheat", "читы: виден порядок патронов"]]
	for b in boxes:
		var on: bool = ui.get(b[1], false)
		_text(x, y, "[%s] %s  %s" % ["x" if on else " ", b[0], b[2]], S, (CHEAT if b[1] == "cheat" else TEXT) if on else DIM)
		y += lh
	var w := _text(x, y, "модель: ", S, DIM)
	_text(x + w, y, model_current if model_current != "" else "—", S, TEXT, inner - w - 110)
	_text_r(r.end.x - PAD, y, "PgUp/PgDn сменить", SMALL, DIM)
	y += lh
	for line in console_log:
		_text(x, y, line, S, DIM, inner)
		y += lh
	y = r.end.y - PAD - lh
	var cursor := "_" if int(Time.get_ticks_msec() / 500) % 2 == 0 else " "
	_text(x, y, "> " + console_line + cursor, S, TEXT, inner)


func _num(x) -> String:
	return str(int(x)) if float(x) == floorf(float(x)) else "%.1f" % float(x)

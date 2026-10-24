extends Control
# The AI's interface drawn inside the game (docs/ui-plan.md, step 1). The bridge owns this node and feeds it
# every frame: `public` (what the player can know), `thought` (sent by Python) and `ui` (AI on/off, mode,
# speed). Left panel: the shells and what you know. Right panel: the advice or the AI's move and its chance.
# Drawn with _draw(): the game's own fonts and shell colours, no mouse input (clicks go to the game).

const FONT_DIR := "res://fonts/"
# Style variants (F6 cycles them while Akel picks one): font, panel colour, text colour, scan lines.
const STYLES := [
	{"name": "чек", "font": "Fake Receipt Cyr Ver2_2.ttf", "panel": Color(0.04, 0.04, 0.04, 0.82),
	 "edge": Color(0.85, 0.85, 0.8, 0.35), "text": Color(0.93, 0.92, 0.88), "dim": Color(0.6, 0.6, 0.57),
	 "accent": Color(1.0, 0.86, 0.45), "scan": 0.0, "size": 1.0},
	{"name": "табло", "font": "DOTMATRI Ver2_2.ttf", "panel": Color(0.0, 0.0, 0.0, 0.86),
	 "edge": Color(0.95, 0.95, 0.95, 0.18), "text": Color(0.96, 0.96, 0.96), "dim": Color(0.55, 0.55, 0.55),
	 "accent": Color(1.0, 1.0, 1.0), "scan": 0.22, "size": 1.15},
	{"name": "плита", "font": "fonts language/RobotoSlab-Medium_cyrillic.ttf", "panel": Color(0.07, 0.065, 0.06, 0.78),
	 "edge": Color(1.0, 0.28, 0.29, 0.9), "text": Color(0.92, 0.9, 0.86), "dim": Color(0.58, 0.56, 0.53),
	 "accent": Color(1.0, 0.8, 0.4), "scan": 0.08, "size": 0.9},
]
const FALLBACK_FONT := "fonts language/NotoSans-Regular_new.ttf"

var bridge: Node = null
var public: Dictionary = {}
var thought: Dictionary = {}
var ui: Dictionary = {}
var style_index := 0
var fonts: Array = []


func _ready() -> void:
	set_anchors_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	var fallback = load(FONT_DIR + FALLBACK_FONT)
	for s in STYLES:
		# A variation, so the game's own font resource is never changed.
		var f := FontVariation.new()
		f.base_font = load(FONT_DIR + s["font"])
		if fallback != null:
			f.fallbacks = [fallback]
		fonts.append(f)


func _process(_delta: float) -> void:
	queue_redraw()


func _input(event: InputEvent) -> void:
	if event is InputEventKey and bridge != null and bridge.on_key(event):
		get_viewport().set_input_as_handled()


func _live() -> Color:
	return GlobalVariables.colorblind_color_live if GlobalVariables.colorblind else GlobalVariables.default_color_live


func _blank() -> Color:
	return GlobalVariables.colorblind_color_blank if GlobalVariables.colorblind else GlobalVariables.default_color_blank


func _shell(s: String) -> Color:
	return _live() if s == "live" else _blank()


func _word(s: String) -> String:
	return {"live": "боевой", "blank": "холостой"}.get(s, "?")


# --- what goes on screen ---------------------------------------------------------------------
# A row is {"size": font scale, "parts": [...]}; a part is {"text", "c"}, {"pip": colour}, {"hp": [n, max]},
# {"bar": 0..1, "c"} or {"gap": px}.

func _left_rows(st: Dictionary) -> Array:
	var p := public
	var rows := []
	rows.append(_row(0.8, [_t("ПАТРОНЫ", st["dim"]), _t("  порядок неизвестен", st["dim"])]))
	var pips := []
	for i in range(int(p.get("live_left", 0))):
		pips.append({"pip": _live()})
	for i in range(int(p.get("blank_left", 0))):
		pips.append({"pip": _blank()})
	pips.append({"gap": 10})
	pips.append(_t("%d боев. · %d холост." % [p.get("live_left", 0), p.get("blank_left", 0)], st["text"]))
	rows.append(_row(1.0, pips))
	var cur: String = p.get("known_current", "")
	var cur_parts := [_t("в стволе: ", st["dim"]), _t(_word(cur), _shell(cur) if cur != "" else st["text"])]
	var guess := _deduce_current()
	if cur == "" and guess != "":
		cur_parts = [_t("в стволе: ", st["dim"]), _t(_word(guess), _shell(guess)), _t("  (по счёту)", st["dim"])]
	if p.get("current_inverted", false):
		cur_parts.append(_t("  (инвертор)", st["dim"]))
	rows.append(_row(1.0, cur_parts))
	var later: Dictionary = p.get("known_later", {})
	if not later.is_empty():
		var parts := [_t("знаю дальше: ", st["dim"])]
		var keys := later.keys()
		keys.sort_custom(func(a, b): return int(a) < int(b))
		for k in keys:
			parts.append(_t("№%d " % (int(k) + 1), st["text"]))
			parts.append(_t(_word(later[k]) + "  ", _shell(later[k])))
		rows.append(_row(0.9, parts))
	var fired: Array = p.get("fired", [])
	if not fired.is_empty():
		var parts := [_t("вылетели: ", st["dim"])]
		for s in fired:
			parts.append({"pip": _shell(s), "small": true})
		rows.append(_row(0.9, parts))
	var used: Dictionary = p.get("dealer_used", {})
	if not used.is_empty():
		var names := []
		for k in used:
			names.append(str(thought.get("names", {}).get(k, k)) + ("×%d" % used[k] if used[k] > 1 else ""))
		rows.append(_row(0.9, [_t("дилер взял: ", st["dim"]), _t(", ".join(names), st["text"])]))
	var max_hp := int(p.get("load_info", {}).get("max_hp", 0))
	var flags := ""
	if p.get("saw", false):
		flags += "  пила"
	if p.get("dealer_cuffed", false):
		flags += "  дилер в наручниках"
	if p.get("player_cuffed", false):
		flags += "  ты в наручниках"
	rows.append(_row(1.0, [_t("ты ", st["dim"]), {"hp": [int(p.get("hp_player", 0)), max_hp]}, {"gap": 18},
						   _t("дилер ", st["dim"]), {"hp": [int(p.get("hp_dealer", 0)), max_hp]},
						   _t(flags, st["accent"])]))
	return rows


# What any player can count: if the shells you haven't seen are all one colour, the chambered one is that
# colour. Only for the interface; the agent gets its own observation and works it out itself.
func _deduce_current() -> String:
	var p := public
	if p.get("current_inverted", false):
		return ""
	var lives := int(p.get("live_left", 0))
	var blanks := int(p.get("blank_left", 0))
	var later: Dictionary = p.get("known_later", {})
	for k in later:
		if later[k] == "live":
			lives -= 1
		else:
			blanks -= 1
	if lives > 0 and blanks == 0:
		return "live"
	if blanks > 0 and lives == 0:
		return "blank"
	return ""


func _right_rows(st: Dictionary) -> Array:
	var rows := []
	var mode := "ВЫКЛ — играешь ты"
	if ui.get("ai_on", false):
		mode = "АВТО" if ui.get("auto", false) else "ПОШАГОВО"
	rows.append(_row(0.8, [_t("ИИ: " + mode, st["dim"]), _t("   ×%s" % _num(ui.get("speed", 1.0)), st["dim"])]))
	var move: String = thought.get("move", "")
	if move != "":
		var head := "ИИ ходит: " if ui.get("ai_on", false) else "совет: "
		rows.append(_row(1.25, [_t(head, st["dim"]), _t(move, st["accent"])]))
		var ch = thought.get("chance")
		if ch != null:
			rows.append(_row(0.9, [_t("шанс выиграть раунд  ", st["dim"]), {"bar": float(ch), "c": st["accent"]},
								   _t("  %d%%" % roundi(100.0 * float(ch)), st["text"])]))
		var alts: Array = thought.get("alts", [])
		if not alts.is_empty():
			var parts := [_t("дальше: ", st["dim"])]
			for a in alts:
				parts.append(_t("%s %d%%   " % [a[0], roundi(100.0 * float(a[1]))], st["dim"]))
			rows.append(_row(0.8, parts))
	var status: String = thought.get("status", "")
	if status != "":
		rows.append(_row(0.85, [_t(status, st["text"])]))
	if ui.get("ai_on", false) and not ui.get("auto", false) and move != "":
		rows.append(_row(0.85, [_t("→  сделать этот ход", st["accent"])]))
	var keys := "F1 ИИ   → ход   Пробел авто   Ctrl+1…4 скорость   F6 стиль"
	rows.append(_row(0.65, [_t(keys, st["dim"])]))
	return rows


func _num(x) -> String:
	return str(int(x)) if float(x) == floorf(float(x)) else "%.1f" % float(x)


func _t(text: String, c: Color) -> Dictionary:
	return {"text": text, "c": c}


func _row(size: float, parts: Array) -> Dictionary:
	return {"size": size, "parts": parts}


# --- drawing ---------------------------------------------------------------------------------

func _draw() -> void:
	var st: Dictionary = STYLES[style_index]
	var font: Font = fonts[style_index]
	var vp := get_viewport_rect().size
	var base := vp.y / 42.0 * float(st["size"])
	var margin := vp.y / 40.0
	if not public.is_empty():
		_panel(Vector2(margin, margin), false, _left_rows(st), font, base, st)
	_panel(Vector2(vp.x - margin, margin), true, _right_rows(st), font, base, st)


func _part_width(part: Dictionary, font: Font, size: int) -> float:
	if part.has("text"):
		return font.get_string_size(part["text"], HORIZONTAL_ALIGNMENT_LEFT, -1, size).x
	if part.has("pip"):
		return size * (0.6 if part.get("small", false) else 0.85)
	if part.has("hp"):
		return part["hp"][1] * size * 0.62
	if part.has("bar"):
		return size * 6.0
	return float(part.get("gap", 0))


func _panel(anchor: Vector2, right: bool, rows: Array, font: Font, base: float, st: Dictionary) -> void:
	var pad := base * 0.8
	var gap := base * 0.3
	var w := 0.0
	var h := 0.0
	for r in rows:
		var size := int(base * r["size"])
		var rw := 0.0
		for part in r["parts"]:
			rw += _part_width(part, font, size)
		w = maxf(w, rw)
		h += font.get_height(size) + gap
	var rect := Rect2(anchor - Vector2(w + 2 * pad if right else 0.0, 0), Vector2(w + 2 * pad, h - gap + 2 * pad))
	draw_rect(rect, st["panel"])
	if style_index == 2:
		# a shell-coloured edge on the side that faces the table
		var edge := Rect2(rect.position + (Vector2(rect.size.x - 3, 0) if right else Vector2.ZERO), Vector2(3, rect.size.y))
		draw_rect(edge, st["edge"])
	else:
		draw_rect(rect, st["edge"], false, 1.0)
	if float(st["scan"]) > 0.0:
		var sy := rect.position.y
		while sy < rect.end.y:
			draw_line(Vector2(rect.position.x, sy), Vector2(rect.end.x, sy), Color(0, 0, 0, st["scan"]), 1.0)
			sy += 3.0
	var y := rect.position.y + pad
	for r in rows:
		var size := int(base * r["size"])
		var line_h := font.get_height(size)
		var asc := font.get_ascent(size)
		var x := rect.position.x + pad
		for part in r["parts"]:
			var pw := _part_width(part, font, size)
			if part.has("text"):
				draw_string(font, Vector2(x, y + asc), part["text"], HORIZONTAL_ALIGNMENT_LEFT, -1, size, part["c"])
			elif part.has("pip"):
				# a shell standing on its brass end, like the ones shown on the table
				var sw := pw * 0.7
				var sh := line_h * (0.75 if part.get("small", false) else 1.0)
				var top := y + (line_h - sh) * 0.5
				draw_rect(Rect2(x, top, sw, sh * 0.78), part["pip"])
				draw_rect(Rect2(x, top + sh * 0.78, sw, sh * 0.22), Color(0.85, 0.68, 0.3))
			elif part.has("hp"):
				var n: int = part["hp"][0]
				for i in range(part["hp"][1]):
					var c: Color = st["text"] if i < n else Color(st["dim"], 0.35)
					draw_rect(Rect2(x + i * size * 0.62, y + line_h * 0.18, size * 0.46, line_h * 0.64), c)
			elif part.has("bar"):
				var bh := line_h * 0.3
				var by := y + (line_h - bh) * 0.5
				draw_rect(Rect2(x, by, pw, bh), Color(st["dim"], 0.3))
				draw_rect(Rect2(x, by, pw * clampf(part["bar"], 0.0, 1.0), bh), part["c"])
			x += pw
		y += line_h + gap

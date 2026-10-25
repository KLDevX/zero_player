extends Control
# The AI's interface drawn inside the game (docs/ui-plan.md). The bridge owns this node and feeds it every
# frame: `public` (what the player can know), `thought` (sent by Python), `ui` (AI on/off, mode, speed,
# panels) and, only with the developer command `cheat order`, `cheat_order` (the real shell order; on screen
# only, never sent to the agent). Panels have fixed sizes, so nothing jumps when the text changes.
#   top left: your shells (always at the table)      top right: the AI's card (only with [F1] on)
#   middle left [I]: why it picks the move           bottom left [N]: the network      bottom right [~]: console
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
const OFF := Color(0.42, 0.42, 0.4)
const UNKNOWN := Color(0.45, 0.45, 0.43)
const CHEAT := Color(0.85, 0.45, 1.0)
const BRASS := Color(0.83, 0.66, 0.3)
const RIM := Color(0.35, 0.26, 0.12)
const BAR_GREY := Color(0.62, 0.62, 0.6)
const M := 12.0          # margin from the screen edge
const PAD := 8.0
const S := 10            # font sizes
const SMALL := 9
const BIG := 12
const LEFT_W := 250.0
const RIGHT_W := 270.0
const WHY_W := 400.0
const ITEMS_W := 124.0  # the item table on the right of the why window
const DEV_W := 430.0
const NET_H := 128.0
const SHELL_W := 5.0     # a 2D shell like the ones the game shows: flat top, coloured hull, brass base
const SHELL_H := 13.0
const SHELL_STEP := 9.0
const SLIDE_SECONDS := 0.15
const ITEMS := ["handcuffs", "beer", "magnifying glass", "cigarettes", "handsaw", "expired medicine", "inverter",
				"burner phone", "adrenaline"]

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
var key_font: Font       # the receipt font draws "~" as a dash
var ink := 1.0           # alpha of what is being drawn (the AI card fades while it waits)
var card_t := 0.0        # 0 = card hidden, 1 = shown (slides in)
var last_ms := 0
var shown: Dictionary = {}  # the last thought with a move: stays on the card, faded, while the dealer plays


func _ready() -> void:
	set_anchors_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	# A variation, so the game's own font resource is never changed.
	var f := FontVariation.new()
	f.base_font = load(FONT)
	key_font = load(FALLBACK_FONT)
	if key_font != null:
		f.fallbacks = [key_font]
	else:
		key_font = f
	font = f


func _process(_delta: float) -> void:
	# real time, not game time: the game may run at ×20
	var now := Time.get_ticks_msec()
	var dt := (now - last_ms) / 1000.0 if last_ms > 0 else 0.0
	last_ms = now
	var target := 1.0 if ui.get("ai_on", false) else 0.0
	card_t = move_toward(card_t, target, dt / SLIDE_SECONDS)
	if str(thought.get("move", "")) != "":
		shown = thought
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


func _shell_colour(s: String) -> Color:
	return _live() if s == "live" else _blank()


func _flip(s: String) -> String:
	return "blank" if s == "live" else "live"


# The thought to explain: the current one, or the last move while the dealer plays (so panels don't blink).
func _now() -> Dictionary:
	return thought if str(thought.get("move", "")) != "" else shown


func _name(item: String) -> String:
	return str(thought.get("names", shown.get("names", {})).get(item, item))


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
			out.append({"c": _shell_colour(known[i]), "how": "seen"})
		elif counted != "":
			out.append({"c": _shell_colour(_flip(counted) if i == 0 and inverted else counted), "how": "counted"})
		else:
			out.append({"c": null, "how": ""})
	return out


# --- drawing helpers (all of them use `ink`, so a whole panel can fade) ---------------------------

func _ink(c: Color) -> Color:
	return Color(c, c.a * ink)


func _rect(r: Rect2, c: Color, filled := true) -> void:
	draw_rect(r, _ink(c), filled, -1.0 if filled else 1.0)


func _box(r: Rect2) -> void:
	_rect(r, PANEL)
	_rect(r, EDGE, false)


func _width(text: String, size: int) -> float:
	var w := 0.0
	var parts := text.split("~")
	for i in range(parts.size()):
		w += font.get_string_size(parts[i], HORIZONTAL_ALIGNMENT_LEFT, -1, size).x
		if i < parts.size() - 1:
			w += key_font.get_string_size("~", HORIZONTAL_ALIGNMENT_LEFT, -1, size).x
	return w


func _fit(text: String, size: int, max_w: float) -> String:
	if max_w <= 0 or _width(text, size) <= max_w:
		return text
	while text.length() > 1 and _width(text + "…", size) > max_w:
		text = text.substr(0, text.length() - 1)
	return text + "…"


func _lh(size: int) -> float:
	return font.get_height(size) + 3.0


# Text with its top at y, in capitals (the receipt font is capitals only and draws some small letters
# oddly); "~" comes from the fallback font. Returns the width used.
func _text(x: float, y: float, text: String, size: int, c: Color, max_w := -1.0) -> float:
	text = _fit(text.to_upper(), size, max_w)
	var asc := font.get_ascent(size)
	var px := x
	var parts := text.split("~")
	for i in range(parts.size()):
		draw_string(font, Vector2(px, y + asc), parts[i], HORIZONTAL_ALIGNMENT_LEFT, -1, size, _ink(c))
		px += font.get_string_size(parts[i], HORIZONTAL_ALIGNMENT_LEFT, -1, size).x
		if i < parts.size() - 1:
			draw_string(key_font, Vector2(px, y + asc), "~", HORIZONTAL_ALIGNMENT_LEFT, -1, size, _ink(c))
			px += key_font.get_string_size("~", HORIZONTAL_ALIGNMENT_LEFT, -1, size).x
	return px - x


func _text_r(right: float, y: float, text: String, size: int, c: Color) -> void:
	_text(right - _width(text.to_upper(), size), y, text, size, c)


# A shell as the game shows them: a flat-topped coloured hull with a light edge, a dark rim, a brass base.
# how: "seen" (full colour), "counted" (darker: you know it by counting), "cheat" (pale, purple mark),
# "" with c = null: unknown (grey).
func _shell(x: float, y: float, c, how := "seen", current := false) -> void:
	var hull: Color = UNKNOWN if c == null else c
	if how == "counted":
		hull = hull.darkened(0.45)
	elif how == "cheat":
		hull = Color(hull, 0.5)
	var hull_h := SHELL_H * 0.68
	_rect(Rect2(x, y, SHELL_W, hull_h), hull)
	_rect(Rect2(x, y, 1, hull_h), hull.lightened(0.3))            # light edge
	_rect(Rect2(x, y, SHELL_W, 1), hull.darkened(0.25))           # crimped top
	_rect(Rect2(x, y + hull_h, SHELL_W, 1), RIM)                  # rim
	_rect(Rect2(x, y + hull_h + 1, SHELL_W, SHELL_H - hull_h - 1), BRASS)
	if how == "cheat":
		_rect(Rect2(x + 1, y - 3, SHELL_W - 2, 2), CHEAT)
	if current:
		_rect(Rect2(x - 1, y + SHELL_H + 2, SHELL_W + 2, 2), ACCENT)


func _hp(x: float, y: float, n: int, max_hp: int) -> float:
	for i in range(max_hp):
		_rect(Rect2(x + i * 7, y + 2, 5, 8), TEXT if i < n else Color(DIM, 0.3))
	return max_hp * 7.0


# A bar with an error bar |—| over its end: the spread of the neighbouring networks.
func _bar(x: float, y: float, w: float, frac: float, c: Color, lo := -1.0, hi := -1.0, h := 4.0) -> void:
	var by := y + 5
	_rect(Rect2(x, by, w, h), Color(DIM, 0.22))
	_rect(Rect2(x, by, w * clampf(frac, 0.0, 1.0), h), c)
	if lo >= 0.0 and hi > lo + 0.002:
		var x0 := x + w * clampf(lo, 0.0, 1.0)
		var x1 := x + w * clampf(hi, 0.0, 1.0)
		var mid := by + h * 0.5
		var wc := Color(TEXT, 0.85)
		_rect(Rect2(x0, mid - 0.5, x1 - x0, 1), wc)
		_rect(Rect2(x0, by - 2, 1, h + 4), wc)
		_rect(Rect2(x1 - 1, by - 2, 1, h + 4), wc)


# --- panels ----------------------------------------------------------------------------------

func _draw() -> void:
	var vp := get_viewport_rect().size
	ink = 1.0
	var left_bottom := M
	if not public.is_empty():
		left_bottom = _left(Vector2(M, M))
	if card_t > 0.0:
		var slide := (1.0 - ease(card_t, 0.4)) * (RIGHT_W + M)
		_card(Vector2(vp.x - M - RIGHT_W + slide, M))
	ink = 1.0
	var ai: bool = ui.get("ai_on", false)
	var net_top := vp.y - M
	if ai and ui.get("panel_n", false) and not _now().get("net", {}).is_empty():
		net_top = vp.y - M - NET_H
		_net(Rect2(M, net_top, LEFT_W, NET_H))
	if ai and ui.get("panel_i", false):
		_why(left_bottom + 8, net_top - 8, vp)
	if dev_open:
		_dev(vp)


func _left(at: Vector2) -> float:
	var p := public
	var lh := _lh(S)
	var row := maxf(lh, SHELL_H + 6)
	var r := Rect2(at, Vector2(LEFT_W, PAD * 2 + _lh(SMALL) + row * 3 + lh * 3))
	_box(r)
	var x := at.x + PAD
	var col := x + 84
	var right := r.end.x - PAD
	var y := at.y + PAD
	# money and rounds: rounds won / rounds needed for a prize over 1 000 000 (the first prize sets it)
	var prize := int(p.get("don_prize", 0))
	var first := int(p.get("don_initial", 0))
	if first <= 0 and p.get("don_counting", false):
		first = maxi(10, 70000 - int(float(p.get("don_timer", 0.0)) / 600.0 * 40000.0))  # falls while you play
	var won := maxi(0, int(p.get("rounds_beat", 1)) - 1)
	var w := _text(x, y, "приз ", SMALL, DIM)
	if prize > 0:
		_text(x + w, y, _money(prize), SMALL, ACCENT if prize > ACH_PRIZE else TEXT)
	elif first > 0:
		_text(x + w, y, "≈" + _money(first), SMALL, DIM)
	else:
		_text(x + w, y, "—", SMALL, OFF)
	var need := _rounds_for_million(first)
	_text_r(right, y, "раунд %d/%s · заряд %d" % [won, str(need) if need > 0 else "?", int(p.get("load", 0)) + 1],
			SMALL, DIM)
	y += _lh(SMALL)
	# 1) which shells are in the gun at all; 2) their order — grey unknown, coloured known, darker counted,
	# the yellow line under the chambered one; 3) the ones that left the gun. One size and step for all.
	_text(x, y + 2, "в ружье:", S, DIM)
	var px := col
	for i in range(int(p.get("live_left", 0))):
		_shell(px, y, _live())
		px += SHELL_STEP
	for i in range(int(p.get("blank_left", 0))):
		_shell(px, y, _blank())
		px += SHELL_STEP
	y += row
	_text(x, y + 2, "порядок:", S, DIM)
	var order := _order()
	px = col
	for i in range(order.size()):
		var s: Dictionary = order[i]
		if s["c"] == null and i < cheat_order.size():
			_shell(px, y, _shell_colour(cheat_order[i]), "cheat", i == 0)
		else:
			_shell(px, y, s["c"], s["how"], i == 0)
		px += SHELL_STEP
	if p.get("current_inverted", false):
		_text(px + 4, y + 2, "инвертор", SMALL, DIM)
	if not cheat_order.is_empty():
		_text_r(right, y + 2, "чит", SMALL, CHEAT)
	y += row
	_text(x, y + 2, "вылетели:", S, DIM)
	var fired: Array = p.get("fired", [])
	px = col
	for s in fired:
		_shell(px, y, _shell_colour(s))
		px += SHELL_STEP
	if fired.is_empty():
		_text(col, y + 2, "—", S, OFF)
	y += row
	var max_hp := int(p.get("load_info", {}).get("max_hp", 0))
	_text(x, y, "жизни:", S, DIM)
	w = _text(col, y, "ты ", S, DIM)
	_hp(col + w, y, int(p.get("hp_player", 0)), max_hp)
	w = _text(col + 66, y, "дилер ", S, DIM)
	_hp(col + 66 + w, y, int(p.get("hp_dealer", 0)), max_hp)
	y += lh
	# cuffs: on the dealer = good for you (green), on you = red, none = grey
	_text(x, y, "наручники:", S, DIM)
	if p.get("dealer_cuffed", false):
		_text(col, y, "на дилере", S, GOOD)
	elif p.get("player_cuffed", false):
		_text(col, y, "на тебе", S, BAD)
	else:
		_text(col, y, "нет", S, OFF)
	_text(col + 84, y, "пила:", S, DIM)
	_text(col + 124, y, "да ×2" if p.get("saw", false) else "нет", S, ACCENT if p.get("saw", false) else OFF)
	y += lh
	_text(x, y, "дилер брал:", S, DIM)
	var used: Dictionary = p.get("dealer_used", {})
	_text(col, y, _items(used), S, TEXT if not used.is_empty() else OFF, right - col)
	return r.end.y


# The AI's card: its move, the chance, the best moves as bars (yellow = its pick, grey = the next ones) with
# the spread of the neighbouring networks as error bars. While the dealer plays it keeps the last move, faded.
func _card(at: Vector2) -> void:
	var lh := _lh(S)
	var r := Rect2(at, Vector2(RIGHT_W, PAD * 2 + _lh(SMALL) * 3 + _lh(BIG) + 12 + lh * 2))
	var waiting := str(thought.get("move", "")) == ""
	var t: Dictionary = shown if waiting else thought
	ink = 1.0
	_box(r)
	var x := at.x + PAD
	var right := r.end.x - PAD
	var inner := RIGHT_W - 2 * PAD
	var y := at.y + PAD
	_text(x, y, "ИИ · " + ("АВТО" if ui.get("auto", false) else "ПОШАГОВО"), SMALL, DIM)
	_text_r(right, y, "×%s" % _num(ui.get("speed", 1.0)), SMALL, DIM)
	y += _lh(SMALL)
	ink = 0.45 if waiting else 1.0
	var bars: Array = t.get("bars", [])
	if not bars.is_empty():
		var best: Array = bars[0]
		var move := str(t.get("move", best[0]))
		var w := _text(x, y, move, BIG, ACCENT, inner - 50)
		if t.has("steal"):
			_text(x + w + 4, y + 2, "(" + str(t["steal"]) + ")", S, TEXT, inner - 50 - w - 4)
		_text_r(right, y, str(best[4]), BIG, TEXT)
		y += _lh(BIG)
		_bar(x, y - 2, inner, float(best[1]), ACCENT, float(best[2]), float(best[3]), 5.0)
		y += 12
		for i in range(1, 3):
			if i < bars.size():
				var b: Array = bars[i]
				_text(x, y, str(b[0]), S, DIM, 96)
				_bar(x + 100, y, inner - 100 - 36, float(b[1]), BAR_GREY, float(b[2]), float(b[3]))
				_text_r(right, y, str(b[4]), S, DIM)
			y += lh
	else:
		_text(x, y, str(thought.get("status", "")), BIG, TEXT, inner)
		y += _lh(BIG) + 12 + lh * 2
	ink = 1.0
	if waiting:
		var status := str(thought.get("status", ""))
		_text(x, y, status if status != "" else "жду своего хода…", SMALL, DIM, inner)
	elif ui.get("auto", false):
		_text(x, y, "[пробел] пауза", SMALL, DIM, inner)
	else:
		_text(x, y, "[пробел] сделать ход", SMALL, ACCENT, inner)
	y += _lh(SMALL)
	_text(x, y, "[I] почему   [N] сеть   [~] консоль", SMALL, DIM, inner)


# Why the network picks its move: what on this table pushed it up (green) or down (red) compared with a usual
# table, grouped, with the coefficient in the move's units (points of the chance). Your and the dealer's
# items at the bottom in small type.
func _why(top: float, bottom: float, vp: Vector2) -> void:
	var p := public
	var lh := _lh(S)
	var slh := _lh(SMALL)
	var rows := 9
	var h := PAD * 2 + slh * 2 + lh * rows
	var y0 := clampf(vp.y * 0.5 - h * 0.5, top, maxf(top, bottom - h))
	var r := Rect2(M, y0, WHY_W, h)
	_box(r)
	var x := M + PAD
	var right := r.end.x - PAD - ITEMS_W - 10   # the reasons; the item table is to the right of them
	var inner := right - x
	var y := y0 + PAD
	var w: Dictionary = _now().get("why", {})
	var move := str(_now().get("move", ""))
	_text(x, y, "почему «%s»" % move if move != "" else "почему", SMALL, DIM, inner - 20)
	_text_r(r.end.x - PAD, y, "[I]", SMALL, DIM)
	y += slh
	var reasons: Array = w.get("reasons", [])
	# group them: the strongest group first, inside a group the strongest reason first
	var groups := {}
	var order := []
	for rr in reasons:
		if not groups.has(rr[0]):
			groups[rr[0]] = []
			order.append(rr[0])
		groups[rr[0]].append(rr)
	var top_coef := 0.0001
	for rr in reasons:
		top_coef = maxf(top_coef, absf(float(rr[2])))
	var listed := 0.0
	var k := 0
	var bar_x := x + 168
	var half := 20.0
	for g in order:
		var first := true
		for rr in groups[g]:
			if k >= rows:
				break
			if first:
				_text(x, y, str(g), SMALL, DIM, 70)
			first = false
			_text(x + 74, y, str(rr[1]), S, TEXT, 100)
			var c := float(rr[2])
			listed += c
			var bar_len := half * absf(c) / top_coef
			_rect(Rect2(bar_x + half, y + 3, 1, 8), Color(DIM, 0.5))
			if c >= 0:
				_rect(Rect2(bar_x + half + 1, y + 4, bar_len, 6), GOOD)
			else:
				_rect(Rect2(bar_x + half - bar_len, y + 4, bar_len, 6), BAD)
			_text_r(right, y, "%+.2f" % c, S, GOOD if c >= 0 else BAD)
			y += lh
			k += 1
	if reasons.is_empty():
		_text(x, y, "сейчас не твой ход" if move == "" else "нет данных для этой модели", S, OFF, inner)
	y = y0 + PAD + slh + lh * rows
	if not w.is_empty():
		# whatever didn't fit in the rows counts as "the rest", so the line always adds up
		var rest: float = float(w.get("total", 0.0)) - float(w.get("base", 0.0)) - listed
		_text(x, y, "обычный стол %.2f  + причины %+.2f  + прочее %+.2f  = %.2f" % [w.get("base", 0.0), listed, rest,
			  w.get("total", 0.0)], SMALL, DIM, r.end.x - PAD - x)
	# items, small: one row per item, your count and the dealer's
	var ix := r.end.x - PAD - ITEMS_W
	var iy := y0 + PAD
	_rect(Rect2(ix - 6, iy, 1, slh + lh * rows - 4), Color(DIM, 0.25))
	_text(ix, iy, "предмет", SMALL, DIM)
	_text_r(ix + ITEMS_W - 30, iy, "ты", SMALL, DIM)
	_text_r(ix + ITEMS_W, iy, "дил", SMALL, DIM)
	iy += slh
	if p.is_empty():
		return
	var step := lh * rows / ITEMS.size()
	for i in range(ITEMS.size()):
		var mine := int(p.get("items_player", {}).get(ITEMS[i], 0))
		var theirs := int(p.get("items_dealer", {}).get(ITEMS[i], 0))
		var cy := iy + i * step
		_text(ix, cy, _name(ITEMS[i]), SMALL, TEXT if mine + theirs > 0 else OFF, ITEMS_W - 46)
		_text_r(ix + ITEMS_W - 30, cy, str(mine), SMALL, TEXT if mine > 0 else OFF)
		_text_r(ix + ITEMS_W, cy, str(theirs), SMALL, TEXT if theirs > 0 else OFF)


func _net(r: Rect2) -> void:
	_box(r)
	var net: Dictionary = _now().get("net", {})
	var layers: Array = net.get("layers", [])
	var x := r.position.x + PAD
	_text(x, r.position.y + PAD, "НЕЙРОСЕТЬ", SMALL, DIM)
	var sizes := []
	for l in layers:
		sizes.append(str(l.size()))
	_text_r(r.end.x - PAD, r.position.y + PAD, " → ".join(sizes) + "   [N]", SMALL, DIM)
	if layers.size() != 4:
		return
	var top := r.position.y + PAD + _lh(SMALL)
	var area_h := r.end.y - PAD - top
	# columns of dots: input, hidden 1, hidden 2, moves; brightness = how strongly it fires
	var cols := [5, 4, 4, 1]
	var xs := [x, x + 56, x + 100, x + 144]
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
		_text(at.x + 8, at.y - 6, str(_now().get("move", "")), SMALL, ACCENT, r.end.x - PAD - at.x - 8)


func _dev(vp: Vector2) -> void:
	var lh := _lh(S)
	var h := PAD * 2 + lh * (4 + 7 + 1)
	var r := Rect2(vp.x - M - DEV_W, vp.y - M - h, DEV_W, h)
	_rect(r, Color(0.02, 0.02, 0.02, 0.92))
	_rect(r, ACCENT, false)
	var x := r.position.x + PAD
	var inner := DEV_W - 2 * PAD
	var y := r.position.y + PAD
	_text(x, y, "РЕЖИМ РАЗРАБОТЧИКА", S, ACCENT)
	_text_r(r.end.x - PAD, y, "[~] закрыть", SMALL, DIM)
	y += lh
	for b in [["F2", "panel_i", "I — почему"], ["F3", "panel_n", "N — нейросеть"]]:
		var on: bool = ui.get(b[1], false)
		_text(x, y, "[%s] [%s]  %s" % ["x" if on else " ", b[0], b[2]], S, TEXT if on else DIM)
		y += lh
	var w := _text(x, y, "модель: ", S, DIM)
	_text(x + w, y, model_current if model_current != "" else "—", S, TEXT, inner - w - 120)
	_text_r(r.end.x - PAD, y, "[PgUp] [PgDn] сменить", SMALL, DIM)
	y += lh
	for line in console_log:
		_text(x, y, line, S, DIM, inner)
		y += lh
	y = r.end.y - PAD - lh
	var cursor := "_" if int(Time.get_ticks_msec() / 500) % 2 == 0 else " "
	_text(x, y, "> " + console_line + cursor, S, TEXT, inner)


const ACH_PRIZE := 1000000


# Rounds to win for a prize over 1 000 000: each cycle of 3 rounds doubles the first prize.
func _rounds_for_million(first: int) -> int:
	if first <= 0:
		return -1
	var k := 0
	while first * pow(2, k) <= ACH_PRIZE:
		k += 1
	return 3 * (k + 1)


func _money(n: int) -> String:
	var t := str(n)
	var out := ""
	while t.length() > 3:
		out = " " + t.substr(t.length() - 3) + out
		t = t.substr(0, t.length() - 3)
	return t + out


func _num(x) -> String:
	return str(int(x)) if float(x) == floorf(float(x)) else "%.1f" % float(x)

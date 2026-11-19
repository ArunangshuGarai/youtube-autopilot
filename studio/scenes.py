"""Backgrounds, set pieces, effects, camera and word-synced captions for the stick-figure studio."""
import math
import os
import random
import cairo
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .stickman import (W, H, GROUND_Y, INK, WHITE, Figure, solve_pose, ease, ease_out_back, rect, circle,
                       poly, line, outlined_box, vgrad, mix, shade, _rgb)

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
FONT_CAPTION = os.path.join(ASSETS, "Anton-Regular.ttf")
FONT_COMIC = os.path.join(ASSETS, "Bangers-Regular.ttf")
FALLBACK_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# ============================================================================= text -> cairo surfaces
_TEXT_CACHE = {}

def _font(path, size):
    for p in (path, FALLBACK_FONT):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()

def pil_to_surface(img):
    arr = np.array(img.convert("RGBA"), dtype=np.uint8)
    a = arr[..., 3:4].astype(np.float32) / 255.0
    arr[..., :3] = (arr[..., :3].astype(np.float32) * a).astype(np.uint8)       # premultiply
    bgra = arr[..., [2, 1, 0, 3]].copy()
    surf = cairo.ImageSurface.create_for_data(bytearray(bgra.tobytes()), cairo.FORMAT_ARGB32, img.width, img.height, img.width * 4)
    return surf

def text_surface(parts, size, font_path=FONT_CAPTION, stroke=10, max_width=None, shadow=True):
    """parts: list of (text, (r,g,b)) laid out on one line. Returns (surface, w, h). Cached."""
    key = (tuple(parts), size, font_path, stroke, max_width)
    if key in _TEXT_CACHE:
        return _TEXT_CACHE[key]
    sz = size
    while True:
        font = _font(font_path, sz)
        widths = [font.getlength(t + " ") for t, _ in parts]
        total = sum(widths) - font.getlength(" ")
        if max_width is None or total + stroke * 2 <= max_width or sz <= 40:
            break
        sz -= 4
    asc, desc = font.getmetrics()
    pad = stroke + 6
    img = Image.new("RGBA", (int(total) + pad * 2, asc + desc + pad * 2 + (8 if shadow else 0)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = pad
    for (t, col), wd in zip(parts, widths):
        c = tuple(int(v * 255) for v in col)
        if shadow:
            d.text((x + 3, pad + 8), t, font=font, fill=(0, 0, 0, 150), stroke_width=stroke, stroke_fill=(0, 0, 0, 150))
        d.text((x, pad), t, font=font, fill=c, stroke_width=stroke, stroke_fill=(10, 10, 12, 255))
        x += wd
    res = (pil_to_surface(img), img.width, img.height)
    _TEXT_CACHE[key] = res
    return res

# ============================================================================= backgrounds
def _bricks(ctx, x0, y0, x1, y1, col, mortar, bw=90, bh=42, seed=1):
    rect(ctx, x0, y0, x1 - x0, y1 - y0, mortar)
    rnd = random.Random(seed)
    row = 0
    y = y0
    while y < y1:
        off = (bw / 2) if row % 2 else 0
        x = x0 - off
        while x < x1:
            rect(ctx, x + 3, y + 3, bw - 6, bh - 6, shade(col, 0.85 + rnd.random() * 0.3))
            x += bw
        y += bh
        row += 1

def _windows(ctx, x, y, w, h, cols, rows, lit_prob, seed, lit="#ffd86b", dark="#27324a"):
    rnd = random.Random(seed)
    gw, gh = w / (cols * 1.6), h / (rows * 1.5)
    for r in range(rows):
        for c in range(cols):
            wx = x + (c + 0.3) * w / cols
            wy = y + (r + 0.25) * h / rows
            rect(ctx, wx, wy, gw, gh, lit if rnd.random() < lit_prob else dark)

def _skyline(ctx, y_base, color, seed, hmin=260, hmax=760, win=True, lit_prob=.4):
    rnd = random.Random(seed)
    x = -40
    while x < W + 40:
        bw = rnd.randint(110, 230)
        bh = rnd.randint(hmin, hmax)
        rect(ctx, x, y_base - bh, bw, bh + 4, color)
        if win:
            _windows(ctx, x + 10, y_base - bh + 20, bw - 20, bh - 40, 3, max(3, bh // 90), lit_prob, rnd.randint(0, 9999))
        x += bw + rnd.randint(-10, 18)

def bg_room(ctx, wall="#d9b99b", floor="#8a5a3b", seed=2):
    vgrad(ctx, 0, GROUND_Y, shade(wall, 1.08), shade(wall, 0.92))
    for i in range(0, W, 120):
        rect(ctx, i, 0, 4, GROUND_Y, shade(wall, 0.9), 0.35)
    rect(ctx, 0, GROUND_Y - 230, W, 14, shade(wall, 0.78))                       # chair rail
    rect(ctx, 0, GROUND_Y - 230 + 14, W, 230 - 14, shade(wall, 0.88), 0.55)      # wainscot
    vgrad(ctx, GROUND_Y, H, floor, shade(floor, 0.7))
    rect(ctx, 0, GROUND_Y - 26, W, 26, shade(wall, 0.7))                         # baseboard
    for i in range(-2, 14):                                                      # floorboards
        line(ctx, (W / 2 + (i - 6) * 40, GROUND_Y), (W / 2 + (i - 6) * 180, H), shade(floor, 0.75), 4)
    outlined_box(ctx, 90, 330, 300, 380, "#9fd8ff", lw=10)                       # window
    rect(ctx, 236, 330, 8, 380, INK); rect(ctx, 90, 515, 300, 8, INK)
    outlined_box(ctx, 720, 380, 220, 280, shade(wall, .8), lw=10)                # picture
    circle(ctx, 830, 480, 38, "#e6c15c"); poly(ctx, [(740, 640), (830, 520), (920, 640)], "#6aa56a")

def bg_office(ctx):
    bg_room(ctx, "#9fb4c7", "#4d5a6b")
    rect(ctx, 90, 330, 300, 380, "#7aa7d4")
    for i in range(10):
        rect(ctx, 90, 330 + i * 38, 300, 20, "#e8eef5", .85)

def bg_kitchen(ctx):
    bg_room(ctx, "#f2e6c8", "#c9c2b0")
    for i in range(0, W, 90):
        line(ctx, (i, 330), (i, GROUND_Y - 230), "#d6c9a6", 3)
    rect(ctx, 0, GROUND_Y - 230, W, 14, "#b9a77a")

def bg_street(ctx, night=False):
    vgrad(ctx, 0, GROUND_Y, "#79c7f2", "#d6f0ff")
    circle(ctx, 880, 300, 90, "#fff3a8", .9)
    _skyline(ctx, GROUND_Y - 60, "#9db4cc", 7, 300, 800, True, .15)
    _skyline(ctx, GROUND_Y - 40, "#6f87a3", 11, 200, 520, True, .2)
    rect(ctx, 0, GROUND_Y - 60, W, 60, "#b8b8bf")                                 # sidewalk
    vgrad(ctx, GROUND_Y, H, "#4a4d57", "#2d2f36")                                  # road
    for i in range(0, W, 220):
        rect(ctx, i + 20, GROUND_Y + 230, 120, 16, "#f4d03f")

def bg_night_street(ctx):
    vgrad(ctx, 0, GROUND_Y, "#0c1230", "#2a2f66")
    rnd = random.Random(5)
    for _ in range(70):
        circle(ctx, rnd.randint(0, W), rnd.randint(0, 700), rnd.choice([2, 3, 4]), "#ffffff", rnd.random() * .8)
    circle(ctx, 840, 300, 100, "#f7f2cf"); circle(ctx, 815, 285, 100, "#0e1535")
    circle(ctx, 840, 300, 150, "#f7f2cf", .08)
    _skyline(ctx, GROUND_Y - 60, "#141a3d", 3, 380, 980, True, .35)
    _skyline(ctx, GROUND_Y - 40, "#0e1330", 9, 220, 560, True, .45)
    rect(ctx, 0, GROUND_Y - 60, W, 60, "#2a2d45")
    vgrad(ctx, GROUND_Y, H, "#1a1c2b", "#0b0c14")
    for i in range(0, W, 220):
        rect(ctx, i + 20, GROUND_Y + 230, 120, 14, "#8f8460")
    # lamp post with glow
    rect(ctx, 180, GROUND_Y - 640, 16, 640, "#10131f")
    g = cairo.RadialGradient(188, GROUND_Y - 640, 8, 188, GROUND_Y - 640, 420)
    g.add_color_stop_rgba(0, 1, .9, .55, .65); g.add_color_stop_rgba(1, 1, .9, .55, 0)
    ctx.set_source(g); ctx.rectangle(0, 0, W, H); ctx.fill()
    circle(ctx, 188, GROUND_Y - 650, 22, "#ffe08a")

def bg_alley(ctx):
    _bricks(ctx, 0, 0, W, GROUND_Y, "#7a4034", "#2d1a17", seed=4)
    vgrad(ctx, GROUND_Y, H, "#2b2b31", "#0f0f13")
    rect(ctx, 700, GROUND_Y - 250, 330, 250, "#2f6b4a"); rect(ctx, 690, GROUND_Y - 270, 350, 36, "#244f38")   # dumpster
    for i in range(4):
        rect(ctx, 150 + i * 16, 220, 8, 700, "#3a3a44")                                                      # pipes
    circle(ctx, 300, GROUND_Y + 120, 90, "#3d5a7a", .35)                                                      # puddle

def bg_rooftop(ctx):
    vgrad(ctx, 0, GROUND_Y, "#ff9a5c", "#ffd9a0")
    circle(ctx, 540, 760, 160, "#fff1c0", .9)
    _skyline(ctx, GROUND_Y - 80, "#7a4d6e", 1, 300, 900, False)
    _skyline(ctx, GROUND_Y - 50, "#3a2748", 6, 200, 600, False)
    rect(ctx, 0, GROUND_Y - 40, W, 40, "#4a3a55")
    vgrad(ctx, GROUND_Y, H, "#5b5566", "#2b2833")
    rect(ctx, 0, GROUND_Y - 20, W, 20, "#2b2833")

def bg_forest(ctx):
    vgrad(ctx, 0, GROUND_Y, "#bfe8c4", "#e9f7d2")
    rnd = random.Random(8)
    for layer, (col, base) in enumerate([("#6aa56a", 1220), ("#3f7f4c", 1290), ("#25583a", GROUND_Y)]):
        x = -60
        while x < W + 60:
            h = rnd.randint(380, 760) - layer * 60
            rect(ctx, x + 20, base - h, 36, h, "#4a3424" if layer < 2 else "#2a1d14")
            circle(ctx, x + 38, base - h, rnd.randint(90, 130) - layer * 8, col)
            circle(ctx, x + 10, base - h + 40, 80, col)
            circle(ctx, x + 70, base - h + 40, 80, col)
            x += rnd.randint(150, 260)
    vgrad(ctx, GROUND_Y, H, "#3f6b3a", "#1f3a22")

def bg_desert(ctx):
    vgrad(ctx, 0, GROUND_Y, "#ffcf7a", "#ffe9b8")
    circle(ctx, 780, 420, 120, "#fff6d6")
    for i, (c, y, a) in enumerate([("#e8b36b", 1180, 70), ("#d99a54", 1260, 90), ("#c98644", GROUND_Y, 60)]):
        ctx.set_source_rgb(*_rgb(c)); ctx.move_to(0, y)
        for x in range(0, W + 60, 60):
            ctx.line_to(x, y - a * math.sin(x / 190 + i * 2))
        ctx.line_to(W, H); ctx.line_to(0, H); ctx.close_path(); ctx.fill()
    vgrad(ctx, GROUND_Y, H, "#d99a54", "#a8682f")
    rect(ctx, 880, GROUND_Y - 280, 36, 280, "#3f8f4c"); rect(ctx, 840, GROUND_Y - 200, 40, 14, "#3f8f4c"); rect(ctx, 840, GROUND_Y - 214, 14, 60, "#3f8f4c")

def bg_cell(ctx):
    _bricks(ctx, 0, 0, W, GROUND_Y, "#8c8f96", "#5a5d63", bw=150, bh=80, seed=6)
    vgrad(ctx, GROUND_Y, H, "#55575d", "#25262a")
    outlined_box(ctx, 780, 300, 200, 160, "#a8d4f0", lw=10)
    for i in range(4):
        rect(ctx, 800 + i * 44, 300, 10, 160, INK)

def bg_vault(ctx):
    vgrad(ctx, 0, GROUND_Y, "#5c6672", "#3d4550")
    for i in range(0, W, 270):
        rect(ctx, i, 0, 8, GROUND_Y, "#2c333b")
        for j in range(0, GROUND_Y, 160):
            circle(ctx, i + 20, j + 40, 6, "#8a95a3")
    vgrad(ctx, GROUND_Y, H, "#2f353d", "#14171b")
    g = cairo.RadialGradient(W / 2, 400, 20, W / 2, 400, 700)
    g.add_color_stop_rgba(0, 1, 1, .9, .22); g.add_color_stop_rgba(1, 1, 1, .9, 0)
    ctx.set_source(g); ctx.rectangle(0, 0, W, GROUND_Y); ctx.fill()

def bg_stage(ctx, color="#a5aa96"):
    """Minimalist Rico Animations sage-paper / Avenu warm-grey paper canvas with subtle sketch vignette."""
    vgrad(ctx, 0, H, shade(color, 1.03), shade(color, 0.92))
    # Subtle hand-drawn horizon pencil line
    line(ctx, (0, GROUND_Y - 10), (W, GROUND_Y + 8), INK, 6)

SETTINGS = {
    "room": bg_room, "office": bg_office, "kitchen": bg_kitchen, "street": bg_street,
    "night_street": bg_night_street, "alley": bg_alley, "rooftop": bg_rooftop, "forest": bg_forest,
    "desert": bg_desert, "cell": bg_cell, "vault": bg_vault, "stage": bg_stage,
}

# ============================================================================= set pieces (x = centre, standing on ground)
def sp_door(ctx, x, g, s=1.0):
    outlined_box(ctx, x - 130 * s, g - 470 * s, 260 * s, 470 * s, "#9b6a3c", lw=9, r=6)
    outlined_box(ctx, x - 95 * s, g - 430 * s, 190 * s, 160 * s, "#8a5b30", lw=6, r=4)
    outlined_box(ctx, x - 95 * s, g - 240 * s, 190 * s, 190 * s, "#8a5b30", lw=6, r=4)
    circle(ctx, x + 90 * s, g - 230 * s, 14 * s, "#e5c35c")

def sp_safe(ctx, x, g, s=1.0):
    outlined_box(ctx, x - 150 * s, g - 340 * s, 300 * s, 340 * s, "#59606b", lw=10, r=10)
    outlined_box(ctx, x - 118 * s, g - 306 * s, 236 * s, 272 * s, "#7b8491", lw=6, r=6)
    circle(ctx, x, g - 170 * s, 54 * s, "#c9ced6"); ctx.set_source_rgb(*INK); ctx.set_line_width(7); ctx.arc(x, g - 170 * s, 54 * s, 0, math.tau); ctx.stroke()
    for a in range(0, 360, 60):
        line(ctx, (x, g - 170 * s), (x + 44 * s * math.cos(math.radians(a)), g - 170 * s + 44 * s * math.sin(math.radians(a))), INK, 6)

def sp_table(ctx, x, g, s=1.0):
    outlined_box(ctx, x - 190 * s, g - 190 * s, 380 * s, 30 * s, "#a8794a", lw=8, r=4)
    rect(ctx, x - 170 * s, g - 160 * s, 24 * s, 160 * s, "#7a5232"); rect(ctx, x + 146 * s, g - 160 * s, 24 * s, 160 * s, "#7a5232")

def sp_desk(ctx, x, g, s=1.0):
    outlined_box(ctx, x - 220 * s, g - 220 * s, 440 * s, 34 * s, "#7a5a3a", lw=8, r=4)
    outlined_box(ctx, x - 210 * s, g - 186 * s, 150 * s, 186 * s, "#6a4b30", lw=8, r=4)
    outlined_box(ctx, x + 60 * s, g - 186 * s, 150 * s, 186 * s, "#6a4b30", lw=8, r=4)
    rect(ctx, x - 190 * s, g - 150 * s, 110 * s, 10 * s, INK, .4); rect(ctx, x + 80 * s, g - 150 * s, 110 * s, 10 * s, INK, .4)

def sp_car(ctx, x, g, s=1.0):
    outlined_box(ctx, x - 280 * s, g - 150 * s, 560 * s, 100 * s, "#d64545", lw=9, r=20)
    poly(ctx, [(x - 150 * s, g - 150 * s), (x - 90 * s, g - 250 * s), (x + 110 * s, g - 250 * s), (x + 190 * s, g - 150 * s)], "#d64545", stroke=INK, lw=9)
    poly(ctx, [(x - 120 * s, g - 158 * s), (x - 78 * s, g - 232 * s), (x + 10 * s, g - 232 * s), (x + 10 * s, g - 158 * s)], "#aee0ff")
    poly(ctx, [(x + 30 * s, g - 158 * s), (x + 30 * s, g - 232 * s), (x + 100 * s, g - 232 * s), (x + 160 * s, g - 158 * s)], "#aee0ff")
    for wx in (x - 160 * s, x + 160 * s):
        circle(ctx, wx, g - 50 * s, 52 * s, INK); circle(ctx, wx, g - 50 * s, 24 * s, "#c9ced6")

def sp_bed(ctx, x, g, s=1.0):
    outlined_box(ctx, x - 230 * s, g - 150 * s, 460 * s, 110 * s, "#6c8fd1", lw=9, r=10)
    outlined_box(ctx, x - 230 * s, g - 230 * s, 40 * s, 190 * s, "#7a5232", lw=8, r=4)
    outlined_box(ctx, x - 190 * s, g - 180 * s, 120 * s, 40 * s, "#f2f2f2", lw=7, r=14)

def sp_couch(ctx, x, g, s=1.0):
    outlined_box(ctx, x - 230 * s, g - 220 * s, 460 * s, 120 * s, "#8a4f9c", lw=9, r=18)
    outlined_box(ctx, x - 250 * s, g - 150 * s, 500 * s, 110 * s, "#9d5fb0", lw=9, r=18)
    rect(ctx, x - 220 * s, g - 40 * s, 24 * s, 40 * s, INK); rect(ctx, x + 196 * s, g - 40 * s, 24 * s, 40 * s, INK)

def sp_bars(ctx, x, g, s=1.0):
    for i in range(-5, 6):
        rect(ctx, x + i * 96 * s - 9 * s, g - 760 * s, 18 * s, 760 * s, "#2c2f36")
    rect(ctx, x - 500 * s, g - 760 * s, 1000 * s, 24 * s, "#2c2f36"); rect(ctx, x - 500 * s, g - 420 * s, 1000 * s, 20 * s, "#2c2f36")

def sp_tv(ctx, x, g, s=1.0):
    outlined_box(ctx, x - 190 * s, g - 420 * s, 380 * s, 250 * s, "#20232b", lw=9, r=10)
    rect(ctx, x - 170 * s, g - 400 * s, 340 * s, 210 * s, "#7fd1ff")
    rect(ctx, x - 40 * s, g - 170 * s, 80 * s, 30 * s, "#20232b")

def sp_vault(ctx, x, g, s=1.0):
    circle(ctx, x, g - 330 * s, 300 * s, "#6a7480"); ctx.set_source_rgb(*INK); ctx.set_line_width(12); ctx.arc(x, g - 330 * s, 300 * s, 0, math.tau); ctx.stroke()
    circle(ctx, x, g - 330 * s, 230 * s, "#8b95a3"); circle(ctx, x, g - 330 * s, 70 * s, "#c9ced6")
    for a in range(0, 360, 45):
        line(ctx, (x, g - 330 * s), (x + 210 * s * math.cos(math.radians(a)), g - 330 * s + 210 * s * math.sin(math.radians(a))), "#4e5762", 18 * s)

def sp_tree(ctx, x, g, s=1.0):
    rect(ctx, x - 26 * s, g - 360 * s, 52 * s, 360 * s, "#6a4a2c"); circle(ctx, x, g - 420 * s, 150 * s, "#3f8f4c"); circle(ctx, x - 90 * s, g - 360 * s, 100 * s, "#4aa05a"); circle(ctx, x + 90 * s, g - 360 * s, 100 * s, "#4aa05a")

def sp_fridge(ctx, x, g, s=1.0):
    outlined_box(ctx, x - 110 * s, g - 520 * s, 220 * s, 520 * s, "#e6ecef", lw=9, r=10)
    rect(ctx, x - 110 * s, g - 330 * s, 220 * s, 8 * s, INK); rect(ctx, x + 70 * s, g - 450 * s, 12 * s, 80 * s, "#8a8f98"); rect(ctx, x + 70 * s, g - 290 * s, 12 * s, 100 * s, "#8a8f98")

def sp_wardrobe(ctx, x, g, s=1.0):
    outlined_box(ctx, x - 170 * s, g - 560 * s, 340 * s, 560 * s, "#9b6a3c", lw=9, r=6)
    rect(ctx, x - 4 * s, g - 560 * s, 8 * s, 560 * s, INK)
    circle(ctx, x - 24 * s, g - 280 * s, 10 * s, "#e5c35c"); circle(ctx, x + 24 * s, g - 280 * s, 10 * s, "#e5c35c")

def sp_bench(ctx, x, g, s=1.0):
    outlined_box(ctx, x - 200 * s, g - 150 * s, 400 * s, 26 * s, "#a8794a", lw=7, r=3)
    outlined_box(ctx, x - 200 * s, g - 250 * s, 400 * s, 70 * s, "#a8794a", lw=7, r=3)
    rect(ctx, x - 170 * s, g - 124 * s, 18 * s, 124 * s, "#2c2f36"); rect(ctx, x + 152 * s, g - 124 * s, 18 * s, 124 * s, "#2c2f36")

def sp_chair(ctx, x, g, s=1.0):
    outlined_box(ctx, x - 90 * s, g - 124 * s, 190 * s, 20 * s, "#8a5b30", lw=7, r=3)
    outlined_box(ctx, x - 100 * s, g - 330 * s, 22 * s, 210 * s, "#8a5b30", lw=7, r=3)
    rect(ctx, x - 80 * s, g - 104 * s, 14 * s, 104 * s, "#6a4527"); rect(ctx, x + 70 * s, g - 104 * s, 14 * s, 104 * s, "#6a4527")

SET_PIECES = {   # name -> (fn, drawn_in_front_of_characters)
    "door": (sp_door, False), "safe": (sp_safe, False), "table": (sp_table, True), "desk": (sp_desk, True),
    "car": (sp_car, False), "bed": (sp_bed, True), "couch": (sp_couch, False), "bars": (sp_bars, True),
    "tv": (sp_tv, False), "vault_door": (sp_vault, False), "tree": (sp_tree, False), "fridge": (sp_fridge, False),
    "wardrobe": (sp_wardrobe, False), "bench": (sp_bench, False), "chair": (sp_chair, False),
}

# ============================================================================= effects (screen-space helpers)
def fx_text(ctx, txt, x, y, size, color, rot=0.0, scale=1.0):
    ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.scale(scale, scale)
    ctx.select_font_face("DejaVu Sans", 0, 1); ctx.set_font_size(size)
    ext = ctx.text_extents(txt)
    ctx.move_to(-ext.width / 2, ext.height / 2); ctx.text_path(txt)
    ctx.set_source_rgb(*INK); ctx.set_line_width(size * .22); ctx.set_line_join(cairo.LINE_JOIN_ROUND); ctx.stroke_preserve()
    ctx.set_source_rgb(*_rgb(color)); ctx.fill(); ctx.restore()

def fx_exclaim(ctx, x, y, t, mark="!"):
    k = ease_out_back(min(1, t / 0.22))
    fx_text(ctx, mark, x, y - 40 * k, 150, "#ffd23f", rot=math.radians(-8), scale=k)

def fx_sweat(ctx, x, y, t):
    for i in range(3):
        ph = (t * 1.4 + i / 3) % 1
        sx, sy = x + (i - 1) * 55, y + ph * 90
        ctx.save(); ctx.translate(sx, sy)
        ctx.move_to(0, -26); ctx.curve_to(18, 0, 14, 20, 0, 20); ctx.curve_to(-14, 20, -18, 0, 0, -26)
        ctx.set_source_rgba(.45, .8, 1, 1 - ph); ctx.fill(); ctx.restore()

def fx_anger(ctx, x, y, t):
    k = 1 + .12 * math.sin(t * 14)
    ctx.save(); ctx.translate(x, y); ctx.scale(k, k)
    ctx.set_source_rgb(.9, .15, .15); ctx.set_line_width(11); ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for ang in (45, 135, 225, 315):
        r = math.radians(ang)
        ctx.new_path(); ctx.arc(math.cos(r) * 22, math.sin(r) * 22, 17, r + math.pi * .6, r + math.pi * 1.4); ctx.stroke()
    ctx.restore()

def fx_zzz(ctx, x, y, t):
    for i in range(3):
        ph = (t * .6 + i / 3) % 1
        fx_text(ctx, "Z", x + ph * 80 + i * 12, y - ph * 140, 50 + i * 18, "#ffffff", scale=min(1, ph * 4) * (1 - ph * .3))

def fx_sparkle(ctx, x, y, t, n=5):
    rnd = random.Random(3)
    for i in range(n):
        ph = (t * 1.2 + rnd.random()) % 1
        sx, sy = x + rnd.uniform(-130, 130), y + rnd.uniform(-130, 90)
        r = 22 * math.sin(math.pi * ph)
        ctx.set_source_rgb(1, .93, .45)
        ctx.move_to(sx, sy - r); ctx.line_to(sx + r * .22, sy - r * .22); ctx.line_to(sx + r, sy); ctx.line_to(sx + r * .22, sy + r * .22)
        ctx.line_to(sx, sy + r); ctx.line_to(sx - r * .22, sy + r * .22); ctx.line_to(sx - r, sy); ctx.line_to(sx - r * .22, sy - r * .22); ctx.close_path(); ctx.fill()

def fx_speedlines(ctx, t, alpha=.55):
    rnd = random.Random(int(t * 24))
    cx, cy = W / 2, H * .5
    ctx.set_source_rgba(1, 1, 1, alpha); ctx.set_line_width(5)
    for _ in range(26):
        a = rnd.uniform(0, math.tau); r0 = rnd.uniform(520, 700); r1 = r0 + rnd.uniform(220, 520)
        ctx.move_to(cx + math.cos(a) * r0, cy + math.sin(a) * r0 * 1.5); ctx.line_to(cx + math.cos(a) * r1, cy + math.sin(a) * r1 * 1.5); ctx.stroke()

def fx_rain(ctx, t):
    rnd = random.Random(11)
    ctx.set_source_rgba(.75, .85, 1, .5); ctx.set_line_width(4)
    for _ in range(90):
        x = rnd.uniform(-100, W + 100); sp = rnd.uniform(1.4, 2.4); y0 = ((rnd.random() * H) + t * 1500 * sp) % (H + 200) - 100
        ctx.move_to(x, y0); ctx.line_to(x - 22, y0 + 70); ctx.stroke()


def fx_ambient(ctx, t, lighting):
    """Slow drifting particles so 'static' backgrounds never feel frozen: dust motes by day, fog + embers at night."""
    rnd = random.Random(21)
    if lighting in ("night", "dark"):
        for i in range(4):                                     # drifting fog bands
            y = 520 + i * 250 + 30 * math.sin(t * .5 + i)
            x = ((rnd.random() * W * 1.6) + t * (18 + i * 7)) % (W * 1.6) - W * .3
            g = cairo.RadialGradient(x, y, 10, x, y, 420)
            g.add_color_stop_rgba(0, .75, .8, .95, .10); g.add_color_stop_rgba(1, .75, .8, .95, 0)
            ctx.set_source(g); ctx.rectangle(0, 0, W, H); ctx.fill()
    for _ in range(26):
        x = (rnd.random() * W + t * rnd.uniform(6, 22)) % W
        y = (rnd.random() * H * .85 - t * rnd.uniform(4, 16)) % (H * .85)
        r = rnd.uniform(2, 5.5)
        a = (.20 if lighting in ("night", "dark") else .32) * (0.6 + 0.4 * math.sin(t * 1.5 + x))
        circle(ctx, x, y, r, "#fff6d0" if lighting not in ("night", "dark") else "#b8c4ff", a)

POPUP = {"boom": "BOOM!", "slam": "SLAM!", "hit": "WHAM!", "fail": "FAIL!", "cash": "$$$", "knock": "KNOCK KNOCK",
         "boing": "BOING!", "ding": "DING!", "record_scratch": "WAIT, WHAT?", "siren": "BUSTED!"}
POPUP_DARK = {"boom", "slam", "knock", "siren", "hit"}          # the only ones allowed in thriller / crime

def draw_popup(ctx, sfx, t, t_hit, genre):
    word = POPUP.get(sfx)
    if not word or (genre != "comedy" and sfx not in POPUP_DARK):
        return
    age = t - t_hit
    if not 0 <= age < 0.85:
        return
    k = ease_out_back(min(1, age / .16)) * (1 - max(0, (age - .55) / .3))
    col = (1.0, 0.86, 0.15) if genre == "comedy" else (1.0, 0.3, 0.22)
    surf, w, h = text_surface([(word, col)], 150, FONT_COMIC, stroke=14, max_width=820)
    ctx.save(); ctx.translate(W * .68, 700); ctx.rotate(math.radians(-9)); ctx.scale(max(k, .01), max(k, .01))
    ctx.set_source_surface(surf, -w / 2, -h / 2); ctx.paint(); ctx.restore()

def draw_hook_card(ctx, text, t):
    """First ~2.3s: the on-screen half of the hook (different words from the spoken line, per yt-shorts)."""
    if t > 2.5:
        return
    k = ease_out_back(min(1, t / .2))
    out = max(0.0, (t - 2.15) / .35)
    surf, w, h = text_surface([(text.upper(), (0.07, 0.07, 0.08))], 150, FONT_COMIC, stroke=0, shadow=False, max_width=860)
    ctx.save(); ctx.translate(W / 2, 330 - out * 400); ctx.rotate(math.radians(-2.5)); ctx.scale(.55 + .45 * k, .55 + .45 * k)
    outlined_box(ctx, -w / 2 - 34, -h / 2 - 22, w + 68, h + 44, "#ffd23f", lw=9, r=14)
    ctx.set_source_surface(surf, -w / 2, -h / 2 - 4); ctx.paint(); ctx.restore()

def draw_cta(ctx, text, t, dur):
    """Last ~2.6s: a pinned 'comment' that makes viewers pick a side (comments feed the algorithm, and it holds the loop)."""
    start = max(0.4, dur - 2.7)
    if not text or t < start:
        return
    k = ease_out_back(min(1, (t - start) / .3))
    words = text.split()
    half = max(1, len(words) // 2) if len(text) > 30 else len(words)
    lines = [" ".join(words[:half]), " ".join(words[half:])] if half < len(words) else [text]
    surfs = [text_surface([(ln, (0.07, 0.07, 0.08))], 62, FONT_COMIC, stroke=0, shadow=False, max_width=800) for ln in lines]
    bw = max(sf[1] for sf in surfs) + 150
    bh = sum(sf[2] for sf in surfs) + 70
    ctx.save(); ctx.translate(W / 2, 370); ctx.scale(.7 + .3 * k, .7 + .3 * k)
    outlined_box(ctx, -bw / 2, -bh / 2, bw, bh, "#ffffff", lw=7, r=26)
    circle(ctx, -bw / 2 + 62, 0, 30, "#ff3d3d"); circle(ctx, -bw / 2 + 62, -6, 11, "#ffffff"); circle(ctx, -bw / 2 + 62, 20, 17, "#ffffff", .9)
    y = -bh / 2 + 28
    for sf, w, h in surfs:
        ctx.set_source_surface(sf, -bw / 2 + 112, y); ctx.paint(); y += h
    ctx.restore()

# ============================================================================= director: draws one scene frame
LIGHT = {"day": None, "dusk": (0.35, 0.12, 0.28, 0.22), "night": (0.03, 0.06, 0.22, 0.5), "dark": (0.0, 0.0, 0.05, 0.62)}
HIT_SFX = {"hit", "boom", "sting", "slam", "crash"}

def _norm_cast(scene):
    out = []
    for i, c in enumerate(scene.get("cast", [])[:3]):
        x = float(c.get("x", [0.5, 0.3, 0.72][i] if len(scene.get("cast", [])) > 1 else 0.5))
        face_dir = c.get("facing", "right" if x < 0.5 else "left")
        out.append(dict(role=c.get("role", "hero"), pose=c.get("pose", "idle"), face=c.get("face", "neutral"),
                        x=min(max(x, 0.12), 0.88) * W, facing=-1 if str(face_dir).startswith("l") else 1,
                        prop=c.get("prop"), scale=float(c.get("scale", 1.08 if len(scene.get("cast", [])) > 1 else 1.28)),
                        fx=c.get("fx")))
    return out or [dict(role="hero", pose="idle", face="neutral", x=W / 2, facing=1, prop=None, scale=1.05, fx=None)]

def draw_scene(ctx, scene, t, dur, genre="thriller", punch=0.0):
    cast = _norm_cast(scene)
    setting = scene.get("setting", "room")
    lighting = scene.get("lighting") or ("night" if genre in ("thriller", "crime") else "day")
    bg = SETTINGS.get(setting, bg_room)
    cam = scene.get("camera", "push_in")
    k = t / max(dur, 0.1)

    # ----- camera
    fx0 = sum(c["x"] for c in cast) / len(cast)
    fy0 = 1000
    z, fx, fy, rot, shake = 1.04, fx0, fy0, 0.0, 0.0
    if cam == "push_in":
        z = 1.0 + 0.22 * ease(k)
    elif cam == "pull_out":
        z = 1.24 - 0.22 * ease(k)
    elif cam == "pan_left":
        z, fx = 1.14, fx0 + 110 - 220 * ease(k)
    elif cam == "pan_right":
        z, fx = 1.14, fx0 - 110 + 220 * ease(k)
    elif cam == "shake":
        z, shake = 1.10, 22 * math.exp(-t * 2.2) + 4
    elif cam == "dutch":
        z, rot = 1.17 + 0.12 * ease(k), math.radians(-4 + 2 * k)
    elif cam == "whip":
        z = 1.06 + 0.45 * math.exp(-t * 9)
    elif cam == "snap_zoom":
        z, fy = 1.55 + 0.55 * ease(min(1, t / 0.16)), 810   # Tight Rico/Avenu reaction close-up on the face!
    elif cam == "drift_up":
        z, fy = 1.12, fy0 + 150 - 300 * ease(k)
    sfx = scene.get("sfx", "none")
    t_hit = float(scene.get("sfx_at", 0.05))
    if sfx in HIT_SFX and t > t_hit:
        z *= 1 + 0.07 * math.exp(-(t - t_hit) * 9)
        shake = max(shake, 16 * math.exp(-(t - t_hit) * 8))
    z *= 1 + 0.055 * punch                                     # zoom punch on every stressed word
    z = max(z, 1.05)                                           # margin so shake/pans never show the world edge
    half_w, half_h = W / (2 * z) + 30, H / (2 * z) + 30
    fx = min(max(fx, half_w), W - half_w)
    fy = min(max(fy, half_h), H - half_h)
    rnd = random.Random(int(t * 30))
    sx, sy = (rnd.uniform(-1, 1) * shake, rnd.uniform(-1, 1) * shake) if shake else (0, 0)
    sx += 4 * math.sin(t * 1.7); sy += 3 * math.cos(t * 1.3)      # hand-held sway: nothing ever sits perfectly still

    ctx.save()
    ctx.translate(W / 2 + sx, H / 2 + sy); ctx.rotate(rot); ctx.scale(z, z); ctx.translate(-fx, -fy)
    bg(ctx) if setting != "stage" else bg_stage(ctx, scene.get("stage_color", "#2c3e66"))

    tint = LIGHT.get(lighting)
    sp = scene.get("set_piece") or {}
    sp_name = sp.get("name")
    sp_entry = SET_PIECES.get(sp_name)
    # auto chair for seated figures
    for c in cast:
        if c["pose"] in ("sit", "sit_talk") and not sp_entry:
            sp_chair(ctx, c["x"] - 6 * c["facing"], GROUND_Y, 1.0)
    if sp_entry and not sp_entry[1]:
        sp_entry[0](ctx, float(sp.get("x", .5)) * W, GROUND_Y, float(sp.get("scale", 1.0)))
    if tint:
        rect(ctx, -W, -200, W * 3, H + 400, tint[:3], tint[3])
        g = cairo.RadialGradient(fx0, 900, 40, fx0, 900, 760)           # warm key light on the action
        g.add_color_stop_rgba(0, 1, .93, .7, .20 if lighting != "dusk" else .1); g.add_color_stop_rgba(1, 1, .93, .7, 0)
        ctx.set_source(g); ctx.rectangle(-W, -200, W * 3, H + 400); ctx.fill()

    # ----- characters
    heads = []
    enter = ease_out_back(min(1, t / 0.28))
    for c in cast:
        fig = Figure(c["role"], c["scale"])
        a = solve_pose(c["pose"], t + (sum(map(ord, c["role"])) % 7) * 0.13, prev=None)
        fig.scale = c["scale"] * (0.9 + 0.1 * enter)
        fig.draw(ctx, c["x"], GROUND_Y, a, face=c["face"], facing=c["facing"], prop=c["prop"], t=t)
        hp = fig.head_world(c["x"], GROUND_Y, a, c["facing"])
        hw, _, _ = fig.hand_world(c["x"], GROUND_Y, a, c["facing"])
        heads.append((hp, hw, c))
    if sp_entry and sp_entry[1]:
        sp_entry[0](ctx, float(sp.get("x", .5)) * W, GROUND_Y, float(sp.get("scale", 1.0)))

    # ----- per-character effects (world space)
    for (hx, hy), (px, py), c in heads:
        for name in ([c["fx"]] if isinstance(c["fx"], str) else (c["fx"] or [])):
            if name == "exclaim": fx_exclaim(ctx, hx + 20, hy - 140, t, "!")
            elif name == "question": fx_exclaim(ctx, hx + 20, hy - 140, t, "?")
            elif name == "sweat": fx_sweat(ctx, hx - 90 * c["facing"], hy - 40, t)
            elif name == "anger": fx_anger(ctx, hx + 70 * c["facing"], hy - 100, t)
            elif name == "zzz": fx_zzz(ctx, hx + 70, hy - 80, t)
            elif name == "sparkle": fx_sparkle(ctx, px, py - 60, t)
    if scene.get("rain"):
        fx_rain(ctx, t)
    ctx.restore()

    # ----- screen-space finishing
    if scene.get("speedlines") or "run" in [c["pose"] for c in cast]:
        fx_speedlines(ctx, t, .35 if not scene.get("speedlines") else .55)
    flash = scene.get("transition", "cut")
    if flash == "flash" and t < .14:
        rect(ctx, 0, 0, W, H, "#ffffff", .75 * (1 - t / .14))
    if flash == "black" and t < .18:
        rect(ctx, 0, 0, W, H, "#000000", 1 - t / .18)
    if sfx in HIT_SFX and 0 <= t - t_hit < .07:
        rect(ctx, 0, 0, W, H, "#ffffff", .35)
    fx_ambient(ctx, t, lighting)
    # vignette
    g = cairo.RadialGradient(W / 2, H * .45, H * .28, W / 2, H * .45, H * .75)
    vig = .55 if genre in ("thriller", "crime") else .28
    g.add_color_stop_rgba(0, 0, 0, 0, 0); g.add_color_stop_rgba(1, 0, 0, 0, vig)
    ctx.set_source(g); ctx.rectangle(0, 0, W, H); ctx.fill()

    draw_popup(ctx, sfx, t, t_hit, genre)
    if scene.get("hook_card"):
        draw_hook_card(ctx, scene["hook_card"], t)
    if scene.get("cta"):
        draw_cta(ctx, scene["cta"], t, dur)

    # overlay stamp ("3:07 AM", "ONE WEEK LATER")
    ov = scene.get("overlay")
    if ov and not (scene.get("hook_card") and t < 2.6):        # the hook card owns the top of the frame for the first seconds
        slide = ease_out_back(min(1, t / .3))
        surf, w, h = text_surface([(str(ov).upper(), (0.07, 0.07, 0.08))], 74, FONT_COMIC, stroke=0, shadow=False, max_width=900)
        ctx.save(); ctx.translate(58 - (1 - slide) * 700, 190); ctx.rotate(math.radians(-3))
        outlined_box(ctx, -10, -8, w + 20, h + 8, "#ffd23f", lw=7, r=8)
        ctx.set_source_surface(surf, 0, -2); ctx.paint(); ctx.restore()

# ============================================================================= captions
YELLOW, WHITE_C, HOT = (1.0, 0.86, 0.15), (1.0, 1.0, 1.0), (1.0, 0.36, 0.22)

def chunk_words(words, max_words=3, max_chars=17):
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        txt = " ".join(x["text"] for x in cur)
        end_punct = w["text"][-1:] in ".,!?;:—"
        if len(cur) >= max_words or len(txt) >= max_chars or end_punct:
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)
    return chunks

def draw_caption(ctx, chunks, t, emphasis=(), y_center=1500):
    """chunks: list of lists of {text,start,end}. Draws the chunk active at time t with the spoken word highlighted."""
    active = None
    for i, ch in enumerate(chunks):
        nxt = chunks[i + 1][0]["start"] if i + 1 < len(chunks) else ch[-1]["end"] + .5
        if ch[0]["start"] - 0.03 <= t < min(nxt, ch[-1]["end"] + .45):
            active = ch
            break
    if not active:
        return
    parts = []
    for w in active:
        clean = w["text"].upper()
        base = HOT if w["text"].strip(".,!?;:").lower() in emphasis else WHITE_C
        parts.append((clean, YELLOW if (w["start"] - .02 <= t < w["end"] + .04) else base))
    surf, w, h = text_surface(parts, 128, FONT_CAPTION, stroke=11, max_width=960)
    since = t - active[0]["start"]
    stressed = any(w["text"].strip(".,!?;:").lower() in emphasis and w["start"] - .02 <= t < w["end"] + .04 for w in active)
    pop = 1.0 + 0.2 * max(0.0, 1 - since / 0.11) + (0.10 if stressed else 0.0)
    ctx.save(); ctx.translate(W / 2, y_center); ctx.scale(pop, pop)
    ctx.set_source_surface(surf, -w / 2, -h / 2); ctx.paint(); ctx.restore()

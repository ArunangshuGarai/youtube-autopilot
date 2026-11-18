"""Code-drawn stick-figure animation engine (pycairo). No image APIs, no cost, fully deterministic.

Coordinate system: 1080x1920 canvas, y grows downward. Character joint angles are measured from
"straight down" (0 deg), positive toward the direction the character faces:
    vec = (sin(theta), cos(theta))  ->  0 = down, 90 = forward, 180 = up, -90 = backward.
"""
import math
import random
import cairo

W, H = 1080, 1920
GROUND_Y = 1330
INK = (0.04, 0.04, 0.05)
WHITE = (0.97, 0.97, 0.95)

# ----------------------------------------------------------------------------- helpers
def _rgb(c):
    return c if isinstance(c, tuple) else tuple(int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))

def shade(c, f):
    c = _rgb(c)
    return tuple(max(0, min(1, v * f)) for v in c)

def mix(a, b, t):
    a, b = _rgb(a), _rgb(b)
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))

def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)

def ease_out_back(t):
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2

def pt(p, length, theta):
    r = math.radians(theta)
    return (p[0] + length * math.sin(r), p[1] + length * math.cos(r))

def vgrad(ctx, y0, y1, top, bottom, x0=0, x1=W):
    g = cairo.LinearGradient(0, y0, 0, y1)
    g.add_color_stop_rgb(0, *_rgb(top))
    g.add_color_stop_rgb(1, *_rgb(bottom))
    ctx.set_source(g)
    ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
    ctx.fill()

def rect(ctx, x, y, w, h, color, alpha=1.0):
    ctx.set_source_rgba(*_rgb(color), alpha)
    ctx.rectangle(x, y, w, h)
    ctx.fill()

def circle(ctx, x, y, r, color, alpha=1.0):
    ctx.set_source_rgba(*_rgb(color), alpha)
    ctx.arc(x, y, r, 0, math.tau)
    ctx.fill()

def poly(ctx, pts, color, alpha=1.0, stroke=None, lw=6):
    ctx.set_source_rgba(*_rgb(color), alpha)
    ctx.move_to(*pts[0])
    for p in pts[1:]:
        ctx.line_to(*p)
    ctx.close_path()
    if stroke:
        ctx.fill_preserve()
        ctx.set_source_rgb(*_rgb(stroke))
        ctx.set_line_width(lw)
        ctx.stroke()
    else:
        ctx.fill()

def line(ctx, a, b, color, lw):
    ctx.set_source_rgb(*_rgb(color))
    ctx.set_line_width(lw)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.move_to(*a)
    ctx.line_to(*b)
    ctx.stroke()

def outlined_box(ctx, x, y, w, h, fill, lw=7, r=10):
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.close_path()
    ctx.set_source_rgb(*_rgb(fill))
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(lw)
    ctx.stroke()

# ----------------------------------------------------------------------------- poses
# angle keys: torso lean, head tilt, upper arm (a*), forearm (e*), thigh (l*), shin (k*) - L = far side, R = near side
BASE = dict(torso=0, head=0, aL=-10, eL=-6, aR=10, eR=6, lL=-7, kL=-7, lR=7, kR=7, y=0, rot=0)

def _p(**kw):
    d = dict(BASE)
    d.update(kw)
    return d

def _walk(t, a, amp=28, speed=7.0, arm=26, lean=2):
    ph = t * speed
    s = math.sin(ph)
    a["lR"], a["lL"] = amp * s, -amp * s
    a["kR"], a["kL"] = amp * s - 10 - 14 * max(0, math.cos(ph)), -amp * s - 10 - 14 * max(0, -math.cos(ph))
    a["aR"], a["aL"] = -arm * s, arm * s
    a["eR"], a["eL"] = a["aR"] + 12, a["aL"] + 12
    a["torso"] = lean
    a["y"] = -abs(math.sin(ph)) * 6
    return a

def _run(t, a):
    a = _walk(t, a, amp=52, speed=13.0, arm=55, lean=16)
    a["eR"], a["eL"] = a["aR"] + 70, a["aL"] + 70
    a["y"] = -abs(math.sin(t * 13.0)) * 22
    return a

def _talk(t, a):
    a["aR"] = 38 + 22 * math.sin(t * 5.1)
    a["eR"] = 95 + 25 * math.sin(t * 5.1 + 1.0)
    a["head"] = 3 * math.sin(t * 2.6)
    return a

def _laugh(t, a):
    b = math.sin(t * 16)
    a["torso"] = -12 + 3 * b
    a["head"] = -10 + 4 * b
    a["y"] = -abs(b) * 10
    return a

def _dance(t, a):
    s, c = math.sin(t * 8), math.cos(t * 8)
    a["aR"], a["eR"] = 150 + 25 * s, 170 + 20 * s
    a["aL"], a["eL"] = -150 + 25 * c, -170 + 20 * c
    a["lR"], a["kR"] = 20 * s, 20 * s - 15
    a["lL"], a["kL"] = -20 * s, -20 * s - 15
    a["torso"] = 6 * s
    a["y"] = -abs(s) * 14
    return a

def _panic(t, a):
    a["aR"], a["eR"] = 140 + 15 * math.sin(t * 20), 170
    a["aL"], a["eL"] = -140 + 15 * math.sin(t * 20 + 2), -170
    a["lR"], a["kR"] = 16 * math.sin(t * 18), 16 * math.sin(t * 18)
    a["lL"], a["kL"] = -16 * math.sin(t * 18), -16 * math.sin(t * 18)
    a["y"] = -abs(math.sin(t * 9)) * 12
    return a

def _tremble(t, a):
    a["head"] += 2.5 * math.sin(t * 38)
    a["torso"] += 1.5 * math.sin(t * 33)
    return a

def _breathe(t, a):
    a["torso"] += 1.2 * math.sin(t * 2.4)
    return a

def _sneak(t, a):
    a = _walk(t, a, amp=18, speed=4.0, arm=0, lean=22)
    a.update(aR=45, eR=88, aL=28, eL=70, head=-12)
    return a

POSES = {
    "idle": (_p(), _breathe),
    "talk": (_p(aL=-14, eL=-10, torso=2), _talk),
    "walk": (_p(), _walk),
    "run": (_p(), _run),
    "sneak": (_p(torso=22, head=-12, aL=30, eL=75, aR=40, eR=85, lL=42, kL=-8, lR=-14, kR=-30), _sneak),
    "point": (_p(aR=88, eR=88, aL=-45, eL=30, torso=4), lambda t, a: dict(a, aR=88 + 4 * math.sin(t * 3))),
    "shocked": (_p(aL=-155, eL=-175, aR=155, eR=175, lL=-14, kL=-14, lR=14, kR=14, torso=-6, head=-8, y=-18), _tremble),
    "shrug": (_p(aL=-38, eL=-128, aR=38, eR=128, head=8, torso=-2), _breathe),
    "hands_up": (_p(aL=-130, eL=-178, aR=130, eR=178, lL=-6, kL=-6, lR=6, kR=6), _tremble),
    "facepalm": (_p(aR=62, eR=172, torso=9, head=10), _breathe),
    "laugh": (_p(aL=20, eL=-70, aR=-20, eR=70, torso=-12, head=-10), _laugh),
    "dance": (_p(), _dance),
    "panic": (_p(), _panic),
    "cower": (_p(aL=-125, eL=-165, aR=125, eR=165, torso=32, head=22, lL=30, kL=-30, lR=48, kR=-20), _tremble),
    "sit": (_p(aL=-18, eL=-5, aR=18, eR=5, lL=88, kL=2, lR=92, kR=-2), _breathe),
    "sit_talk": (_p(aL=-18, eL=-5, lL=88, kL=2, lR=92, kR=-2), _talk),
    "hold_up": (_p(aR=150, eR=172, aL=-12, eL=-8, torso=-3), _breathe),
    "hold": (_p(aR=62, eR=100, aL=-12, eL=-8), _breathe),
    "thinking": (_p(aR=52, eR=168, aL=-12, eL=-8, head=8), _breathe),
    "fall": (_p(aL=-150, eL=-170, aR=150, eR=170, lL=-24, kL=-30, lR=24, kR=30, rot=-55, y=-120), None),
    "lie": (_p(aL=-14, eL=-10, aR=14, eR=10, rot=-90), lambda t, a: dict(a, torso=a["torso"] + 0.8 * math.sin(t * 2))),
    "slump": (_p(torso=24, head=28, aL=8, eL=4, aR=-6, eR=-3), _breathe),
    "victory": (_p(aL=-155, eL=-178, aR=155, eR=178, lL=-10, kL=-10, lR=10, kR=10, head=-6), lambda t, a: dict(a, y=-abs(math.sin(t * 6)) * 16)),
    "kneel": (_p(torso=10, lL=88, kL=130, lR=20, kR=-5, aL=-20, eL=-10, aR=20, eR=10), _breathe),
    "lean": (_p(torso=-14, aL=-30, eL=-10, aR=70, eR=120, lL=-6, kL=-6, lR=22, kR=22), _breathe),
}

def solve_pose(name, t, prev=None, blend_t=0.0, blend_dur=0.22):
    base, fn = POSES.get(name, POSES["idle"])
    a = dict(base)
    if fn:
        a = fn(t, a)
    if prev is not None and blend_t < blend_dur:
        k = ease(blend_t / blend_dur)
        a = {key: prev.get(key, a[key]) * (1 - k) + a[key] * k for key in a}
    return a

# ----------------------------------------------------------------------------- face
FACES = {   # eyes, brows, mouth, extras
    "neutral":    ("dot", "none", "flat"),
    "happy":      ("happy", "none", "smile"),
    "laugh":      ("happy", "none", "laugh"),
    "scared":     ("wide", "worried", "wobble"),
    "shocked":    ("wide", "raised", "o"),
    "angry":      ("dot", "angry", "frown"),
    "sad":        ("dot", "worried", "frown"),
    "smirk":      ("dot", "angry_half", "smirk"),
    "suspicious": ("side", "angry_half", "flat"),
    "sleepy":     ("closed", "none", "flat"),
    "dead":       ("x", "none", "flat"),
    "confused":   ("dot", "raised_one", "wobble"),
    "sly":        ("squint", "angry_half", "smirk"),
    "screaming":  ("wide", "worried", "scream"),
}

def draw_face(ctx, cx, cy, r, expr, t):
    eyes, brows, mouth = FACES.get(expr, FACES["neutral"])
    ex = r * 0.34
    fx = r * 0.22                       # face is shifted toward facing direction (3/4 view)
    ey = cy - r * 0.08
    lw = max(4, r * 0.1)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_source_rgb(*INK)
    blink = (t % 3.4) > 3.28
    for sx in (-1, 1):
        x = cx + fx + sx * ex
        if eyes == "dot" or (blink and eyes in ("dot", "wide", "side")):
            ctx.set_line_width(lw)
            if blink:
                ctx.move_to(x - r * .12, ey); ctx.line_to(x + r * .12, ey); ctx.stroke()
            else:
                ctx.arc(x, ey, r * 0.115, 0, math.tau); ctx.fill()
        elif eyes == "wide":
            circle(ctx, x, ey, r * 0.22, WHITE)
            ctx.set_source_rgb(*INK); ctx.set_line_width(lw * .6)
            ctx.arc(x, ey, r * 0.22, 0, math.tau); ctx.stroke()
            ctx.arc(x + r * .04, ey, r * 0.08, 0, math.tau); ctx.fill()
        elif eyes == "side":
            circle(ctx, x, ey, r * 0.2, WHITE)
            ctx.set_source_rgb(*INK); ctx.set_line_width(lw * .6)
            ctx.arc(x, ey, r * 0.2, 0, math.tau); ctx.stroke()
            ctx.arc(x + r * .12, ey, r * 0.08, 0, math.tau); ctx.fill()
        elif eyes == "happy":
            ctx.set_line_width(lw)
            ctx.arc(x, ey + r * .1, r * .16, math.pi * 1.1, math.pi * 1.9); ctx.stroke()
        elif eyes == "closed":
            ctx.set_line_width(lw)
            ctx.arc(x, ey - r * .06, r * .16, math.pi * .1, math.pi * .9); ctx.stroke()
        elif eyes == "squint":
            ctx.set_line_width(lw)
            ctx.move_to(x - r * .15, ey); ctx.line_to(x + r * .15, ey); ctx.stroke()
        elif eyes == "x":
            ctx.set_line_width(lw * .9)
            d = r * .13
            ctx.move_to(x - d, ey - d); ctx.line_to(x + d, ey + d)
            ctx.move_to(x + d, ey - d); ctx.line_to(x - d, ey + d); ctx.stroke()
    # eyebrows
    ctx.set_line_width(lw * .85)
    by = ey - r * 0.3
    if brows in ("angry", "angry_half"):
        for sx in (-1, 1):
            if brows == "angry_half" and sx == -1:
                continue
            x = cx + fx + sx * ex
            ctx.move_to(x - sx * r * .2, by - r * .12); ctx.line_to(x + sx * r * .16, by + r * .08); ctx.stroke()
    elif brows == "worried":
        for sx in (-1, 1):
            x = cx + fx + sx * ex
            ctx.move_to(x - sx * r * .2, by + r * .08); ctx.line_to(x + sx * r * .16, by - r * .12); ctx.stroke()
    elif brows in ("raised", "raised_one"):
        for sx in (-1, 1):
            if brows == "raised_one" and sx == -1:
                continue
            x = cx + fx + sx * ex
            ctx.arc(x, by + r * .2, r * .2, math.pi * 1.15, math.pi * 1.85); ctx.stroke()
    # mouth
    mx, my = cx + fx, cy + r * 0.42
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(lw * .9)
    if mouth == "flat":
        ctx.move_to(mx - r * .2, my); ctx.line_to(mx + r * .2, my); ctx.stroke()
    elif mouth == "smile":
        ctx.arc(mx, my - r * .12, r * .26, math.pi * .15, math.pi * .85); ctx.stroke()
    elif mouth == "smirk":
        ctx.move_to(mx - r * .15, my + r * .02); ctx.curve_to(mx, my + r * .1, mx + r * .15, my, mx + r * .26, my - r * .12); ctx.stroke()
    elif mouth == "frown":
        ctx.arc(mx, my + r * .22, r * .22, math.pi * 1.15, math.pi * 1.85); ctx.stroke()
    elif mouth == "wobble":
        ctx.move_to(mx - r * .22, my)
        for i in range(1, 5):
            ctx.line_to(mx - r * .22 + i * r * .11, my + (r * .06 if i % 2 else -r * .06))
        ctx.stroke()
    elif mouth in ("o", "scream", "laugh"):
        open_k = {"o": .15, "scream": .3, "laugh": .24}[mouth]
        if mouth == "laugh":
            open_k *= 0.8 + 0.2 * math.sin(t * 16)
        ctx.save(); ctx.translate(mx, my + r * .04); ctx.scale(1, 1.15 if mouth != "laugh" else 0.9)
        ctx.arc(0, 0, r * open_k, 0, math.tau); ctx.set_source_rgb(*INK); ctx.fill(); ctx.restore()
        if mouth == "scream":
            circle(ctx, mx, my + r * .17, r * .13, (0.85, 0.3, 0.3))

# ----------------------------------------------------------------------------- accessories
def _acc_head(ctx, kind, hx, hy, r):
    if kind == "cap":
        ctx.save(); ctx.translate(hx, hy - r * .55)
        ctx.arc(0, 0, r * .95, math.pi, 0); ctx.close_path()
        ctx.set_source_rgb(*_rgb("#d93636")); ctx.fill_preserve(); ctx.set_source_rgb(*INK); ctx.set_line_width(7); ctx.stroke()
        poly(ctx, [(r * .5, -r * .08), (r * 1.55, r * .0), (r * 1.5, r * .16), (r * .4, r * .08)], "#b82727", stroke=INK, lw=6)
        ctx.restore()
    elif kind == "beanie":
        ctx.save(); ctx.translate(hx, hy - r * .5)
        ctx.arc(0, 0, r * 1.0, math.pi, 0); ctx.close_path()
        ctx.set_source_rgb(*_rgb("#2b2b33")); ctx.fill_preserve(); ctx.set_source_rgb(*INK); ctx.set_line_width(7); ctx.stroke()
        ctx.restore()
        rect(ctx, hx - r * .72, hy - r * .24, r * 1.7, r * .3, "#15151a")        # bandit mask
        ctx.set_source_rgb(*INK); ctx.set_line_width(5); ctx.rectangle(hx - r * .72, hy - r * .24, r * 1.7, r * .3); ctx.stroke()
        for sx in (-1, 1):
            circle(ctx, hx + r * .22 + sx * r * .34, hy - r * .09, r * .09, WHITE)
    elif kind == "police":
        ctx.save(); ctx.translate(hx, hy - r * .55)
        ctx.arc(0, 0, r * .98, math.pi, 0); ctx.close_path()
        ctx.set_source_rgb(*_rgb("#2457c5")); ctx.fill_preserve(); ctx.set_source_rgb(*INK); ctx.set_line_width(7); ctx.stroke()
        poly(ctx, [(-r * 1.05, 0), (r * 1.4, 0), (r * 1.35, r * .22), (-r * 1.0, r * .22)], "#173c8f", stroke=INK, lw=6)
        circle(ctx, r * .1, -r * .4, r * .17, "#f2c230")
        ctx.restore()
    elif kind == "tophat":
        rect(ctx, hx - r * .95, hy - r * 1.02, r * 2.0, r * .2, "#1c1c22")
        outlined_box(ctx, hx - r * .62, hy - r * 2.0, r * 1.24, r * 1.02, "#26262e", lw=6, r=6)
        rect(ctx, hx - r * .62, hy - r * 1.28, r * 1.24, r * .2, "#c9a227")
    elif kind == "fedora":
        poly(ctx, [(hx - r * 1.2, hy - r * .74), (hx + r * 1.3, hy - r * .74), (hx + r * .9, hy - r * .98), (hx - r * .8, hy - r * .98)], "#6b4a2b", stroke=INK, lw=6)
        outlined_box(ctx, hx - r * .6, hy - r * 1.5, r * 1.3, r * .8, "#7b5733", lw=6, r=14)
        rect(ctx, hx - r * .6, hy - r * .98, r * 1.3, r * .14, "#2b1c0f")
    elif kind == "glasses":
        ctx.set_source_rgb(*INK); ctx.set_line_width(6)
        for sx in (-1, 1):
            x = hx + r * .22 + sx * r * .34
            ctx.arc(x, hy - r * .08, r * .24, 0, math.tau); ctx.stroke()
        ctx.move_to(hx + r * .22 - r * .1, hy - r * .08); ctx.line_to(hx + r * .22 + r * .1, hy - r * .08); ctx.stroke()
    elif kind == "headphones":
        ctx.set_source_rgb(*_rgb("#3a3af0")); ctx.set_line_width(12)
        ctx.arc(hx, hy - r * .1, r * 1.05, math.pi * 1.05, math.pi * 1.95); ctx.stroke()
        for sx in (-1, 1):
            outlined_box(ctx, hx + sx * r * 1.0 - r * .18, hy - r * .35, r * .36, r * .6, "#3a3af0", lw=5, r=6)
    elif kind == "hair":
        for i, (dx, hh) in enumerate([(-.5, .55), (-.15, .85), (.2, .7), (.55, .5)]):
            poly(ctx, [(hx + dx * r - r * .13, hy - r * .92), (hx + dx * r + r * .02, hy - r * (.92 + hh)), (hx + dx * r + r * .17, hy - r * .92)], INK)
    elif kind == "bandana":
        rect(ctx, hx - r * .98, hy - r * .66, r * 1.96, r * .26, "#e0452b")
        ctx.set_source_rgb(*INK); ctx.set_line_width(5); ctx.rectangle(hx - r * .98, hy - r * .66, r * 1.96, r * .26); ctx.stroke()

def _acc_body(ctx, kind, neck, hip, torso_ang):
    sx = neck[0] * .86 + hip[0] * .14
    sy = neck[1] * .86 + hip[1] * .14
    if kind == "tie":
        poly(ctx, [(sx - 10, sy), (sx + 10, sy), (sx + 16, sy + 70), (sx, sy + 92), (sx - 16, sy + 70)], "#d62a2a", stroke=INK, lw=5)
    elif kind == "scarf":
        ctx.set_source_rgb(*_rgb("#ee8f2b")); ctx.set_line_width(26); ctx.move_to(neck[0] - 24, neck[1] + 10); ctx.line_to(neck[0] + 24, neck[1] + 10); ctx.stroke()
        rect(ctx, neck[0] - 4, neck[1] + 10, 16, 58, "#ee8f2b")
    elif kind == "badge":
        poly(ctx, [(sx + 8, sy + 30), (sx + 26, sy + 30), (sx + 28, sy + 52), (sx + 17, sy + 62), (sx + 6, sy + 52)], "#f2c230", stroke=INK, lw=4)
    elif kind == "trench":
        ctx.set_source_rgb(*_rgb("#8a6a3f")); ctx.set_line_width(44)
        ctx.move_to(sx, sy + 8); ctx.line_to(hip[0], hip[1] + 40); ctx.stroke()
        ctx.set_source_rgb(*INK); ctx.set_line_width(5)
        ctx.move_to(sx - 22, sy + 8); ctx.line_to(hip[0] - 22, hip[1] + 40); ctx.move_to(sx + 22, sy + 8); ctx.line_to(hip[0] + 22, hip[1] + 40); ctx.stroke()

ROLES = {   # role -> (head accessory, body accessory)
    "hero":      ("cap", None),
    "villain":   ("beanie", None),
    "cop":       ("police", "badge"),
    "boss":      ("tophat", "tie"),
    "friend":    ("headphones", "scarf"),
    "detective": ("fedora", "trench"),
    "civilian":  ("glasses", None),
    "kid":       ("hair", None),
    "criminal":  ("bandana", None),
    "extra":     (None, None),
}

# ----------------------------------------------------------------------------- props
FOLLOW_ARM = {"flashlight", "magnifier", "camera"}

def draw_prop(ctx, name, p, ang, t=0.0):
    """Draw a hand-held prop at hand point p; ang = forearm angle (deg from down)."""
    ctx.save(); ctx.translate(*p)
    if name in FOLLOW_ARM:
        ctx.rotate(math.radians(180 - ang))          # prop 'up' points along the forearm
    else:
        ctx.rotate(math.radians(5 * math.sin(t * 2.0)))  # stays upright, tiny sway
    if name == "phone":
        outlined_box(ctx, -22, -78, 44, 80, "#2a2f3a", lw=6, r=8); rect(ctx, -15, -68, 30, 54, "#7fd1ff")
    elif name == "briefcase":
        outlined_box(ctx, -52, -6, 104, 74, "#7a4a22", lw=7, r=8); ctx.set_source_rgb(*INK); ctx.set_line_width(6); ctx.arc(0, -8, 20, math.pi, 0); ctx.stroke(); rect(ctx, -6, 16, 12, 12, "#e5c35c")
    elif name == "moneybag":
        circle(ctx, 0, -40, 48, "#c9b28a"); ctx.set_source_rgb(*INK); ctx.set_line_width(6); ctx.arc(0, -40, 48, 0, math.tau); ctx.stroke()
        poly(ctx, [(-20, -84), (20, -84), (14, -70), (-14, -70)], "#c9b28a", stroke=INK, lw=5)
        ctx.select_font_face("DejaVu Sans", 0, 1); ctx.set_font_size(52); ctx.set_source_rgb(*INK); ctx.move_to(-17, -22); ctx.show_text("$")
    elif name == "cash":
        for i in range(3):
            ctx.save(); ctx.rotate(math.radians(-8 + i * 8)); outlined_box(ctx, -46, -62 + i * 8, 92, 44, "#5fbf6a", lw=5, r=4); circle(ctx, 0, -40 + i * 8, 11, "#3f9a4c"); ctx.restore()
    elif name == "magnifier":
        ctx.set_source_rgb(*INK); ctx.set_line_width(11); ctx.move_to(0, 0); ctx.line_to(0, -50); ctx.stroke()
        circle(ctx, 0, -92, 42, "#bfe9ff", 0.7); ctx.set_source_rgb(*INK); ctx.set_line_width(9); ctx.arc(0, -92, 42, 0, math.tau); ctx.stroke()
    elif name == "flashlight":
        outlined_box(ctx, -15, -64, 30, 64, "#3b3f4a", lw=5, r=5); poly(ctx, [(-24, -64), (24, -64), (20, -80), (-20, -80)], "#e8e8e8", stroke=INK, lw=4)
        beam = cairo.LinearGradient(0, -80, 0, -470); beam.add_color_stop_rgba(0, 1, 0.97, 0.7, 0.55); beam.add_color_stop_rgba(1, 1, 0.97, 0.7, 0)
        ctx.set_source(beam); ctx.move_to(-20, -80); ctx.line_to(-160, -470); ctx.line_to(160, -470); ctx.line_to(20, -80); ctx.close_path(); ctx.fill()
    elif name == "key":
        ctx.set_source_rgb(*_rgb("#e5c35c")); ctx.set_line_width(10); ctx.move_to(0, 0); ctx.line_to(0, -60); ctx.stroke()
        ctx.arc(0, -82, 20, 0, math.tau); ctx.stroke(); ctx.move_to(0, -10); ctx.line_to(14, -10); ctx.move_to(0, -26); ctx.line_to(14, -26); ctx.stroke()
    elif name == "handcuffs":
        for sx in (-1, 1):
            ctx.set_source_rgb(*_rgb("#b8bdc6")); ctx.set_line_width(9); ctx.arc(sx * 24, -30, 20, 0, math.tau); ctx.stroke()
        ctx.set_source_rgb(*INK); ctx.set_line_width(5); ctx.move_to(-6, -30); ctx.line_to(6, -30); ctx.stroke()
    elif name == "coffee":
        outlined_box(ctx, -30, -64, 60, 64, "#f2f2f2", lw=6, r=6); rect(ctx, -30, -50, 60, 16, "#7a4a22")
        ctx.set_source_rgb(*INK); ctx.set_line_width(6); ctx.arc(32, -32, 16, -math.pi / 2, math.pi / 2); ctx.stroke()
        for i in range(2):
            ctx.set_source_rgba(1, 1, 1, .6); ctx.set_line_width(5); ctx.move_to(-10 + i * 18, -74); ctx.curve_to(-18 + i * 18, -92, -2 + i * 18, -100, -10 + i * 18, -118); ctx.stroke()
    elif name == "laptop":
        outlined_box(ctx, -60, -8, 120, 14, "#3b3f4a", lw=5, r=3); poly(ctx, [(-52, -8), (52, -8), (44, -86), (-44, -86)], "#3b3f4a", stroke=INK, lw=5); poly(ctx, [(-40, -14), (40, -14), (35, -78), (-35, -78)], "#7fd1ff")
    elif name == "envelope":
        outlined_box(ctx, -46, -64, 92, 62, "#f6f1dc", lw=5, r=3); ctx.set_source_rgb(*INK); ctx.set_line_width(5); ctx.move_to(-46, -64); ctx.line_to(0, -30); ctx.line_to(46, -64); ctx.stroke()
    elif name == "trophy":
        poly(ctx, [(-34, -110), (34, -110), (22, -50), (-22, -50)], "#f2c230", stroke=INK, lw=6); rect(ctx, -8, -50, 16, 30, "#f2c230"); outlined_box(ctx, -30, -22, 60, 20, "#d6a720", lw=5, r=3)
    elif name == "balloon":
        ctx.set_source_rgb(*INK); ctx.set_line_width(4); ctx.move_to(0, 0); ctx.curve_to(10, -60, -10, -110, 0, -170); ctx.stroke()
        ctx.save(); ctx.translate(0, -230); ctx.scale(1, 1.25); circle(ctx, 0, 0, 52, "#e84d6b"); ctx.set_source_rgb(*INK); ctx.set_line_width(6); ctx.arc(0, 0, 52, 0, math.tau); ctx.stroke(); ctx.restore()
    elif name == "banana":
        ctx.set_source_rgb(*_rgb("#f4d03f")); ctx.set_line_width(26); ctx.arc(0, -52, 44, math.pi * .25, math.pi * 1.05); ctx.stroke()
    elif name == "pizza":
        poly(ctx, [(-50, -70), (50, -70), (0, 10)], "#f0b84a", stroke=INK, lw=6); circle(ctx, -14, -48, 9, "#c93b3b"); circle(ctx, 16, -42, 9, "#c93b3b"); circle(ctx, 0, -20, 8, "#c93b3b")
    elif name == "camera":
        outlined_box(ctx, -52, -64, 104, 62, "#3b3f4a", lw=6, r=8); circle(ctx, 0, -33, 22, "#9fd6ff"); ctx.set_source_rgb(*INK); ctx.set_line_width(5); ctx.arc(0, -33, 22, 0, math.tau); ctx.stroke()
    elif name == "sign":
        rect(ctx, -5, -10, 10, 70, "#7a4a22"); outlined_box(ctx, -90, -130, 180, 100, "#f6f1dc", lw=7, r=6)
    elif name == "bomb":
        circle(ctx, 0, -44, 44, "#222228"); ctx.set_source_rgb(*INK); ctx.set_line_width(5); ctx.arc(0, -44, 44, 0, math.tau); ctx.stroke()
        ctx.set_source_rgb(*_rgb("#c9a227")); ctx.set_line_width(7); ctx.move_to(14, -84); ctx.curve_to(26, -108, 40, -98, 38, -120); ctx.stroke()
        circle(ctx, 38 + 3 * math.sin(t * 30), -124, 9 + 2 * math.sin(t * 25), "#ffb02e")
    ctx.restore()

# ----------------------------------------------------------------------------- character
class Figure:
    HEAD_R = 60
    TORSO = 190
    UARM, FARM = 100, 96
    THIGH, SHIN = 122, 124

    def __init__(self, role="hero", scale=1.0):
        self.role = role if role in ROLES else "hero"
        self.scale = scale

    def layout(self, a):
        """Joint positions in character space (hip at origin, y down, facing +x)."""
        lean = a["torso"]
        hip = (0.0, 0.0)
        neck = pt(hip, -self.TORSO, lean)
        neck = (hip[0] + self.TORSO * math.sin(math.radians(lean)), hip[1] - self.TORSO * math.cos(math.radians(lean)))
        sh = (hip[0] + (neck[0] - hip[0]) * 0.9, hip[1] + (neck[1] - hip[1]) * 0.9)
        hr = self.HEAD_R
        hth = math.radians(lean + a["head"])
        head = (neck[0] + (hr + 6) * math.sin(hth), neck[1] - (hr + 6) * math.cos(hth))
        J = {"hip": hip, "neck": neck, "sh": sh, "head": head}
        for side in ("L", "R"):
            e = pt(sh, self.UARM, a["a" + side]); h = pt(e, self.FARM, a["e" + side])
            k = pt(hip, self.THIGH, a["l" + side]); f = pt(k, self.SHIN, a["k" + side])
            J.update({"el" + side: e, "h" + side: h, "k" + side: k, "f" + side: f})
        rot = math.radians(a.get("rot", 0))
        if rot:
            c, s = math.cos(rot), math.sin(rot)
            J = {n: (p[0] * c - p[1] * s, p[0] * s + p[1] * c) for n, p in J.items()}
        return J

    def draw(self, ctx, x, ground, a, face="neutral", facing=1, prop=None, t=0.0, extra_y=0.0, shadow=True):
        J = self.layout(a)
        lowest = max(max(p[1] for n, p in J.items() if n != "head"), J["head"][1] + self.HEAD_R)
        s = self.scale
        ctx.save()
        ctx.translate(x, ground - lowest * s + a.get("y", 0) * s + extra_y)
        ctx.scale(s * facing, s)
        if shadow:
            ctx.save(); ctx.translate(0, lowest + a.get("y", 0) * -1 - 4); ctx.scale(1, 0.16)
            circle(ctx, 0, 0, 120 * max(0.5, 1 + a.get("y", 0) / 300), (0, 0, 0), 0.28); ctx.restore()
        LW_OUT, LW_IN = 26, 15
        def limb(*pts_):
            for lw, col in ((LW_OUT, INK), (LW_IN, WHITE)):
                ctx.set_source_rgb(*col); ctx.set_line_width(lw); ctx.set_line_cap(cairo.LINE_CAP_ROUND); ctx.set_line_join(cairo.LINE_JOIN_ROUND)
                ctx.move_to(*pts_[0])
                for q in pts_[1:]:
                    ctx.line_to(*q)
                ctx.stroke()
        head_acc, body_acc = ROLES[self.role]
        limb(J["sh"], J["elL"], J["hL"])                                 # far arm
        limb(J["hip"], J["kL"], J["fL"])                                 # far leg
        limb(J["hip"], J["kR"], J["fR"])                                 # near leg
        limb(J["hip"], J["neck"])                                        # torso
        if body_acc:
            _acc_body(ctx, body_acc, J["neck"], J["hip"], a["torso"])
        if prop:
            ang = a["eR"] if a["eR"] != BASE["eR"] else 80
            draw_prop(ctx, prop, J["hR"], ang if "rot" not in a or not a["rot"] else ang + a["rot"], t)
        limb(J["sh"], J["elR"], J["hR"])                                 # near arm
        hx, hy = J["head"]
        circle(ctx, hx, hy, self.HEAD_R + 6, INK); circle(ctx, hx, hy, self.HEAD_R - 2, WHITE)
        draw_face(ctx, hx, hy, self.HEAD_R, face, t)
        if head_acc:
            _acc_head(ctx, head_acc, hx, hy, self.HEAD_R)
        ctx.restore()
        return J

    def hand_world(self, x, ground, a, facing=1):
        J = self.layout(a)
        lowest = max(max(p[1] for n, p in J.items() if n != "head"), J["head"][1] + self.HEAD_R)
        s = self.scale
        px, py = J["hR"]
        return (x + px * s * facing, ground - lowest * s + a.get("y", 0) * s + py * s), J, lowest

    def head_world(self, x, ground, a, facing=1):
        J = self.layout(a)
        lowest = max(max(p[1] for n, p in J.items() if n != "head"), J["head"][1] + self.HEAD_R)
        s = self.scale
        hx, hy = J["head"]
        return (x + hx * s * facing, ground - lowest * s + a.get("y", 0) * s + hy * s)

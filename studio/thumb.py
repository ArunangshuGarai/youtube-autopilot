"""Click-worthy thumbnail composer (1080x1920 JPEG, <2MB).

Layers, back to front:
  1. background  - an AI image when one is available (Gemini image model or Pollinations, both free), otherwise the
                   studio's own vector set drawn as a tight close-up. Either way it is graded for punch.
  2. sunburst + coloured glow behind the character (the 'sticker' look that works at feed size)
  3. the stick-figure hero, enlarged, extreme expression, white sticker outline + drop shadow
  4. 2-3 word headline in Anton: line 1 white, line 2 yellow, heavy black stroke
  5. small context badge (TRUE STORY / SCARY STORY / FUNNY STORY)
A 3D-render look needs an image model; with no model reachable the result is the flat-vector version of the same layout.
"""
import io
import math
import os
import urllib.parse

import cairo
import numpy as np
import requests
from PIL import Image, ImageEnhance, ImageFilter

from . import scenes as S
from .stickman import W, H, GROUND_Y, Figure, solve_pose, ease_out_back, rect, circle

PALETTE = {"crime": ((1.0, 0.45, 0.1), (1.0, 0.85, 0.2)), "thriller": ((0.1, 0.8, 0.9), (0.55, 0.3, 1.0)), "comedy": ((1.0, 0.75, 0.1), (1.0, 0.35, 0.6))}
BADGE = {"crime": "TRUE STORY", "thriller": "SCARY STORY", "comedy": "FUNNY STORY"}
STYLE = ("vertical 9:16 poster, 3D cartoon render, Pixar style, vivid saturated colours, dramatic rim lighting, shallow depth of field, "
         "empty space in the upper third, no text, no letters, no people, no characters. Scene: ")

# --------------------------------------------------------------------------- optional AI background
def _decode(img_bytes):
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    if min(img.size) < 256 or np.asarray(img.resize((64, 64))).std() < 12:       # blank / placeholder images are rejected
        raise ValueError("unusable image")
    return img

def _gemini_image(prompt):
    model, key = os.environ.get("GEMINI_IMAGE_MODEL", "").strip(), os.environ.get("GEMINI_API_KEY", "")
    if not model or not key:
        return None
    from . import script
    if not script._spend():
        return None
    try:
        from google import genai
        from google.genai import types
        res = genai.Client(api_key=key).models.generate_content(model=model, contents=prompt, config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]))
        for cand in res.candidates or []:
            for part in cand.content.parts or []:
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    return _decode(part.inline_data.data)
    except Exception as e:
        print(f"Thumbnail Gemini image unavailable: {str(e)[:100]}")
    return None

def _pollinations_image(prompt):
    if os.environ.get("THUMB_AI", "1") == "0":
        return None
    try:
        url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:600]) + "?width=1080&height=1920&nologo=true&model=flux&seed=" + str(abs(hash(prompt)) % 99999)
        r = requests.get(url, timeout=50, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            return _decode(r.content)
    except Exception as e:
        print(f"Thumbnail Pollinations image unavailable: {str(e)[:100]}")
    return None

def ai_background(sb):
    prompt = (sb.get("thumb") or {}).get("bg_prompt")
    if not prompt:
        return None
    full = STYLE + prompt
    return _gemini_image(full) or _pollinations_image(full)

# --------------------------------------------------------------------------- helpers
def _to_pil(surf):
    surf.flush()
    arr = np.ndarray((H, W, 4), np.uint8, surf.get_data())
    return Image.fromarray(arr[..., [2, 1, 0, 3]].copy(), "RGBa").convert("RGBA")

def _cover(img):
    r = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * r) + 1, int(img.height * r) + 1), Image.LANCZOS)
    return img.crop(((img.width - W) // 2, (img.height - H) // 2, (img.width - W) // 2 + W, (img.height - H) // 2 + H))

def _head_xy(role, pose, face, facing=1):
    fig = Figure(role, 1.28)
    a = solve_pose(pose, 1.2, prev=None)
    return fig, a, fig.head_world(W / 2, GROUND_Y, a, facing)

def _camera(ctx, head, z, ty):
    ctx.translate(W / 2, ty); ctx.scale(z, z); ctx.translate(-head[0], -head[1])

def _vector_background(th, genre, head, z, ty):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)
    zb = z * 0.9
    ctx.save(); _camera(ctx, head, zb, ty - max(0.0, ty - head[1] * zb))      # shift down-never-up so the world's top edge is always covered
    S.SETTINGS.get(th["setting"], S.bg_room)(ctx)
    sp = S.SET_PIECES.get(th.get("set_piece"))
    if sp:
        sp[0](ctx, W * 0.72, GROUND_Y, 1.0)
    ctx.restore()
    tint = S.LIGHT.get(th.get("lighting"))
    if tint:
        rect(ctx, 0, 0, W, H, tint[:3], tint[3])
    return _to_pil(surf).convert("RGB")

def _rays_and_glow(genre, head_screen):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)
    c1, c2 = PALETTE[genre]
    cx, cy = head_screen
    n = 18
    for i in range(n):
        a0, a1 = math.tau * i / n, math.tau * (i + .5) / n
        ctx.move_to(cx, cy); ctx.line_to(cx + 2600 * math.cos(a0), cy + 2600 * math.sin(a0)); ctx.line_to(cx + 2600 * math.cos(a1), cy + 2600 * math.sin(a1)); ctx.close_path()
        ctx.set_source_rgba(*c2, .20); ctx.fill()
    g = cairo.RadialGradient(cx, cy, 30, cx, cy, 760)
    g.add_color_stop_rgba(0, *c1, .55); g.add_color_stop_rgba(1, *c1, 0)
    ctx.set_source(g); ctx.rectangle(0, 0, W, H); ctx.fill()
    return _to_pil(surf)

def _hero_layer(th, genre, head, z, ty):
    """The enlarged stick figure on a transparent layer, then a white sticker outline and a drop shadow."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)
    fig, a, _ = _head_xy(th["role"], th["pose"], th["face"])
    fig.scale = 1.28
    ctx.save(); _camera(ctx, head, z, ty)
    fig.draw(ctx, W / 2, GROUND_Y, a, face=th["face"], facing=1, prop=th.get("prop"), t=1.2)
    hx, hy = head
    if th["face"] in ("shocked", "scared", "screaming"):
        S.fx_exclaim(ctx, hx + 150, hy - 120, 1.0, "!")
    elif th["face"] in ("angry",):
        S.fx_anger(ctx, hx + 120, hy - 60, 1.0)
    ctx.restore()
    hero = _to_pil(surf)
    alpha = hero.split()[3]
    small = alpha.resize((W // 3, H // 3), Image.BILINEAR).filter(ImageFilter.MaxFilter(11)).resize((W, H), Image.BILINEAR)
    outline = Image.new("RGBA", (W, H), (255, 255, 255, 0)); outline.putalpha(small.point(lambda v: 255 if v > 40 else 0))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0)); shadow.putalpha(small.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * .75)))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.alpha_composite(shadow, (10, 16)); layer.alpha_composite(outline); layer.alpha_composite(hero)
    return layer

def _headline(text, genre):
    words = text.upper().split()
    lines = [" ".join(words)] if len(words) == 1 else [words[0], " ".join(words[1:])] if len(words) <= 3 else [" ".join(words[:2]), " ".join(words[2:])]
    c1, c2 = PALETTE[genre]
    cols = [(1.0, 1.0, 1.0), (1.0, 0.86, 0.15)]
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)
    y = 120
    for i, ln in enumerate(lines[:2]):
        ts, w, h = S.text_surface([(ln, cols[i])], 200 if i == 0 else 225, S.FONT_CAPTION, stroke=20, max_width=1000)
        ctx.save(); ctx.translate(W / 2, y + h / 2); ctx.rotate(math.radians(-2.5 if i == 0 else 2))
        ctx.set_source_surface(ts, -w / 2, -h / 2); ctx.paint(); ctx.restore()
        y += h - 20
    return _to_pil(surf), y

def _badge(genre, fiction):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)
    label = BADGE[genre] if not (genre == "comedy" and not fiction) else "TRUE FAIL"
    ts, w, h = S.text_surface([(label, (0.07, 0.07, 0.08))], 70, S.FONT_COMIC, stroke=0, shadow=False, max_width=500)
    ctx.save(); ctx.translate(60, H - 210); ctx.rotate(math.radians(-3))
    S.outlined_box(ctx, -10, -8, w + 20, h + 14, "#ffd23f", lw=7, r=8)
    ctx.set_source_surface(ts, 0, -2); ctx.paint(); ctx.restore()
    return _to_pil(surf)

# --------------------------------------------------------------------------- public API
def make_thumbnail(sb, out_jpg, bg_img=None, allow_ai=True):
    th, genre = dict(sb["thumb"]), sb["genre"]
    if th["face"] not in ("shocked", "screaming", "scared", "laugh", "angry"):       # a thumbnail face must be extreme
        th["face"] = "screaming" if genre == "comedy" else "shocked"
    z, ty = 1.6, 1230
    _, _, head = _head_xy(th["role"], th["pose"], th["face"])
    ai = bg_img if bg_img is not None else (ai_background(sb) if allow_ai else None)
    if ai is not None:
        base = _cover(ai)
        used = "ai-background"
    else:
        base = _vector_background(th, genre, head, z, ty)
        used = "vector-background"
    base = ImageEnhance.Contrast(ImageEnhance.Color(base).enhance(1.3)).enhance(1.12).convert("RGBA")
    base.alpha_composite(_rays_and_glow(genre, (W / 2, ty)))
    base.alpha_composite(_hero_layer(th, genre, head, z, ty))
    vig = Image.new("L", (W, H), 0)
    ys, xs = np.mgrid[0:H, 0:W]
    d = np.sqrt(((xs - W / 2) / (W * .75)) ** 2 + ((ys - H * .5) / (H * .62)) ** 2)
    vig = Image.fromarray(np.clip((d - .55) * 190, 0, 150).astype(np.uint8), "L")
    base.alpha_composite(Image.merge("RGBA", (Image.new("L", (W, H), 0),) * 3 + (vig,)))
    head_layer, _ = _headline(th["text"], genre)
    base.alpha_composite(head_layer)
    base.alpha_composite(_badge(genre, sb.get("is_fiction", True)))
    img = base.convert("RGB")
    for q in (92, 85, 78, 70):
        img.save(out_jpg, "JPEG", quality=q, optimize=True)
        if os.path.getsize(out_jpg) < 1_900_000:
            break
    print(f"Thumbnail: {used}, '{th['text']}', {os.path.getsize(out_jpg) / 1e3:.0f} KB")
    return out_jpg

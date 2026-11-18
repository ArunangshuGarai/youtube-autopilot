"""Assemble a finished Short: voice -> timing -> music/SFX mix -> frame rendering -> encode."""
import os
import subprocess
import time

import cairo
import numpy as np

from . import audio as A
from . import scenes as S
from .stickman import W, H

FPS = 30
LEAD = 0.12          # visuals pop before the voice starts
TAIL = 0.28          # breathing room after each scene's narration

def build_audio_timeline(sb, workdir):
    """Synthesize every scene, then lay them on one timeline. Returns dict with arrays, starts, durations, words."""
    os.makedirs(workdir, exist_ok=True)
    genre = sb["genre"]
    voice_chunks, starts, durs, scene_words = [], [], [], []
    t = 0.0
    for i, sc in enumerate(sb["scenes"]):
        t0 = time.time()
        wav = A.synth_voice(sc["narration"], sb["voice_profile"], sc.get("delivery", "normal"), workdir, f"s{i}")
        vdur = len(wav) / A.SR
        tail = TAIL + (0.25 if i == len(sb["scenes"]) - 1 else 0.0) + (0.12 if sc.get("sfx") in ("sting", "boom", "slam", "fail", "boing") else 0.0)
        dur = LEAD + vdur + tail
        path = os.path.join(workdir, f"voice_{i}.wav")
        A.write_wav(path, wav)
        words_txt = sc["narration"].split()
        ws, we = A.word_timings(words_txt, path, vdur)
        words = [dict(text=w, start=t + LEAD + a, end=t + LEAD + b) for w, a, b in zip(words_txt, ws, we)]
        voice_chunks.append((t + LEAD, wav))
        starts.append(t); durs.append(dur); scene_words.append(words)
        t += dur
        print(f"  scene {i}: voice {vdur:.2f}s, scene {dur:.2f}s ({time.time() - t0:.1f}s to build)")
    total = t
    voice = np.zeros(int(total * A.SR) + A.SR, dtype=np.float32)
    for off, wav in voice_chunks:
        i = int(off * A.SR)
        voice[i:i + len(wav)] += wav
    return dict(voice=voice, starts=starts, durs=durs, words=scene_words, total=total)

def build_soundtrack(sb, tl, out_aac, workdir):
    music = A.make_music(sb["music_mood"], tl["total"], seed=sum(map(ord, sb["topic_id"])))
    events = []
    for i, sc in enumerate(sb["scenes"]):
        name = sc.get("sfx", "none")
        if name != "none":
            events.append((name, tl["starts"][i] + float(sc.get("sfx_at", 0.05)), 0.85))
        if sc.get("transition") == "flash" and name == "none":
            events.append(("whoosh", tl["starts"][i], 0.35))
    mixed = A.mix_tracks(tl["voice"], music, events, tl["total"])
    raw = os.path.join(workdir, "mix.wav")
    A.write_wav(raw, mixed)
    A.master(raw, out_aac, sb["genre"])
    return out_aac

def render_video(sb, tl, audio_path, out_mp4, max_seconds=None):
    genre = sb["genre"]
    total = tl["total"] if not max_seconds else min(tl["total"], max_seconds)
    n_frames = int(total * FPS)
    chunks_per_scene = [S.chunk_words(w) for w in tl["words"]]
    # No film grain: it is incompressible and exploded file size (200MB+). Flat vector art encodes to a few MB.
    grade = "eq=contrast=1.06:saturation=1.12" if genre == "comedy" else "eq=contrast=1.10:saturation=0.95:gamma=0.97"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", audio_path, "-vf", grade, "-c:v", "libx264", "-preset", os.environ.get("X264_PRESET") or "veryfast", "-crf", "21", "-maxrate", "9M", "-bufsize", "18M", "-tune", "animation",
           "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", "-movflags", "+faststart", out_mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)
    starts, durs = tl["starts"], tl["durs"]
    idx, t_start = 0, time.time()
    for f in range(n_frames):
        T = f / FPS
        while idx + 1 < len(starts) and T >= starts[idx + 1]:
            idx += 1
        sc = sb["scenes"][idx]
        local = T - starts[idx]
        ctx.save(); ctx.set_operator(cairo.OPERATOR_SOURCE); ctx.set_source_rgba(0, 0, 0, 1); ctx.paint(); ctx.restore()
        S.draw_scene(ctx, sc, local, durs[idx], genre)
        S.draw_caption(ctx, chunks_per_scene[idx], T, emphasis=set(sc.get("emphasis", [])))
        if f > n_frames - 8:                                           # fade to black at the very end
            S.rect(ctx, 0, 0, W, H, "#000000", min(1.0, (f - (n_frames - 8)) / 7))
        surf.flush()
        proc.stdin.write(bytes(surf.get_data()))
        if f % 300 == 0:
            print(f"  frame {f}/{n_frames} ({time.time() - t_start:.0f}s)")
    proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg encode failed ({rc})")
    return out_mp4

def render_thumbnail(sb, tl, out_jpg):
    """Dramatic frame from scene 2-3 + big hook text. 1080x1920 JPEG (<2MB)."""
    from PIL import Image
    i = min(2, len(sb["scenes"]) - 1)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)
    S.draw_scene(ctx, dict(sb["scenes"][i], overlay=None), 1.2, tl["durs"][i], sb["genre"])
    txt, w, h = S.text_surface([(sb["thumb_text"], (1.0, 0.86, 0.15))], 190, S.FONT_CAPTION, stroke=16, max_width=980)
    ctx.set_source_surface(txt, (W - w) / 2, 210); ctx.paint()
    surf.write_to_png(out_jpg + ".png")
    Image.open(out_jpg + ".png").convert("RGB").save(out_jpg, "JPEG", quality=92)
    os.remove(out_jpg + ".png")
    return out_jpg

def produce_short(sb, workdir="build", out_mp4="final_video.mp4", out_thumb="build/thumbnail.jpg", max_seconds=None):
    os.makedirs(workdir, exist_ok=True)
    print("1/4 Voice + word timing")
    tl = build_audio_timeline(sb, workdir)
    print(f"   total {tl['total']:.1f}s")
    print("2/4 Music, SFX and mix")
    aac = build_soundtrack(sb, tl, os.path.join(workdir, "soundtrack.m4a"), workdir)
    print("3/4 Rendering frames + encode")
    render_video(sb, tl, aac, out_mp4, max_seconds)
    print("4/4 Thumbnail")
    render_thumbnail(sb, tl, out_thumb)
    return out_mp4, out_thumb, tl

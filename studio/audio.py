"""Audio pipeline: free neural voice (Kokoro, optional edge-tts), Whisper word timing, synthesized music + SFX, ducked mix."""
import difflib
import math
import os
import re
import subprocess
import wave

import numpy as np

SR = 44100

# ----------------------------------------------------------------------------- voices
# Every profile can be overridden with env vars, e.g. VOICE_GRAVE="bm_george" VOICE_GRAVE_SPEED=0.95
VOICE_PROFILES = {
    "grave":     dict(voice="am_fenrir", speed=0.98, pause_period=0.40, pause_comma=0.18, edge="en-US-AndrewNeural", edge_rate=-2, edge_pitch=-2),
    "tense":     dict(voice="am_fenrir", speed=1.00, pause_period=0.38, pause_comma=0.16, edge="en-US-BrianNeural", edge_rate=0, edge_pitch=-2),
    "jolly":     dict(voice="am_michael", speed=1.00, pause_period=0.38, pause_comma=0.16, edge="en-US-GuyNeural", edge_rate=2, edge_pitch=0),
    "sarcastic": dict(voice="am_michael", speed=1.00, pause_period=0.38, pause_comma=0.16, edge="en-US-ChristopherNeural", edge_rate=2, edge_pitch=0),
}
DELIVERY_SPEED = {"normal": 1.0, "slow": 0.97, "fast": 1.03, "whisper": 0.96, "excited": 1.03, "deadpan": 0.98}
KEEP_AS_WORD = {"NASA", "NATO", "SWAT", "LEGO", "OPEC", "FIFA", "COVID", "AIDS", "UNESCO", "RADAR", "LASER", "SCUBA", "PIN", "WIFI"}
PRONOUNCE = {"IV": "eye-vee", "DNA": "D N A", "ID": "I D", "TV": "T V", "AI": "A I", "UFO": "U F O"}

def profile(name):
    p = dict(VOICE_PROFILES.get(name, VOICE_PROFILES["grave"]))
    up = name.upper()
    p["voice"] = os.environ.get(f"VOICE_{up}") or p["voice"]
    p["speed"] = float(os.environ.get(f"VOICE_{up}_SPEED") or p["speed"])
    p["edge"] = os.environ.get(f"EDGE_VOICE_{up}") or p["edge"]
    return p

def tts_text(text):
    """Spell acronyms the way a person would say them (so 'FBI' is 'F B I', 'IV' is not 'four')."""
    def fix(m):
        w = m.group(0)
        if w in PRONOUNCE:
            return PRONOUNCE[w]
        if w in KEEP_AS_WORD or len(w) < 2 or len(w) > 5:
            return w
        return " ".join(w)
    return re.sub(r"\b[A-Z]{2,5}\b", fix, text)

def split_sentences(text):
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return [p for p in parts if p]

_KOKORO = None
def _kokoro():
    global _KOKORO
    if _KOKORO is None:
        from kokoro_onnx import Kokoro
        m, v = os.environ.get("KOKORO_MODEL") or "kokoro-v1.0.onnx", os.environ.get("KOKORO_VOICES") or "voices-v1.0.bin"
        _KOKORO = Kokoro(m, v)
    return _KOKORO

def _trim(samples, sr, lead=0.03, tail=0.07, thr=0.006):
    idx = np.where(np.abs(samples) > thr)[0]
    if len(idx) < 100:
        return samples
    return samples[max(0, idx[0] - int(sr * lead)): min(len(samples), idx[-1] + int(sr * tail))]

def _resample(x, sr_from, sr_to=SR):
    if sr_from == sr_to:
        return x.astype(np.float32)
    n = int(len(x) * sr_to / sr_from)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)

def _tts_kokoro(text, prof, speed):
    k = _kokoro()
    vname = prof["voice"]
    try:
        if vname == "am_fenrir":
            voice_vec = k.get_voice_style("am_michael") * 0.65 + k.get_voice_style("am_adam") * 0.35
        elif vname in ("am_puck", "am_michael"):
            voice_vec = k.get_voice_style("am_puck") * 0.55 + k.get_voice_style("am_michael") * 0.45
        else:
            voice_vec = vname
    except Exception:
        voice_vec = vname
    samples, sr = k.create(text, voice=voice_vec, speed=speed, lang="en-us")
    return _resample(_trim(np.asarray(samples, dtype=np.float32), sr), sr)

def _tts_edge(text, prof, speed_mult, out_tmp):
    rate = int(round(prof["edge_rate"] + (speed_mult - 1.0) * 100))
    pitch = prof["edge_pitch"]
    mp3 = out_tmp + ".mp3"
    subprocess.run(["edge-tts", "--voice", prof["edge"], f"--rate={rate:+d}%", f"--pitch={pitch:+d}Hz", "--text", text, "--write-media", mp3],
                   check=True, capture_output=True, timeout=90)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ar", str(SR), "-ac", "1", out_tmp + ".wav"], check=True)
    return _read_wav(out_tmp + ".wav")

def _read_wav(path):
    with wave.open(path, "rb") as w:
        n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(n)
    dt = {1: np.uint8, 2: np.int16, 4: np.int32}[sw]
    a = np.frombuffer(raw, dtype=dt).astype(np.float32)
    a = (a - 128) / 128 if sw == 1 else a / float(2 ** (8 * sw - 1))
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return _resample(_trim(a, sr), sr)

def _write_wav(path, x, sr=SR):
    x = np.clip(x, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((x * 32767).astype(np.int16).tobytes())

def synth_voice(text, prof_name, delivery, workdir, tag, provider=None):
    """Returns float32 mono array at SR. Sentence-by-sentence so pauses and pacing feel human."""
    prof = profile(prof_name)
    provider = provider or os.environ.get("TTS_PROVIDER") or "kokoro"
    speed_mult = DELIVERY_SPEED.get(delivery, 1.0)
    sents = split_sentences(tts_text(text)) or [text]
    chunks, rng = [], np.random.RandomState(sum(map(ord, tag)))
    for i, s in enumerate(sents):
        jitter = 1.0 + rng.uniform(-0.03, 0.03)
        sp = prof["speed"] * speed_mult * jitter
        order = [provider] + [p for p in ("kokoro", "edge") if p != provider]
        wav = None
        for pv in order:
            try:
                wav = _tts_kokoro(s, prof, sp) if pv == "kokoro" else _tts_edge(s, prof, speed_mult * jitter, os.path.join(workdir, f"edge_{tag}_{i}"))
                break
            except Exception as e:
                print(f"TTS provider {pv} failed on '{s[:30]}': {str(e)[:120]}")
        if wav is None:
            raise RuntimeError("All TTS providers failed")
        chunks.append(wav)
        if i < len(sents) - 1:
            pause = prof["pause_period"] if s[-1] in ".!?…" else prof["pause_comma"]
            chunks.append(np.zeros(int(SR * pause), dtype=np.float32))
    return np.concatenate(chunks)

# ----------------------------------------------------------------------------- word timing (Whisper) with graceful fallback
_WHISPER = None
def _whisper():
    global _WHISPER
    if _WHISPER is None:
        from faster_whisper import WhisperModel
        _WHISPER = WhisperModel(os.environ.get("WHISPER_MODEL") or "base.en", device="cpu", compute_type="int8")
    return _WHISPER

def _norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())

def whisper_words(wav_path):
    segs, _ = _whisper().transcribe(wav_path, word_timestamps=True, language="en", beam_size=1, condition_on_previous_text=False)
    out = []
    for s in segs:
        for w in (s.words or []):
            out.append((w.word.strip(), float(w.start), float(w.end)))
    return out

def align_words(script_words, asr, voiced_start, voiced_end):
    """Map known script words onto ASR timestamps; interpolate the words ASR spelled differently."""
    n = len(script_words)
    start, end = [None] * n, [None] * n
    a = [_norm(w) for w in script_words]
    b = [_norm(w[0]) for w in asr]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                start[i1 + k], end[i1 + k] = asr[j1 + k][1], asr[j1 + k][2]
    # interpolate gaps proportionally to character counts
    i = 0
    while i < n:
        if start[i] is not None:
            i += 1; continue
        j = i
        while j < n and start[j] is None:
            j += 1
        t0 = end[i - 1] if i > 0 else voiced_start
        t1 = start[j] if j < n else voiced_end
        t1 = max(t1, t0 + 0.05 * (j - i))
        weights = [max(1, len(script_words[k])) for k in range(i, j)]
        tot, acc = float(sum(weights)), 0.0
        for k, wgt in zip(range(i, j), weights):
            start[k] = t0 + (t1 - t0) * acc / tot
            acc += wgt
            end[k] = t0 + (t1 - t0) * acc / tot
        i = j
    return start, end

def word_timings(script_words, wav_path, total_dur):
    try:
        asr = whisper_words(wav_path)
        if len(asr) >= max(1, len(script_words) // 3):
            return align_words(script_words, asr, 0.0, total_dur)
        print("Whisper returned too few words - using proportional timing.")
    except Exception as e:
        print(f"Whisper unavailable ({str(e)[:100]}) - using proportional timing.")
    return align_words(script_words, [], 0.0, total_dur)

# ----------------------------------------------------------------------------- synthesized SFX
def _env(n, attack=0.005, decay=8.0):
    t = np.arange(n) / SR
    return np.minimum(1, t / max(attack, 1e-4)) * np.exp(-t * decay)

def _noise(n, seed=0):
    return np.random.RandomState(seed).randn(n).astype(np.float32)

def _smooth(x, k):
    k = max(1, int(k))
    return np.convolve(x, np.ones(k) / k, mode="same")

def sfx(name, dur=None):
    n = lambda d: int(SR * d)
    if name == "whoosh":
        m = n(0.55); t = np.arange(m) / SR
        x = _smooth(_noise(m, 1), 30) * np.sin(np.pi * t / 0.55) ** 2 * 3.2
        return x * 0.45
    if name in ("hit", "boom", "slam"):
        m = n(0.7); t = np.arange(m) / SR
        f = 150 * np.exp(-t * 9) + 38
        body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 6)
        crack = _smooth(_noise(m, 2), 6) * np.exp(-t * 40) * 0.8
        return (body + crack) * 0.8
    if name == "ding":
        m = n(1.2); t = np.arange(m) / SR
        return (np.sin(2 * np.pi * 1318 * t) + 0.5 * np.sin(2 * np.pi * 2637 * t) + 0.25 * np.sin(2 * np.pi * 3951 * t)) * np.exp(-t * 4.5) * 0.28
    if name == "heartbeat":
        m = n(1.1); x = np.zeros(m, dtype=np.float32)
        for off, amp in ((0.0, 1.0), (0.22, 0.75)):
            k = n(0.18); t = np.arange(k) / SR
            th = np.sin(2 * np.pi * (70 * np.exp(-t * 14) + 38) * t) * np.exp(-t * 22) * amp
            s0 = int(off * SR); x[s0:s0 + k] += th[: m - s0]
        return x * 0.9
    if name == "sting":
        m = n(1.4); t = np.arange(m) / SR
        x = sum(np.sign(np.sin(2 * np.pi * f * t)) * 0.12 for f in (233, 247, 349, 370))
        return _smooth(x, 5) * np.exp(-t * 3.2) * 1.4
    if name == "record_scratch":
        m = n(0.55); t = np.arange(m) / SR
        f = 900 * np.exp(-t * 3) + 90
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.5 + _smooth(_noise(m, 3), 3) * 0.6
        return x * np.exp(-t * 3.5) * np.minimum(1, t / .01) * 0.7
    if name == "fail":
        m = n(1.1); t = np.arange(m) / SR
        f = 392 * np.exp(-t * 0.9) * (1 + 0.02 * np.sin(2 * np.pi * 6 * t))
        ph = 2 * np.pi * np.cumsum(f) / SR
        x = (np.sign(np.sin(ph)) * 0.5 + np.sin(ph) * 0.5)
        return _smooth(x, 4) * np.exp(-t * 1.4) * np.minimum(1, t / .02) * 0.5
    if name == "cash":
        x = np.zeros(n(0.9), dtype=np.float32)
        for i, f in enumerate((1568, 2093, 2637, 3136)):
            t = np.arange(n(0.4)) / SR; s0 = int(i * 0.07 * SR)
            x[s0:s0 + len(t)] += np.sin(2 * np.pi * f * t) * np.exp(-t * 9) * 0.25
        return x
    if name == "knock":
        x = np.zeros(n(0.9), dtype=np.float32)
        for i in range(3):
            t = np.arange(n(0.16)) / SR; s0 = int(i * 0.24 * SR)
            x[s0:s0 + len(t)] += np.sin(2 * np.pi * 110 * t) * np.exp(-t * 30) * 0.9 + _smooth(_noise(len(t), i), 8) * np.exp(-t * 50)
        return x * 0.9
    if name == "boing":
        m = n(0.7); t = np.arange(m) / SR
        f = 260 + 220 * np.sin(2 * np.pi * 5 * t) * np.exp(-t * 3) + 120 * np.exp(-t * 6)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4) * 0.5
    if name == "siren":
        m = n(1.6); t = np.arange(m) / SR
        f = 780 + 260 * np.sin(2 * np.pi * 1.4 * t)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.22 * np.minimum(1, t / .1) * np.minimum(1, (1.6 - t) / .3)
    if name == "click":
        m = n(0.12); t = np.arange(m) / SR
        return _smooth(_noise(m, 4), 3) * np.exp(-t * 60) * 0.7
    if name == "tick":
        x = np.zeros(n(1.2), dtype=np.float32)
        for i in range(4):
            t = np.arange(n(0.05)) / SR; s0 = int(i * 0.3 * SR)
            x[s0:s0 + len(t)] += np.sin(2 * np.pi * 1800 * t) * np.exp(-t * 90) * 0.4
        return x
    return np.zeros(1, dtype=np.float32)

# ----------------------------------------------------------------------------- generated music
def _midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)

MOODS = {
    #            bpm  root  scale     chords (scale degrees, 0-based)        character
    "tense":   dict(bpm=84,  root=45, scale=[0, 2, 3, 5, 7, 8, 10], prog=[0, 5, 3, 4], kind="dark"),
    "dark":    dict(bpm=72,  root=43, scale=[0, 2, 3, 5, 7, 8, 10], prog=[0, 2, 5, 4], kind="dark"),
    "sneaky":  dict(bpm=100, root=47, scale=[0, 2, 3, 5, 7, 8, 11], prog=[0, 3, 0, 4], kind="sneaky"),
    "sad":     dict(bpm=68,  root=50, scale=[0, 2, 3, 5, 7, 8, 10], prog=[0, 5, 2, 4], kind="dark"),
    "quirky":  dict(bpm=116, root=55, scale=[0, 2, 4, 5, 7, 9, 11], prog=[0, 3, 4, 0], kind="fun"),
    "upbeat":  dict(bpm=124, root=53, scale=[0, 2, 4, 5, 7, 9, 11], prog=[0, 4, 5, 3], kind="fun"),
    "epic":    dict(bpm=96,  root=40, scale=[0, 2, 3, 5, 7, 8, 10], prog=[0, 5, 6, 4], kind="dark"),
}

def _deg(scale, d, root):
    return root + scale[d % 7] + 12 * (d // 7)

def _tone(f, dur, kind, vel=1.0):
    m = int(SR * dur); t = np.arange(m) / SR
    if kind == "pluck":
        x = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t)) * np.exp(-t * 11)
    elif kind == "bass":
        x = (np.sin(2 * np.pi * f * t) + 0.4 * np.sign(np.sin(2 * np.pi * f * t))) * np.exp(-t * 4.5)
    elif kind == "pad":
        x = sum(np.sin(2 * np.pi * f * (1 + d) * t) for d in (-0.004, 0.0, 0.004)) / 3
        x = x * np.minimum(1, t / 0.4) * np.minimum(1, (dur - t) / 0.5)
    elif kind == "bell":
        x = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2.76 * f * t)) * np.exp(-t * 5)
    else:
        x = np.sin(2 * np.pi * f * t)
    return (x * vel).astype(np.float32)

def _add(buf, x, t0):
    i = int(t0 * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(x))
    buf[i:j] += x[: j - i]

def _kick():
    m = int(SR * 0.28); t = np.arange(m) / SR
    return np.sin(2 * np.pi * np.cumsum(120 * np.exp(-t * 22) + 42) / SR) * np.exp(-t * 11) * 0.9

def _hat(open_=False):
    m = int(SR * (0.16 if open_ else 0.05)); t = np.arange(m) / SR
    n = _noise(m, 5)
    return (n - _smooth(n, 8)) * np.exp(-t * (28 if open_ else 80)) * 0.22

def _snare():
    m = int(SR * 0.2); t = np.arange(m) / SR
    return (_noise(m, 6) * 0.5 + np.sin(2 * np.pi * 190 * t) * 0.4) * np.exp(-t * 22) * 0.55

def make_music(mood, duration, seed=0):
    cfg = MOODS.get(mood, MOODS["tense"])
    rng = np.random.RandomState(seed)
    beat = 60.0 / cfg["bpm"]
    total = duration + 1.0
    buf = np.zeros(int(total * SR), dtype=np.float32)
    scale, root, prog, kind = cfg["scale"], cfg["root"], cfg["prog"], cfg["kind"]
    bar = 4 * beat
    nbars = int(total / bar) + 1
    melody_deg = 2
    for b in range(nbars):
        ch = prog[b % len(prog)]
        t0 = b * bar
        # pad: triad
        for off in (0, 2, 4):
            _add(buf, _tone(_midi(_deg(scale, ch + off, root + 12)), bar + .3, "pad", 0.16), t0)
        if kind == "dark":
            for q in range(8):                                   # pulsing eighth-note bass
                _add(buf, _tone(_midi(_deg(scale, ch, root - 12)), beat * .5, "bass", 0.5 if q % 2 == 0 else 0.3), t0 + q * beat / 2)
            if cfg["bpm"] < 90:
                for q in (0, 1, 2, 3):
                    _add(buf, _kick() * 0.55, t0 + q * beat)
            for q in range(8):
                _add(buf, _hat(), t0 + q * beat / 2 + (beat / 4))
            if b % 2 == 1:                                       # sparse eerie bell
                _add(buf, _tone(_midi(_deg(scale, ch + 4, root + 24)), 2.0, "bell", 0.12), t0 + beat * 2)
        elif kind == "sneaky":
            for q in range(4):
                _add(buf, _tone(_midi(_deg(scale, ch + (0 if q % 2 == 0 else 4), root - 12)), beat * .45, "bass", 0.55), t0 + q * beat)
            for q in range(8):
                if q % 2 == 1:
                    _add(buf, _tone(_midi(_deg(scale, ch + [0, 2, 4, 2][(q // 2) % 4], root + 12)), beat * .3, "pluck", 0.28), t0 + q * beat / 2)
            _add(buf, _kick() * 0.4, t0); _add(buf, _kick() * 0.4, t0 + 2 * beat)
            for q in range(8):
                _add(buf, _hat(), t0 + q * beat / 2)
        else:                                                    # fun
            for q in range(4):
                _add(buf, _tone(_midi(_deg(scale, ch + [0, 4, 2, 4][q], root - 12)), beat * .8, "bass", 0.55), t0 + q * beat)
            for q in range(8):                                   # bouncy pluck melody (seeded random walk)
                if rng.rand() < 0.75:
                    melody_deg = int(np.clip(melody_deg + rng.choice([-2, -1, 0, 1, 2]), 0, 9))
                    _add(buf, _tone(_midi(_deg(scale, melody_deg, root + 12)), beat * .45, "pluck", 0.32), t0 + q * beat / 2)
            for q in (0, 2):
                _add(buf, _kick() * 0.6, t0 + q * beat)
            for q in (1, 3):
                _add(buf, _snare() * 0.6, t0 + q * beat)
            for q in range(8):
                _add(buf, _hat(), t0 + q * beat / 2 + beat / 4)
    buf = buf[: int(total * SR)]
    fade = int(1.2 * SR)
    buf[-fade:] *= np.linspace(1, 0, fade)
    buf[: int(0.05 * SR)] *= np.linspace(0, 1, int(0.05 * SR))
    peak = np.max(np.abs(buf)) or 1
    return (buf / peak * 0.9).astype(np.float32)

# ----------------------------------------------------------------------------- mix
def _envelope(x, win):
    a = np.abs(x)
    k = max(1, int(win))
    c = np.cumsum(np.insert(a, 0, 0))
    out = (c[k:] - c[:-k]) / k
    return np.concatenate([out, np.full(len(x) - len(out), out[-1] if len(out) else 0)])

def mix_tracks(voice, music, sfx_events, total_dur, music_db=-27, duck=0.85):
    """voice/music: arrays at SR; sfx_events: list of (name, t_seconds, gain). Returns mono float32."""
    n = int(total_dur * SR)
    out = np.zeros(n, dtype=np.float32)
    v = np.zeros(n, dtype=np.float32); v[: min(n, len(voice))] = voice[:n]
    m = np.zeros(n, dtype=np.float32); m[: min(n, len(music))] = music[:n]
    env = _envelope(v, int(0.06 * SR))
    env = np.clip(env / 0.08, 0, 1)
    env = np.convolve(env, np.ones(int(0.18 * SR)) / int(0.18 * SR), mode="same")
    gain = 1 - duck * env
    out += v + m * (10 ** (music_db / 20)) * gain
    for name, t0, g in sfx_events:
        x = sfx(name)
        i = int(max(0, t0) * SR)
        j = min(n, i + len(x))
        if i < n:
            out[i:j] += x[: j - i] * (g * 0.42)
    peak = np.max(np.abs(out)) or 1
    if peak > 0.95:
        out = out / peak * 0.95
    return out

def write_wav(path, x):
    _write_wav(path, x)

def master(in_wav, out_aac, genre="thriller"):
    """Voice-forward polish + loudness for Shorts (-14 LUFS)."""
    chain = ("highpass=f=60,equalizer=f=3200:t=q:w=1.2:g=2,acompressor=threshold=-18dB:ratio=3:attack=8:release=90:makeup=2,"
             + ("aecho=0.8:0.55:35:0.12," if genre in ("thriller", "crime") else "")
             + "loudnorm=I=-14:TP=-1.5:LRA=9")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", in_wav, "-af", chain, "-c:a", "aac", "-b:a", "192k", "-ar", "44100", out_aac], check=True)

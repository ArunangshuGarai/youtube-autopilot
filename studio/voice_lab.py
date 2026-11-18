"""Voice lab: render the same lines in many free voices so you can LISTEN and pick.  python -m studio.voice_lab"""
import os
import subprocess

import numpy as np

from . import audio as A

LINES = {
    "thriller": "At three a.m., my phone buzzed. The text came from my own number. It said: don't open the front door.",
    "comedy": "I built a wardrobe by myself. Four hours. Zero instructions. The box said easy assembly. The box lied.",
}
KOKORO_VOICES = ["am_fenrir", "am_michael", "am_adam", "am_onyx", "am_eric", "am_liam", "am_puck", "am_echo", "bm_george", "bm_fable", "bm_daniel", "bm_lewis", "af_heart", "af_bella"]
EDGE_VOICES = ["en-US-AndrewNeural", "en-US-BrianNeural", "en-US-GuyNeural", "en-US-ChristopherNeural", "en-US-EricNeural", "en-GB-RyanNeural", "en-US-AndrewMultilingualNeural"]

def to_mp3(wav, mp3):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-c:a", "libmp3lame", "-b:a", "128k", mp3], check=True)

if __name__ == "__main__":
    out = "build/voice_lab"
    os.makedirs(out, exist_ok=True)
    rows = []
    for genre, text in LINES.items():
        for v in KOKORO_VOICES:
            for speed in (0.95, 1.05):
                prof = dict(voice=v, speed=speed, pause_period=0.3, pause_comma=0.13)
                try:
                    chunks = []
                    for s in A.split_sentences(text):
                        chunks += [A._tts_kokoro(s, prof, speed), np.zeros(int(A.SR * 0.28), dtype=np.float32)]
                    wav = f"{out}/_tmp.wav"; A.write_wav(wav, np.concatenate(chunks))
                    final = f"{out}/{genre}__kokoro__{v}__{speed}.m4a"
                    A.master(wav, final, genre)
                    rows.append(f"{genre} | kokoro | {v} | speed {speed}")
                except Exception as e:
                    print("skip", v, speed, str(e)[:80])
        for v in EDGE_VOICES:
            try:
                prof = dict(edge=v, edge_rate=0, edge_pitch=0)
                wav = f"{out}/_edge_{genre}_{v}"
                x = A._tts_edge(text, prof, 1.0, wav)
                A.write_wav(f"{out}/_tmp.wav", x)
                A.master(f"{out}/_tmp.wav", f"{out}/{genre}__edge__{v}.m4a", genre)
                rows.append(f"{genre} | edge-tts | {v}")
            except Exception as e:
                print("edge voice failed (cloud IPs are sometimes blocked):", v, str(e)[:100])
    open(f"{out}/INDEX.txt", "w").write("\n".join(rows))
    print(f"{len(rows)} samples in {out}")

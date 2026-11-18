"""Render a preview Short without touching YouTube:  python -m studio --genre comedy [--seconds 20]"""
import argparse
import json
import os

from . import script, video

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--genre", default="comedy", choices=script.GENRES)
    ap.add_argument("--live", action="store_true", help="use the LLM instead of the curated backup story")
    ap.add_argument("--seconds", type=float, default=None, help="render only the first N seconds (quick test)")
    ap.add_argument("--out", default="preview.mp4")
    a = ap.parse_args()
    os.makedirs("build", exist_ok=True)
    sb = script.generate_story({"used_topics": [], "genre_log": []}, "", []) if a.live else script.backup_story(a.genre, [])
    json.dump(sb, open("build/storyboard.json", "w"), indent=2)
    mp4, thumb, tl = video.produce_short(sb, out_mp4=a.out, max_seconds=a.seconds)
    print(f"Done: {mp4} ({tl['total']:.1f}s) thumbnail: {thumb}")

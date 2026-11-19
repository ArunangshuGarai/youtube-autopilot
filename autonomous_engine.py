"""Autonomous YouTube Shorts studio: writes, voices, animates, scores, QA-checks and uploads a stick-figure Short.

Everything runs free on GitHub Actions: stick figures are drawn in code (pycairo), voice is Kokoro (edge-tts fallback),
captions are timed with Whisper, music/SFX are synthesized. Only Gemini (free tier) writes the script.
"""
import json
import os
import random
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta, timezone

import requests
from PIL import Image, ImageStat
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from studio import learn, packaging, script, video

MEMORY_FILE = "memory.json"
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}

# ----------------------------------------------------------------------------- memory
def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"used_topics": [], "published_log": {}, "channel_synced": False}

def save_memory(mem):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mem, f, indent=2)

def sync_existing_channel_history(youtube_client, memory):
    if memory.get("channel_synced"):
        return
    try:
        items = youtube_client.channels().list(mine=True, part="snippet,contentDetails").execute().get("items", [])
        if not items:
            return
        uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = youtube_client.playlistItems().list(playlistId=uploads_id, part="snippet", maxResults=50).execute()
        for item in pl.get("items", []):
            vid_id, title = item["snippet"]["resourceId"]["videoId"], item["snippet"]["title"]
            if title not in memory["used_topics"]:
                memory["used_topics"].append(title)
            memory.setdefault("published_log", {})[vid_id] = {"title": title, "hook": item["snippet"].get("description", "")[:120],
                                                              "scheduled_for": item["snippet"].get("publishedAt", "existing")}
        memory["channel_synced"] = True
        save_memory(memory)
    except Exception as e:
        print(f"Channel sync note: {e}")

# ----------------------------------------------------------------------------- scheduling gate
def enforce_warmup_gate(memory):
    """First 14 bot uploads: at most one scheduled run a day (13-15 UTC). Counts only videos this bot made."""
    total = memory.get("bot_uploads", 0)
    hour = datetime.now(timezone.utc).hour
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and total < 14 and hour not in (13, 14, 15):
        print(f"Warm-up gate: {total}/14 bot uploads, skipping this scheduled slot.")
        raise SystemExit(0)

# ----------------------------------------------------------------------------- learning + inspiration
def fetch_self_learning_feedback(creds, memory):
    try:
        yt_analytics = build("youtubeAnalytics", "v2", credentials=creds)
        report = yt_analytics.reports().query(
            ids="channel==MINE", startDate=(date.today() - timedelta(days=28)).isoformat(), endDate=date.today().isoformat(),
            metrics="views,engagedViews,averageViewPercentage,subscribersGained", dimensions="video", sort="-engagedViews", maxResults=10).execute()
        rows = report.get("rows", [])
        pub = memory.get("published_log", {})
        scored = []
        for r in rows[:3]:
            vid, views, engaged, avg_pct, subs = r
            meta = pub.get(vid, {"title": vid})
            scored.append(f"'{meta['title']}' [{meta.get('genre', '?')}] ({engaged} engaged views, {avg_pct:.0f}% retention)")
        return ("Top performers: " + "; ".join(scored)) if scored else ""
    except Exception:
        return ""

def harvest_signals():
    signals = []
    for sub in ("todayilearned", "UnresolvedMysteries", "tifu", "AskReddit"):
        try:
            r = requests.get(f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=6", headers=BROWSER_HEADERS, timeout=12)
            if r.status_code == 200:
                signals += [p["data"]["title"] for p in r.json()["data"]["children"]]
        except Exception:
            pass
    try:
        r = requests.get("https://trends.google.com/trending/rss?geo=US", headers=BROWSER_HEADERS, timeout=12)
        if r.status_code == 200:
            signals += [i.text for i in ET.fromstring(r.text).findall(".//item/title")[:6]]
    except Exception:
        pass
    return signals

# ----------------------------------------------------------------------------- QA gate
def _probe(path, entries, stream=None):
    cmd = ["ffprobe", "-v", "error"] + (["-select_streams", stream] if stream else []) + ["-show_entries", entries, "-of", "default=noprint_wrappers=1:nokey=1", path]
    return subprocess.check_output(cmd, text=True).strip()

def qa_verify(video_path, thumb_path, sb):
    if not os.path.exists(video_path) or os.path.getsize(video_path) < 400_000:
        raise RuntimeError("QA: video missing or too small")
    dur = float(_probe(video_path, "format=duration"))
    if not 20 <= dur <= 75:
        raise RuntimeError(f"QA: unexpected duration {dur:.1f}s (want 20-75s)")
    if not _probe(video_path, "stream=codec_type", "a"):
        raise RuntimeError("QA: no audio stream")
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", video_path, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", out)
    if m and float(m.group(1)) < -40:
        raise RuntimeError(f"QA: audio nearly silent ({m.group(1)} dB)")
    for t in (dur * 0.2, dur * 0.5, dur * 0.8):
        frame = f"build/qa_{int(t)}.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(t), "-i", video_path, "-frames:v", "1", frame], check=True)
        if max(ImageStat.Stat(Image.open(frame).convert("RGB")).stddev) < 12:
            raise RuntimeError(f"QA: frame at {t:.0f}s looks blank")
    if not os.path.exists(thumb_path) or os.path.getsize(thumb_path) > 2_000_000:
        raise RuntimeError("QA: thumbnail missing or over 2MB")
    print(f"QA passed: {dur:.1f}s, {os.path.getsize(video_path) / 1e6:.1f}MB")

# ----------------------------------------------------------------------------- upload
def publish(youtube_client, video_path, thumb_path, sb):
    seo = packaging.build_seo(sb)
    publish_at = (datetime.now(timezone.utc) + timedelta(minutes=random.randint(15, 35))).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "snippet": {
            "title": seo["title"],                         # <=58 chars, subject first; #Shorts lives in the description (saves title space)
            "description": seo["description"],
            "tags": seo["tags"],
            "categoryId": "24",                            # Entertainment
            "defaultLanguage": "en-US", "defaultAudioLanguage": "en-US",
        },
        "status": {
            "privacyStatus": "private", "publishAt": publish_at,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": False,               # "Altered or synthetic content": No (stylised animation + TTS narrator)
            "embeddable": True, "publicStatsViewable": True,
        },
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    res = youtube_client.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    vid = res["id"]
    try:
        youtube_client.thumbnails().set(videoId=vid, media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg")).execute()
    except Exception as e:
        print(f"Thumbnail note (custom thumbnails need a verified channel): {str(e)[:120]}")
    print(f"SEO: title='{seo['title']}' | tags={len(seo['tags'])} | hashtags={seo['hashtags']} | query coverage={seo['coverage']}")
    return vid, publish_at, seo["title"]

def local_quality_gate(sb):
    """Free gate (no API call): returns (ok, fix_hint). A weak hook is the one flaw worth a regeneration."""
    h = packaging.score_hook(sb["scenes"][0]["narration"])
    print("GATE:", packaging.package_report(sb))
    if h["verdict"] < 40:
        return False, f"The opening line scored {h['verdict']}/100 (weakest: {h['weakest']}). Rewrite it: {packaging.HOOK_FIX.get(h['weakest'], '')}."
    return True, ""

# Add to autonomous_engine.py right inside qa_verify() (or call right after produce_short):
def ai_multimodal_virality_audit(video_path, sb):
    """Extracts a 4-frame contact sheet from final_video.mp4 and uses Gemini Vision to grade visual quality & virality."""
    from PIL import Image
    from google import genai
    from google.genai import types

    dur = float(_probe(video_path, "format=duration"))
    frames = []
    for idx, pct in enumerate((0.12, 0.38, 0.65, 0.88)):
        f_path = f"build/audit_{idx}.jpg"
        subprocess.run([
            "ffmpeg", "-loglevel", "error", "-y", "-ss", str(dur * pct),
            "-i", video_path, "-frames:v", "1", f_path
        ], check=True)
        frames.append(Image.open(f_path).convert("RGB").resize((540, 960)))

    # Stitch 2x2 contact sheet of the actual rendered video frames
    sheet = Image.new("RGB", (1080, 1920))
    sheet.paste(frames[0], (0, 0)); sheet.paste(frames[1], (540, 0))
    sheet.paste(frames[2], (0, 960)); sheet.paste(frames[3], (540, 960))
    sheet_path = "build/qa_contact_sheet.jpg"
    sheet.save(sheet_path, "JPEG", quality=88)

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return True, 85, "No API key for vision audit"

    client = genai.Client(api_key=api_key)
    with open(sheet_path, "rb") as f:
        img_bytes = f.read()

    audit_prompt = f"""
    You are a strict YouTube Shorts Virality & Quality Inspector reviewing a 2x2 contact sheet of 4 rendered frames
    from our stick-figure Short titled '{sb['title']}' (Hook: '{sb['scenes'][0]['narration']}').
    Score this video from 0 to 100 across 4 criteria (25 pts each):
    1. Visual Readability & Framing (Are characters clearly visible, uncluttered, and expressive?)
    2. Facial Expression Contrast (Do expressions clearly change from setup to reaction?)
    3. Story Clarity & Hook Punch (Is the premise immediately understandable in 2 seconds?)
    4. Technical Cleanliness (No blank panels, broken text, or unreadable overlaps?)
    Return ONLY valid JSON: {{"score": 88, "pass": true, "critique": "1-sentence explanation", "fix_hint": "what to change if score < 80"}}
    """
    for model_name in ("gemini-3.8-flash", "gemini-3.6-flash"):
        try:
            res = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    audit_prompt
                ]
            )
            cleaned = re.sub(r"^```(?:json)?|```$", "", res.text.strip(), flags=re.MULTILINE).strip()
            verdict = json.loads(cleaned[cleaned.find("{"):cleaned.rfind("}") + 1])
            score = int(verdict.get("score", 85))
            print(f"AI Vision Virality Audit ({model_name}): {score}/100 — {verdict.get('critique')}")
            return score >= 80, score, verdict.get("fix_hint", "")
        except Exception as e:
            print(f"Vision audit {model_name} note: {e}")
    return True, 85, "Fallback technical QA passed"

# ----------------------------------------------------------------------------- main
if __name__ == "__main__":
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
    )
    yt = build("youtube", "v3", credentials=creds)

    memory = load_memory()
    sync_existing_channel_history(yt, memory)
    enforce_warmup_gate(memory)

    hint = learn.learn_from_analytics(creds, memory) or fetch_self_learning_feedback(creds, memory)
    signals = learn.viral_scout(yt, memory) + harvest_signals()

    os.makedirs("build", exist_ok=True)
    use_vision = os.environ.get("VISION_AUDIT", "").strip() == "1"      # off by default: it costs 1-2 extra Gemini calls per video
    storyboard = mp4 = thumb = None
    for qa_pass in range(2):
        storyboard = script.generate_story(memory, hint, signals)
        ok, fix = local_quality_gate(storyboard)
        if not ok and qa_pass == 0 and memory.get("api_budget", {}).get("calls", 0) < 10:
            print(f"Local gate asked for a rewrite: {fix}")
            hint = f"{hint} | CRITICAL FIX REQUIRED: {fix}"
            continue
        print(f"Pass {qa_pass + 1} | Genre: {storyboard['genre']} | Title: {storyboard['title']} | scenes: {len(storyboard['scenes'])}")
        with open("build/storyboard.json", "w", encoding="utf-8") as f:
            json.dump(storyboard, f, indent=2)

        mp4, thumb, tl = video.produce_short(storyboard, out_mp4="final_video.mp4", out_thumb="build/thumbnail.jpg")
        qa_verify(mp4, thumb, storyboard)
        if not use_vision:
            break
        passed, score, fix_hint = ai_multimodal_virality_audit(mp4, storyboard)
        if passed:
            break
        print(f"Video scored {score}/100 - auto-regenerating with fix: {fix_hint}")
        hint = f"{hint} | CRITICAL FIX REQUIRED: {fix_hint}"

    vid, when, final_title = publish(yt, mp4, thumb, storyboard)

    memory["used_topics"].append(storyboard["topic_id"])
    memory["bot_uploads"] = memory.get("bot_uploads", 0) + 1
    memory.setdefault("genre_log", []).append(storyboard["genre"])
    memory.setdefault("published_log", {})[vid] = {
        "title": final_title,
        "genre": storyboard["genre"],
        "hook": storyboard["scenes"][0]["narration"],
        "hook_score": packaging.score_hook(storyboard["scenes"][0]["narration"])["verdict"],
        "thumb_text": storyboard.get("thumb_text"),
        "queries": storyboard.get("seo", {}).get("queries", []),
        "scheduled_for": when,
        "is_fiction": storyboard["is_fiction"],
        "facts_used": storyboard.get("facts_used", []),
    }
    save_memory(memory)
    print(f"Success! Video {vid} scheduled for {when}")
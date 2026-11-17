import os, json, time, random, urllib.parse, subprocess, xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta, timezone
import requests
from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

MEMORY_FILE = "memory.json"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"used_topics": [], "published_log": {}, "channel_synced": False}

def save_memory(mem):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mem, f, indent=2)

# 0. AUTO-SYNC EXISTING CHANNEL VIDEOS ON FIRST RUN (Never repeats your past videos)
def sync_existing_channel_history(youtube_client, memory):
    if memory.get("channel_synced"):
        return
    try:
        ch_res = youtube_client.channels().list(mine=True, part="snippet,contentDetails").execute()
        items = ch_res.get("items", [])
        if not items:
            return
        uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl_res = youtube_client.playlistItems().list(playlistId=uploads_id, part="snippet", maxResults=50).execute()
        for item in pl_res.get("items", []):
            vid_id = item["snippet"]["resourceId"]["videoId"]
            title = item["snippet"]["title"]
            if title not in memory["used_topics"]:
                memory["used_topics"].append(title)
            memory.setdefault("published_log", {})[vid_id] = {
                "title": title,
                "hook": item["snippet"].get("description", "")[:120],
                "scheduled_for": item["snippet"].get("publishedAt", "existing")
            }
        memory["channel_synced"] = True
        save_memory(memory)
        print(f"Synced {len(pl_res.get('items', []))} existing videos into memory.json.")
    except Exception as e:
        print(f"Existing channel sync skipped: {e}")

# 1. ANTI-BAN SHIELD: 14-Day Warm-Up Gate (1 video/day if channel has < 14 videos, else 3/day)
def enforce_warmup_gate(memory):
    total_uploaded = len(memory.get("used_topics", []))
    current_utc_hour = datetime.now(timezone.utc).hour
    is_scheduled = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    if is_scheduled and total_uploaded < 14 and current_utc_hour not in (13, 14, 15):
        print(f"Warm-up gate active ({total_uploaded}/14 videos): skipping secondary slot.")
        raise SystemExit(0)

# 2. SELF-LEARNING ANALYTICS LOOP: Pull past retention & engagedViews from YouTube Analytics API v2
def fetch_self_learning_feedback(creds, memory):
    try:
        yt_analytics = build("youtubeAnalytics", "v2", credentials=creds)
        start_date = (date.today() - timedelta(days=28)).isoformat()
        end_date = date.today().isoformat()
        report = yt_analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,engagedViews,averageViewPercentage,subscribersGained",
            dimensions="video",
            sort="-engagedViews",
            maxResults=12
        ).execute()
        rows = report.get("rows", [])
        if not rows:
            return "Focus on extreme visual curiosity hooks in the first 1.5 seconds."
        pub_log = memory.get("published_log", {})
        scored = []
        for r in rows:
            vid_id, views, engaged, avg_pct, subs = r
            meta = pub_log.get(vid_id, {"title": vid_id, "hook": "N/A"})
            scored.append(
                f"Title: '{meta['title']}' | Hook: '{meta['hook']}' -> "
                f"Engaged Views: {engaged}, Avg % Viewed: {avg_pct:.1f}%, Subs: +{subs}"
            )
        winners = "\n".join(scored[:3])
        losers = "\n".join(scored[-3:])
        return f"TOP PERFORMERS (Replicate hook style & pacing):\n{winners}\n\nLOW PERFORMERS (Avoid):\n{losers}"
    except Exception as e:
        return f"Analytics initializing ({e}): use high-retention 35-second seamless-loop structure."

# 3. LIVE US VIRAL IDEATION: Harvest Reddit Top Daily + US Google Trends RSS + YouTube US Most Popular
def harvest_us_viral_signals(youtube_client):
    signals = []
    headers = {"User-Agent": "USStoryAutomation/2.0 (by /u/autonomous_creator)"}
    for sub in ["todayilearned", "Damnthatsinteresting", "UnresolvedMysteries"]:
        try:
            r = requests.get(f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=8", headers=headers, timeout=15)
            if r.status_code == 200:
                for p in r.json()["data"]["children"]:
                    signals.append(f"[Reddit US Viral] {p['data']['title']}")
        except Exception:
            pass
    try:
        r = requests.get("https://trends.google.com/trending/rss?geo=US", headers=headers, timeout=15)
        if r.status_code == 200:
            root = ET.fromstring(r.text)
            for item in root.findall(".//item/title")[:10]:
                signals.append(f"[US Google Trend] {item.text}")
    except Exception:
        pass
    try:
        res = youtube_client.videos().list(part="snippet", chart="mostPopular", regionCode="US", maxResults=10).execute()
        for item in res.get("items", []):
            signals.append(f"[YouTube US Trending] {item['snippet']['title']}")
    except Exception:
        pass
    return signals
    
def call_gemini_with_fallback(client, contents, config=None):
    for model_name in ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"]:
        try:
            return client.models.generate_content(model=model_name, contents=contents, config=config)
        except Exception as e:
            print(f"Model {model_name} busy ({e}), trying fallback in 10s...")
            time.sleep(10)
    raise RuntimeError("All Gemini models temporarily unavailable.")
    
# 4. GEMINI 2.5 FLASH RESEARCH + VIRAL CRITIC + SEAMLESS LOOP ARCHITECT
def generate_verified_storyboard(signals, used_topics, analytics_feedback):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    research_prompt = f"""
    You are an elite US YouTube Shorts Story Director (style of Zack D. Films, Fern, and Veritasium).
    Live US Viral Signals today:
    {json.dumps(signals[:25])}

    Channel Self-Learning Analytics Report:
    {analytics_feedback}

    Topics already published (NEVER REPEAT ANY OF THESE):
    {json.dumps(used_topics[-60:])}

    1. Select or synthesize ONE bizarre, high-curiosity 'What-If' physics/medical dilemma, survival scenario, or scientific paradox with massive US appeal.
    2. Use verified scientific mechanisms, exact numbers, and a counter-intuitive twist.
    3. Write a 10-scene script (~36 seconds total) where:
       - Scene 1 starts mid-crisis in the first 1.5 seconds (zero intro filler).
       - Scenes 2 to 9 escalate tension and explain the exact physical/biological mechanism.
       - Scene 10 delivers the twist AND ends with an incomplete 4-word bridge phrase (e.g. '...which is exactly why') that flows grammatically into the first word of Scene 1 for a seamless loop.
    """
    draft = call_gemini_with_fallback(client, research_prompt)
    time.sleep(5)

    critic_prompt = f"""
    Refine this researched draft so it achieves 75%+ Stayed-to-Watch and 80%+ Average Percentage Viewed:
    {draft.text}

    Rules:
    - Exactly 10 scenes. Each scene narration MUST be 1 punchy sentence (10 to 16 words) in natural US English.
    - Scene 10 narration must end mid-sentence so it loops seamlessly into Scene 1 narration.
    - Provide a locked 'style_bible' string so all 10 AI images share an identical 3D cinematic aesthetic and protagonist.
    Return ONLY valid JSON matching this exact structure:
    {{
      "topic_id": "unique-kebab-case-slug",
      "title": "Curiosity-gap title under 65 chars #Shorts",
      "description": "2-sentence original story summary with key facts.",
      "tags": ["whatif", "science", "curiosity", "story", "explained"],
      "style_bible": "3D stylized cinematic render, stylized character in yellow hoodie, dramatic volumetric lighting, Unreal Engine 5, 8k",
      "scenes": [
        {{"narration": "Sentence for scene.", "visual_prompt": "Specific camera angle, subject action, and lighting (no text)"}}
      ]
    }}
    """
    final = call_gemini_with_fallback(
        client,
        critic_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    return json.loads(final.text)

# 5. PURE AI VISUALS (POLLINATIONS FLUX) + EDGE-TTS CLI SUBTITLES + FFMPEG RENDERER
def render_story_video(storyboard):
    os.makedirs("build", exist_ok=True)
    seed_base = random.randint(10000, 99999)

    voice = random.choice(["en-US-ChristopherNeural", "en-US-GuyNeural", "en-US-EricNeural", "en-US-RogerNeural"])
    rate = f"+{random.randint(5, 9)}%"
    pitch = f"{random.choice(['-', '+'])}{random.randint(1, 2)}Hz"
    drone_freq = random.choice([52, 55, 58, 62, 65])

    segment_entries = []
    for i, scene in enumerate(storyboard["scenes"]):
        audio_path = f"build/voice_{i}.mp3"
        vtt_path = f"build/sub_{i}.vtt"
        img_path = f"build/scene_{i}.jpg"
        seg_path = f"build/seg_{i}.mp4"

        subprocess.run([
            "edge-tts",
            "--voice", voice,
            f"--rate={rate}",
            f"--pitch={pitch}",
            "--text", scene["narration"],
            "--write-media", audio_path,
            "--write-subtitles", vtt_path
        ], check=True)

        full_prompt = f"{storyboard['style_bible']}, {scene['visual_prompt']}, no text, no letters, clean render"
        img_saved = False
        for attempt in range(4):
            model_name = "flux" if attempt < 3 else "turbo"
            url = (
                f"https://gen.pollinations.ai/image/{urllib.parse.quote(full_prompt)}"
                f"?model={model_name}&width=1080&height=1920&seed={seed_base + i + attempt}&nologo=true"
            )
            try:
                resp = requests.get(url, timeout=90)
                if resp.status_code == 200 and len(resp.content) > 12000:
                    with open(img_path, "wb") as f:
                        f.write(resp.content)
                    img_saved = True
                    break
            except Exception:
                pass
            time.sleep(4)

        if not img_saved:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=#101828:s=1080x1920:d=1",
                "-frames:v", "1", img_path
            ], check=True)

        dur_str = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path
        ], text=True).strip()
        duration = max(float(dur_str), 1.5)
        frames = int(duration * 30)

        zoom_expr = "min(zoom+0.0022,1.26)" if i % 2 == 0 else "if(eq(on,1),1.26,max(zoom-0.0022,1.0))"
        sub_style = "FontName=DejaVu Sans,FontSize=15,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=68"
        vf_filter = (
            f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30,"
            f"subtitles={vtt_path}:force_style='{sub_style}'"
        )
        subprocess.run([
            "ffmpeg", "-y", "-i", img_path, "-i", audio_path,
            "-vf", vf_filter, "-c:v", "libx264", "-t", str(duration),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", seg_path
        ], check=True)
        segment_entries.append(f"file 'seg_{i}.mp4'")

    with open("build/concat.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(segment_entries))
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "build/concat.txt", "-c", "copy", "build/raw.mp4"
    ], check=True)

    subprocess.run([
        "ffmpeg", "-y", "-i", "build/raw.mp4",
        "-f", "lavfi", "-i", f"aevalsrc='0.035*sin(2*PI*{drone_freq}*t)+0.025*sin(2*PI*{drone_freq*2}*t)':s=44100",
        "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "final_video.mp4"
    ], check=True)
    return "final_video.mp4"

# 6. ZERO-CLICK YOUTUBE UPLOAD WITH HUMAN JITTER & ALL COMPLIANCE CHECKBOXES
def publish_with_human_jitter(youtube_client, video_path, storyboard):
    jitter_mins = random.randint(16, 44)
    publish_at = (datetime.now(timezone.utc) + timedelta(minutes=jitter_mins)).strftime("%Y-%m-%dT%H:%M:%SZ")

    body = {
        "snippet": {
            "title": storyboard["title"][:70],
            "description": f"{storyboard['description'][:400]}\n\n#Shorts #whatif #science",
            "tags": storyboard.get("tags", ["whatif", "science", "shorts"])[:6],
            "categoryId": "28",
            "defaultLanguage": "en-US",
            "defaultAudioLanguage": "en-US"
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
            "embeddable": True,
            "publicStatsViewable": True
        }
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    res = youtube_client.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    return res["id"], publish_at

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
            "https://www.googleapis.com/auth/yt-analytics.readonly"
        ]
    )
    yt = build("youtube", "v3", credentials=creds)

    memory = load_memory()
    sync_existing_channel_history(yt, memory)
    enforce_warmup_gate(memory)

    analytics_report = fetch_self_learning_feedback(creds, memory)
    signals = harvest_us_viral_signals(yt)
    storyboard = generate_verified_storyboard(signals, memory["used_topics"], analytics_report)
    final_mp4 = render_story_video(storyboard)
    video_id, scheduled_time = publish_with_human_jitter(yt, final_mp4, storyboard)

    memory["used_topics"].append(storyboard["topic_id"])
    memory.setdefault("published_log", {})[video_id] = {
        "title": storyboard["title"],
        "hook": storyboard["scenes"][0]["narration"],
        "scheduled_for": scheduled_time
    }
    save_memory(memory)
    print(f"Success! Video {video_id} scheduled for public release at {scheduled_time}")

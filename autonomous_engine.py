import os, re, json, time, random, urllib.parse, subprocess, xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta, timezone
import requests
from google import genai
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

# 0. AUTO-SYNC EXISTING CHANNEL VIDEOS ON FIRST RUN
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

# 1. ANTI-BAN SHIELD: 14-Day Warm-Up Gate
def enforce_warmup_gate(memory):
    total_uploaded = len(memory.get("used_topics", []))
    current_utc_hour = datetime.now(timezone.utc).hour
    is_scheduled = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    if is_scheduled and total_uploaded < 14 and current_utc_hour not in (13, 14, 15):
        print(f"Warm-up gate active ({total_uploaded}/14 videos): skipping secondary slot.")
        raise SystemExit(0)

# 2. SELF-LEARNING ANALYTICS LOOP
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
        return f"TOP PERFORMERS (Replicate style):\n{winners}\n\nLOW PERFORMERS (Avoid):\n{losers}"
    except Exception as e:
        return f"Analytics initializing ({e}): use high-retention 35-second seamless-loop structure."

# 3. LIVE US VIRAL IDEATION
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

def extract_valid_json(raw_text):
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start:end + 1]
    data = json.loads(cleaned)
    if "scenes" in data and len(data["scenes"]) >= 6:
        return data
    raise ValueError("JSON missing required scenes array")

# 4. ZERO-FAILURE MULTI-CLOUD LLM ROUTER (Google Gemini/Gemma -> Pollinations OpenAI/Mistral/DeepSeek -> Built-in Engine)
def generate_verified_storyboard(signals, used_topics, analytics_feedback):
    master_prompt = f"""
    You are an elite US YouTube Shorts Story Director (style of Zack D. Films, Fern, and Veritasium).
    Live US Viral Signals today:
    {json.dumps(signals[:20])}

    Channel Self-Learning Analytics Report:
    {analytics_feedback}

    Topics already published (NEVER REPEAT ANY OF THESE):
    {json.dumps(used_topics[-50:])}

    Task:
    1. Pick or synthesize ONE bizarre, high-curiosity 'What-If' physics/medical dilemma, survival scenario, or scientific paradox with massive US appeal.
    2. Write an original 10-scene script (~36 seconds total) in punchy US English (10 to 16 words per scene):
       - Scene 1 starts mid-crisis in the first 1.5 seconds (zero intro filler).
       - Scenes 2 to 9 escalate tension and explain the exact physical or biological mechanism with real numbers.
       - Scene 10 delivers a shocking twist AND ends with an incomplete 4-word bridge phrase (e.g. '...which is exactly why') that connects grammatically into the first word of Scene 1 for a seamless loop.
    3. Return ONLY valid raw JSON (no markdown fences) matching this exact schema:
    {{
      "topic_id": "unique-kebab-case-slug",
      "title": "Curiosity-gap title under 65 chars #Shorts",
      "description": "2-sentence original story summary with key scientific facts.",
      "tags": ["whatif", "science", "curiosity", "story", "explained"],
      "style_bible": "3D stylized cinematic render, stylized character in yellow hoodie, dramatic volumetric lighting, Unreal Engine 5, 8k",
      "scenes": [
        {{"narration": "Sentence for scene.", "visual_prompt": "Specific camera angle, subject action, and lighting (no text)"}}
      ]
    }}
    """

    # LAYER 1: Try Google AI Studio Models (Gemini 3.8, 3.6, 3.5-Lite, and Gemma 3 27B)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key:
        client = genai.Client(api_key=api_key)
        for g_model in ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemma-3-27b-it"]:
            try:
                print(f"Trying Google model: {g_model}...")
                res = client.models.generate_content(model=g_model, contents=master_prompt)
                data = extract_valid_json(res.text)
                print(f"Storyboard generated successfully via {g_model}!")
                return data
            except Exception as e:
                print(f"Google model {g_model} unavailable ({e}), switching to next...")
                time.sleep(3)

    # LAYER 2: Keyless Pollinations OpenAI-Compatible Endpoint (openai, mistral, deepseek)
    for p_model in ["openai", "mistral", "deepseek"]:
        try:
            print(f"Trying Keyless Backup Cloud LLM (Pollinations/{p_model})...")
            resp = requests.post(
                "https://text.pollinations.ai/openai",
                headers={"Content-Type": "application/json"},
                json={
                    "model": p_model,
                    "messages": [
                        {"role": "system", "content": "You output only valid raw JSON objects with no markdown formatting."},
                        {"role": "user", "content": master_prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "seed": random.randint(1, 99999)
                },
                timeout=60
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                data = extract_valid_json(content)
                print(f"Storyboard generated successfully via Pollinations/{p_model}!")
                return data
        except Exception as e:
            print(f"Pollinations/{p_model} backup busy ({e}), trying next...")
            time.sleep(3)

    # LAYER 3: Keyless Pollinations Direct GET Endpoint
    try:
        print("Trying Pollinations Direct GET JSON endpoint...")
        short_prompt = (
            "Return ONLY raw JSON for a 10-scene viral US science What-If YouTube Short not in "
            f"{json.dumps(used_topics[-10:])} with keys: topic_id, title, description, tags, style_bible, "
            "and scenes (list of 10 objects with narration and visual_prompt)."
        )
        r = requests.get(
            f"https://text.pollinations.ai/{urllib.parse.quote(short_prompt)}?model=openai&json=true&seed={random.randint(1,9999)}",
            timeout=60
        )
        if r.status_code == 200:
            return extract_valid_json(r.text)
    except Exception as e:
        print(f"Direct GET backup skipped ({e})")

    # LAYER 4: Unbreakable Built-in Viral Story Synthesizer (Zero External LLM Dependency)
    print("Activating built-in autonomous story bank...")
    stamp = int(time.time()) % 10000
    return {
        "topic_id": f" Mariana-Trench-Implosion-Physics-{stamp}",
        "title": f"What If Your Submarine Hull Cracked at 36,000 Feet? #{stamp} #Shorts",
        "description": "At the bottom of the Mariana Trench, water pressure hits 15,750 psi—over 1,000 times surface atmospheric pressure.",
        "tags": ["whatif", "science", "physics", "curiosity", "shorts"],
        "style_bible": "3D stylized cinematic render, stylized character in yellow hoodie, dramatic volumetric lighting, Unreal Engine 5, 8k",
        "scenes": [
            {"narration": "if a hairline crack opens on your submarine at thirty-six thousand feet, you won't drown.", "visual_prompt": "Deep ocean submersible at Mariana Trench floor with glowing hairline crack on titanium hull"},
            {"narration": "At the bottom of the Mariana Trench, water crushes inward at fifteen thousand pounds per square inch.", "visual_prompt": "Massive glowing pressure arrows pressing against yellow-hooded character inside submarine cockpit"},
            {"narration": "That is the equivalent of fifty jumbo jets stacked directly on top of a single person.", "visual_prompt": "3D cross-section visualization of extreme ocean depth pressure gauges hitting red zone"},
            {"narration": "The moment the titanium hull gives way, water jets inward at Mach two.", "visual_prompt": "Supersonic wall of water bursting inward in ultra slow motion inside glowing chamber"},
            {"narration": "The air pocket inside doesn't just leak out—it compresses twenty-five hundred times in one millisecond.", "visual_prompt": "Glowing air molecules compressing violently into a blinding white-hot sphere"},
            {"narration": "Physics turns that trapped air into a diesel piston, superheating the cabin to five thousand degrees.", "visual_prompt": "Blinding thermal shockwave inside spherical hull hotter than the surface of the sun"},
            {"narration": "The human brain takes one hundred fifty milliseconds just to register a pain signal from your nerves.", "visual_prompt": "3D translucent brain and glowing neural pathway frozen in slow-motion time"},
            {"narration": "Yet the entire implosion finishes in less than two milliseconds from start to finish.", "visual_prompt": "Digital millisecond stopwatch frozen at 0.002 seconds beside collapsing pressure sphere"},
            {"narration": "The hull collapses faster than the speed of sound traveling through your own nervous system.", "visual_prompt": "Acoustic shockwave ring expanding through dark abyssal ocean water"},
            {"narration": "You would be turned to ash before your brain even knew something happened, which is why", "visual_prompt": "Silent deep sea floor with glowing bioluminescent particles drifting in darkness"}
        ]
    }

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
        vf_with_subs = (
            f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30,"
            f"subtitles={vtt_path}:force_style='{sub_style}'"
        )
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", img_path, "-i", audio_path,
                "-vf", vf_with_subs, "-c:v", "libx264", "-t", str(duration),
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", seg_path
            ], check=True)
        except Exception:
            # Fallback without subtitle filter if VTT is ever malformed
            vf_no_subs = (
                f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30"
            )
            subprocess.run([
                "ffmpeg", "-y", "-i", img_path, "-i", audio_path,
                "-vf", vf_no_subs, "-c:v", "libx264", "-t", str(duration),
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

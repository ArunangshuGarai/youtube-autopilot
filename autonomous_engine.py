import os, re, json, time, math, random, shutil, urllib.parse, subprocess, xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta, timezone
import numpy as np
import soundfile as sf
import requests
from PIL import Image, ImageDraw, ImageFont, ImageStat, ImageEnhance
from google import genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

MEMORY_FILE = "memory.json"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
}

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"used_topics": [], "published_log": {}, "channel_synced": False}

def save_memory(mem):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mem, f, indent=2)

# 0. AUTO-SYNC EXISTING CHANNEL VIDEOS
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
    except Exception as e:
        print(f"Channel sync note: {e}")

# 1. WARM-UP GATE
def enforce_warmup_gate(memory):
    total_uploaded = len(memory.get("used_topics", []))
    current_utc_hour = datetime.now(timezone.utc).hour
    is_scheduled = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    if is_scheduled and total_uploaded < 14 and current_utc_hour not in (13, 14, 15):
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
            maxResults=10
        ).execute()
        rows = report.get("rows", [])
        if not rows:
            return "Prioritize intense survival, dark history, and bizarre physics stories."
        pub_log = memory.get("published_log", {})
        scored = []
        for r in rows[:3]:
            vid_id, views, engaged, avg_pct, subs = r
            meta = pub_log.get(vid_id, {"title": vid_id})
            scored.append(f"'{meta['title']}' ({engaged} engaged views, {avg_pct:.1f}% retention)")
        return "Top Winners: " + "; ".join(scored)
    except Exception:
        return "Focus on visceral 1.5-second hooks and fast multi-angle visual storytelling."

# 3. LIVE US VIRAL IDEATION
def harvest_us_viral_signals(youtube_client):
    signals = []
    for sub in ["todayilearned", "Damnthatsinteresting", "UnresolvedMysteries"]:
        try:
            r = requests.get(f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=8", headers=BROWSER_HEADERS, timeout=15)
            if r.status_code == 200:
                for p in r.json()["data"]["children"]:
                    signals.append(p["data"]["title"])
        except Exception:
            pass
    try:
        r = requests.get("https://trends.google.com/trending/rss?geo=US", headers=BROWSER_HEADERS, timeout=15)
        if r.status_code == 200:
            root = ET.fromstring(r.text)
            for item in root.findall(".//item/title")[:8]:
                signals.append(item.text)
    except Exception:
        pass
    return signals

def extract_valid_json(raw_text):
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start:end + 1]
    data = json.loads(cleaned)
    if "scenes" in data and len(data["scenes"]) >= 8:
        return data
    raise ValueError("Invalid scenes JSON")

# 4. VIRAL STORY ARCHITECT
def generate_storyboard(signals, used_topics, analytics_feedback):
    prompt = f"""
    You are an elite US Viral Shorts Director (combining the comedic stick-figure wit of 'Sam O'Nella Academy' & 'StickFigure Explains' with the visceral pacing of 'Zack D. Films').
    Live US Viral Inspirations: {json.dumps(signals[:15])}
    Channel Performance Feedback: {analytics_feedback}
    Already Used Topics (DO NOT REPEAT): {json.dumps(used_topics[-50:])}

    Write a gripping, darkly funny, ultra-fast-paced 8-scene Stick-Figure Story (~32 seconds) starring an expressive hand-drawn character in an extreme historical, medical, or survival scenario.
    Rules:
    - Title: Natural, irresistible US curiosity title (NO random numbers, max 60 chars, end with #Shorts).
    - thumb_text: 2 to 3 ALL-CAPS impact words for the thumbnail (e.g. 'FATAL MISTAKE!', 'NEVER TOUCH THIS', 'WORST JOB EVER').
    - Scene 1 starts mid-action in the first 1.5 seconds.
    - Scenes 2 to 7 escalate with specific, mind-blowing real facts and numbers.
    - Scene 8 delivers the payoff AND ends with a 3-word incomplete bridge ('...which explains why') that loops seamlessly into Scene 1.
    - Each visual_prompt MUST describe a vivid, high-contrast 2D illustrated cartoon/stick-figure comic scene with dramatic lighting, clear subject action, and rich background detail (NO text in image).

    Return ONLY valid raw JSON:
    {{
      "topic_id": "unique-kebab-slug",
      "title": "Why Roman Emperors Drank Poison Every Morning #Shorts",
      "thumb_text": "DAILY POISON?!",
      "description": "Ancient rulers terrified of assassination used a bizarre biological trick known as Mithridatism...",
      "tags": ["storytime", "explained", "history", "science", "whatif", "shorts"],
      "style_bible": "High-contrast 2D graphic novel cartoon illustration, expressive white stick-figure protagonist with bold ink outlines, rich moody cinematic background lighting, Sam O'Nella meets Kurzgesagt color palette, crisp vector shading",
      "scenes": [
        {{
          "narration": "Punchy 11-to-14-word sentence spoken with intense documentary energy.",
          "visual_prompt": "Detailed scene action and camera angle, no text or letters"
        }}
      ]
    }}
    """

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key:
        client = genai.Client(api_key=api_key)
        for wait_sec, m_name in [(2, "gemini-3.8-flash"), (10, "gemini-3.5-flash-lite"), (18, "gemma-3-27b-it"), (25, "gemini-3.8-flash")]:
            try:
                res = client.models.generate_content(model=m_name, contents=prompt)
                return extract_valid_json(res.text)
            except Exception as e:
                print(f"Model {m_name} busy ({e}), retrying in {wait_sec}s...")
                time.sleep(wait_sec)

    for p_model in ["openai", "mistral"]:
        try:
            r = requests.post(
                "https://text.pollinations.ai/",
                headers={"Content-Type": "application/json", **BROWSER_HEADERS},
                json={"messages": [{"role": "user", "content": prompt}], "model": p_model, "jsonMode": True},
                timeout=60
            )
            if r.status_code == 200:
                return extract_valid_json(r.text)
        except Exception:
            pass

    # Curated backup stories if all cloud text APIs are unreachable
    backups = [
        {
            "topic_id": "whaling-ship-essex-survival-story",
            "title": "Why Starving Sailors Refused to Land on This Island #Shorts",
            "thumb_text": "FATAL ISLAND!",
            "description": "In 1820, after a sperm whale sank the whaleship Essex, the crew made a navigation mistake that cost them everything.",
            "tags": ["storytime", "history", "survival", "explained", "whatif", "shorts"],
            "style_bible": "High-contrast 2D graphic novel cartoon illustration, expressive white stick-figure protagonist with bold black ink outlines, dramatic dark ocean and crimson sky lighting, crisp shading",
            "scenes": [
                {"narration": "when an eighty-ton sperm whale rammed their ship in eighteen twenty, twenty sailors jumped into tiny wooden boats.", "visual_prompt": "Giant black whale smashing wooden sailing ship in stormy ocean, expressive cartoon stick-figure sailors in lifeboat"},
                {"narration": "The nearest lush tropical islands were the Marquesas, sitting just twelve hundred miles downwind.", "visual_prompt": "Weathered nautical map with glowing green tropical island close by and skull icon"},
                {"narration": "With the wind at their backs, they could have sailed there in less than two weeks.", "visual_prompt": "Small wooden whaleboat speeding across blue ocean waves under billowing white sail"},
                {"narration": "Instead, the captain ordered the starving crew to turn around and sail three thousand miles into empty ocean.", "visual_prompt": "Terrified cartoon captain pointing compass into dark endless storm clouds"},
                {"narration": "They were terrified of an exaggerated rumor that the island tribes would eat them alive on the beach.", "visual_prompt": "Dark shadowy jungle shoreline with glowing eyes in the bushes, comic illustration"},
                {"narration": "By choosing open water, their bread soaked in seawater, forcing them to drink their own dehydration fluid.", "visual_prompt": "Exhausted stick-figure sailors under blistering red sun in drifting wooden boat"},
                {"narration": "After ninety days adrift, only eight men survived by doing the exact unthinkable thing they feared most.", "visual_prompt": "Lone battered lifeboat rescued by tall ship in dramatic golden sunset light"},
                {"narration": "Fear of a rumor drove them straight into a three-month nightmare at sea, which explains why", "visual_prompt": "Sinking wooden ship hull disappearing into deep dark ocean abyss"}
            ]
        }
    ]
    return backups[0]

# 5. HUMAN-GRADE KOKORO-82M VOICE SYNTHESIS + CINEMATIC SFX GENERATOR
KOKORO_ENGINE = None
def synthesize_human_voice(text, out_wav):
    """Uses Kokoro-82M neural voice (blending am_adam + am_michael) for rich human storytelling."""
    global KOKORO_ENGINE
    try:
        from kokoro_onnx import Kokoro
        if KOKORO_ENGINE is None and os.path.exists("kokoro-v1.0.onnx") and os.path.exists("voices-v1.0.bin"):
            KOKORO_ENGINE = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
        if KOKORO_ENGINE is not None:
            v_adam = KOKORO_ENGINE.get_voice_style("am_adam")
            v_michael = KOKORO_ENGINE.get_voice_style("am_michael")
            blended_voice = (v_adam * 0.60) + (v_michael * 0.40)
            samples, sr = KOKORO_ENGINE.create(text, voice=blended_voice, speed=1.10, lang="en-us")
            # Trim leading/trailing silence so cuts are razor-tight
            non_silent = np.where(np.abs(samples) > 0.008)[0]
            if len(non_silent) > 100:
                samples = samples[max(0, non_silent[0] - int(sr * 0.04)):min(len(samples), non_silent[-1] + int(sr * 0.08))]
            sf.write(out_wav, samples, sr)
            return
    except Exception as e:
        print(f"Kokoro fallback to edge-tts: {e}")

    subprocess.run([
        "edge-tts", "--voice", "en-US-ChristopherNeural", "--rate=+12%", "--pitch=-2Hz",
        "--text", text, "--write-media", out_wav
    ], check=True)

def generate_transition_sfx(out_sfx_wav, duration=0.38, sr=44100):
    """Synthesizes a real cinematic sub-bass impact thud + air whoosh for camera cuts (zero buzzing hum)."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # Exponential pitch-drop sub-bass boom (115Hz -> 28Hz)
    freq = 115.0 * np.exp(-t * 9.5) + 28.0
    phase = 2 * np.pi * np.cumsum(freq) / sr
    thud = np.sin(phase) * np.exp(-t * 8.0) * 0.32
    # Filtered air whoosh
    noise = np.random.normal(0, 1, len(t))
    window = np.sin(np.pi * t / duration) ** 2
    whoosh = np.convolve(noise, np.ones(18)/18, mode="same") * window * 0.08
    sfx = np.clip(thud + whoosh, -0.9, 0.9).astype(np.float32)
    sf.write(out_sfx_wav, sfx, sr)

# 6. DUAL-CLOUD REAL AI IMAGE FETCHER (Hugging Face FLUX.1-schnell + Pollinations 768x1344 with Browser Headers)
HF_CLIENT = None
def fetch_real_ai_illustration(prompt_text, idx, seed_base):
    """Guarantees a real, high-detail AI illustration using Hugging Face FLUX.1-schnell and Pollinations."""
    global HF_CLIENT
    # Tier 1: Hugging Face black-forest-labs/FLUX.1-schnell via Gradio Client
    try:
        from gradio_client import Client
        if HF_CLIENT is None:
            HF_CLIENT = Client("black-forest-labs/FLUX.1-schnell")
        res = HF_CLIENT.predict(
            prompt=prompt_text,
            seed=seed_base + idx,
            randomize_seed=False,
            width=768,
            height=1344,
            num_inference_steps=4,
            api_name="/infer"
        )
        img_file = res[0] if isinstance(res, (list, tuple)) else res
        if isinstance(img_file, dict) and "path" in img_file:
            img_file = img_file["path"]
        im = Image.open(img_file).convert("RGB").resize((1080, 1920), Image.Resampling.LANCZOS)
        if max(ImageStat.Stat(im).stddev) > 22.0:
            print(f"Scene {idx}: Rendered via HuggingFace FLUX.1-schnell!")
            return im
    except Exception as e:
        print(f"Scene {idx} HF FLUX note ({e}), switching to Pollinations 768x1344...")

    # Tier 2: Pollinations 64-aligned 768x1344 with full Desktop Chrome User-Agent Header
    encoded = urllib.parse.quote(prompt_text)
    for attempt, model_name in enumerate(["flux", "turbo", "flux", "turbo"]):
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=768&height=1344&model={model_name}&seed={seed_base + idx * 10 + attempt}&nologo=true&enhance=true"
        )
        try:
            r = requests.get(url, headers=BROWSER_HEADERS, timeout=60)
            if r.status_code == 200 and len(r.content) > 15000:
                tmp_p = f"build/dl_{idx}_{attempt}.jpg"
                with open(tmp_p, "wb") as f:
                    f.write(r.content)
                im = Image.open(tmp_p).convert("RGB").resize((1080, 1920), Image.Resampling.LANCZOS)
                if max(ImageStat.Stat(im).stddev) > 22.0:
                    print(f"Scene {idx}: Rendered via Pollinations/{model_name}!")
                    return im
        except Exception as e:
            print(f"Pollinations attempt {attempt} note: {e}")
        time.sleep(3)

    raise RuntimeError(f"Could not generate AI artwork for Scene {idx}")

# 7. DYNAMIC 2-WORD POP-IN '.ASS' KARAOKE SUBTITLE GENERATOR (Unobstructed Center-Lower Pop-In)
def format_ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def write_pop_in_ass_subtitles(narration, duration, ass_path):
    """Flashes 2 to 3 words at a time with a 125% -> 100% scale pop animation so text never blocks the video."""
    words = narration.strip().split()
    chunks = [" ".join(words[i:i+2]).upper() for i in range(0, len(words), 2)]
    if not chunks:
        chunks = ["WATCH THIS"]
    chunk_dur = max(duration / len(chunks), 0.25)

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: PopYellow,DejaVu Sans,88,&H0000EAFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,8,4,2,60,60,440,1
Style: PopWhite,DejaVu Sans,88,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,8,4,2,60,60,440,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for idx, chunk in enumerate(chunks):
        t_start = idx * chunk_dur
        t_end = min((idx + 1) * chunk_dur, duration)
        style = "PopYellow" if idx % 2 == 0 else "PopWhite"
        safe_chunk = chunk.replace("{", "").replace("}", "")
        pop_tag = r"{\fscx128\fscy128\t(0,85,\fscx100\fscy100)}"
        lines.append(f"Dialogue: 0,{format_ass_time(t_start)},{format_ass_time(t_end)},{style},,0,0,0,,{pop_tag}{safe_chunk}")

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def build_custom_shorts_thumbnail(base_img, thumb_text):
    thumb = ImageEnhance.Contrast(base_img.copy()).enhance(1.20)
    thumb = ImageEnhance.Color(thumb).enhance(1.25)
    draw = ImageDraw.Draw(thumb)
    try:
        hero_font = ImageFont.truetype(FONT_BOLD, 96)
    except Exception:
        hero_font = ImageFont.load_default()

    # Clean, bold top hook text with thick black stroke (no ugly solid box covering art)
    draw.text((540, 210), thumb_text.upper()[:18], font=hero_font, fill=(255, 235, 0), stroke_width=12, stroke_fill=(0, 0, 0), anchor="mm")
    thumb_path = "build/thumbnail.jpg"
    thumb.save(thumb_path, "JPEG", quality=94)
    return thumb_path

# 8. MULTI-SHOT CINEMATIC VIDEOGRAPHY & EDITING ENGINE (2 Camera Angles per Scene + Flash Cuts + SFX)
def render_story_video(storyboard):
    os.makedirs("build", exist_ok=True)
    seed_base = random.randint(10000, 99999)
    sfx_wav = "build/whoosh_thud.wav"
    generate_transition_sfx(sfx_wav)

    segment_entries = []
    first_scene_img = None

    for i, scene in enumerate(storyboard["scenes"]):
        raw_wav = f"build/raw_v_{i}.wav"
        mixed_audio = f"build/voice_{i}.m4a"
        ass_path = f"build/sub_{i}.ass"
        wide_img_path = f"build/wide_{i}.jpg"
        close_img_path = f"build/close_{i}.jpg"
        seg_path = f"build/seg_{i}.mp4"

        # 8A. Synthesize human-grade voiceover via Kokoro-82M
        synthesize_human_voice(scene["narration"], raw_wav)

        # Mix voiceover + broadcast EQ/compression + subtle transition thud at t=0
        subprocess.run([
            "ffmpeg", "-y", "-i", raw_wav, "-i", sfx_wav,
            "-filter_complex",
            "[0:a]acompressor=threshold=-16dB:ratio=3.5:attack=5:release=60:makeup=3,equalizer=f=130:width_type=h:width=90:g=3[v];"
            "[v][1:a]amix=inputs=2:duration=first:weights='1.0 0.35'[aout]",
            "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", mixed_audio
        ], check=True)

        dur_str = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", mixed_audio
        ], text=True).strip()
        duration = max(float(dur_str), 1.8)
        half_dur = duration / 2.0

        # 8B. Fetch real AI scene artwork & create Shot A (Wide) + Shot B (1.35x Dramatic Close-Up Cut)
        full_prompt = f"{storyboard['style_bible']}, {scene['visual_prompt']}, clean illustration, no text, no watermark"
        master_img = fetch_real_ai_illustration(full_prompt, i, seed_base)
        if i == 0:
            first_scene_img = master_img

        # Shot A: Full 1080x1920 frame
        master_img.save(wide_img_path, "JPEG", quality=95)
        # Shot B: 1.35x Tight Dramatic Crop on the focal center-upper action (gives an instant mid-sentence camera cut!)
        crop_box = (140, 180, 940, 1602)
        closeup_img = master_img.crop(crop_box).resize((1080, 1920), Image.Resampling.LANCZOS)
        closeup_img = ImageEnhance.Contrast(closeup_img).enhance(1.10)
        closeup_img.save(close_img_path, "JPEG", quality=95)

        # 8C. Write 2-Word Pop-In ASS Subtitles for this scene
        write_pop_in_ass_subtitles(scene["narration"], duration, ass_path)

        # 8D. Render Shot A (Wide Punch-In + Optical Flash) & Shot B (Close-Up Pan), then join with Pop-In Captions
        frames_a = max(int(half_dur * 30), 15)
        frames_b = max(int((duration - half_dur) * 30), 15)
        shot_a_mp4 = f"build/shot_a_{i}.mp4"
        shot_b_mp4 = f"build/shot_b_{i}.mp4"
        joined_v = f"build/joined_v_{i}.mp4"

        subprocess.run([
            "ffmpeg", "-y", "-i", wide_img_path,
            "-vf", f"zoompan=z='min(zoom+0.0035,1.22)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames_a}:s=1080x1920:fps=30,fade=t=in:st=0:d=0.10:color=white",
            "-c:v", "libx264", "-t", str(half_dur), "-pix_fmt", "yuv420p", shot_a_mp4
        ], check=True)

        pan_dir = "iw/2-(iw/zoom/2)+35*sin(2*PI*on/45)"
        subprocess.run([
            "ffmpeg", "-y", "-i", close_img_path,
            "-vf", f"zoompan=z='1.12':x='{pan_dir}':y='ih/2-(ih/zoom/2)':d={frames_b}:s=1080x1920:fps=30",
            "-c:v", "libx264", "-t", str(duration - half_dur), "-pix_fmt", "yuv420p", shot_b_mp4
        ], check=True)

        with open(f"build/pair_{i}.txt", "w") as pf:
            pf.write(f"file 'shot_a_{i}.mp4'\nfile 'shot_b_{i}.mp4'\n")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"build/pair_{i}.txt", "-c", "copy", joined_v], check=True)

        # Burn 2-word pop-in ASS captions + cinematic vignette & color grade
        subprocess.run([
            "ffmpeg", "-y", "-i", joined_v, "-i", mixed_audio,
            "-vf", f"eq=contrast=1.08:saturation=1.18,vignette=PI/6,ass={ass_path}",
            "-c:v", "libx264", "-t", str(duration), "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-shortest", seg_path
        ], check=True)
        segment_entries.append(f"file 'seg_{i}.mp4'")

    thumb_path = build_custom_shorts_thumbnail(first_scene_img, storyboard.get("thumb_text", "WAIT FOR IT"))

    with open("build/concat.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(segment_entries))
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "build/concat.txt", "-c", "copy", "final_video.mp4"
    ], check=True)
    return "final_video.mp4", thumb_path

# 9. AUTOMATED QA INSPECTOR
def auto_qa_verify_video(video_path, thumb_path, storyboard):
    if not os.path.exists(video_path) or os.path.getsize(video_path) < 350000:
        raise RuntimeError("QA Gate Blocked: Video file too small.")
    for idx in range(len(storyboard["scenes"])):
        im = Image.open(f"build/wide_{idx}.jpg")
        if max(ImageStat.Stat(im).stddev) < 22.0:
            raise RuntimeError(f"QA Gate Blocked: Scene {idx} failed visual richness test.")
    storyboard["title"] = re.sub(r"#\d+\s*", "", storyboard["title"]).strip()
    if "#Shorts" not in storyboard["title"]:
        storyboard["title"] = f"{storyboard['title'][:58]} #Shorts"
    print(f"QA Gate Passed: {storyboard['title']}")

# 10. YOUTUBE UPLOAD (WITH AI DISCLOSURE = FALSE & NOT MADE FOR KIDS = FALSE)
def publish_with_thumbnail(youtube_client, video_path, thumb_path, storyboard):
    jitter_mins = random.randint(15, 35)
    publish_at = (datetime.now(timezone.utc) + timedelta(minutes=jitter_mins)).strftime("%Y-%m-%dT%H:%M:%SZ")

    body = {
        "snippet": {
            "title": storyboard["title"][:70],
            "description": (
                f"{storyboard['description']}\n\n"
                "#Shorts #storytime #explained #history #science #whatif"
            ),
            "tags": storyboard.get("tags", ["storytime", "explained", "history", "science", "whatif", "shorts"])[:7],
            "categoryId": "27",
            "defaultLanguage": "en-US",
            "defaultAudioLanguage": "en-US"
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
            "selfDeclaredMadeForKids": False,    # Ticks "No, it's not made for kids"
            "containsSyntheticMedia": False,     # Sets Altered/Synthetic Content to NO as requested
            "embeddable": True,
            "publicStatsViewable": True
        }
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    res = youtube_client.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    video_id = res["id"]

    try:
        youtube_client.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg")
        ).execute()
    except Exception as e:
        print(f"Thumbnail note: {e}")

    return video_id, publish_at

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
    storyboard = generate_storyboard(signals, memory["used_topics"], analytics_report)
    final_mp4, thumb_jpg = render_story_video(storyboard)
    auto_qa_verify_video(final_mp4, thumb_jpg, storyboard)
    video_id, scheduled_time = publish_with_thumbnail(yt, final_mp4, thumb_jpg, storyboard)

    memory["used_topics"].append(storyboard["topic_id"])
    memory.setdefault("published_log", {})[video_id] = {
        "title": storyboard["title"],
        "hook": storyboard["scenes"][0]["narration"],
        "scheduled_for": scheduled_time
    }
    save_memory(memory)
    print(f"Success! Video {video_id} scheduled for {scheduled_time}")

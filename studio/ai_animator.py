"""Real 2D Cartoon Animation Engine ($0): FLUX.1-schnell Keyframes -> Wan 2.2 / LTX Image-to-Video -> Meme SFX + Top Banner."""
import os, json, time, random, subprocess, urllib.parse
import requests
from PIL import Image, ImageDraw, ImageFont
from gradio_client import Client, handle_file

STYLE_PREFIX = (
    "2D hand-drawn FlipaClip cartoon meme animation frame, minimalist matte sage-grey paper background (#b2b6a4), "
    "expressive grey-shaded stickman character with giant wide cartoon eyes and thick messy black ink outlines, "
    "Rico Animations and Avenu Animations aesthetic, clean 2D flat cel shading, NO text, NO watermark, "
)

def generate_3shot_meme_script():
    """Uses free GitHub Models GPT-4o to write a 14-second, 3-shot visual relatable comedy gag (zero essay narration)."""
    token = os.environ["GITHUB_TOKEN"]
    prompt = """
    Write ONE ultra-relatable, hilarious 14-second silent 2D cartoon meme Short (Rico Animations / Avenu Animations style).
    NO narrator essay! The entire joke is told through ONE top banner caption + 3 escalating visual shots + meme SFX.
    Available SFX filenames: ["boom.mp3", "horror_sting.mp3", "scream_cutoff.mp3", "sad_violin.mp3", "cartoon_slip.mp3", "crickets.mp3"].
    Return ONLY raw JSON:
    {
      "topic_id": "unique-slug",
      "title": "That one moment at 3AM 😭 #Shorts",
      "top_banner": "When you hear a noise at 3AM 💀",
      "description": "Can you relate? 😂 #animation #meme #shorts #relatable",
      "tags": ["animation", "meme", "funny", "relatable", "stickman", "shorts"],
      "shots": [
        {
          "image_prompt": "Shot 1 (Setup): Detailed 2D cartoon scene of the stickman doing an everyday relatable thing",
          "motion_prompt": "Subtle 2D cartoon animation, character blinks, looks around nervously, hand-drawn line boil",
          "sfx": "crickets.mp3"
        },
        {
          "image_prompt": "Shot 2 (Escalation): Creepy or absurd reveal right next to the stickman",
          "motion_prompt": "Dramatic 2D zoom-in, scary figure slowly peeks out from the shadow, cartoon eyes widen in terror",
          "sfx": "horror_sting.mp3"
        },
        {
          "image_prompt": "Shot 3 (Punchline): Extreme close-up of stickman's giant bloodshot eyes or crying flood reaction",
          "motion_prompt": "Rapid comedic cartoon shaking, tears flying, chaotic hilarious panic expression",
          "sfx": "scream_cutoff.mp3"
        }
      ]
    }
    """
    r = requests.post(
        "https://models.github.ai/inference/chat/completions",
        headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"},
        json={"model": "openai/gpt-4o", "messages": [{"role": "user", "content": prompt}], "temperature": 0.95},
        timeout=45,
    )
    raw = r.json()["choices"][0]["message"]["content"]
    return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])

def make_keyframe(prompt_text, out_png, seed):
    hf_token = os.environ.get("HF_TOKEN")
    try:
        client = Client("black-forest-labs/FLUX.1-schnell", hf_token=hf_token)
        res = client.predict(prompt=STYLE_PREFIX + prompt_text, seed=seed, randomize_seed=False, width=768, height=1344, num_inference_steps=4, api_name="/infer")
        src = res[0]["path"] if isinstance(res[0], dict) else res[0]
        Image.open(src).convert("RGB").resize((1080, 1920), Image.Resampling.LANCZOS).save(out_png)
        return out_png
    except Exception as e:
        print(f"FLUX HF fallback to Pollinations ({e})")
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(STYLE_PREFIX + prompt_text)}?width=768&height=1344&model=flux&seed={seed}&nologo=true"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        with open(out_png, "wb") as f:
            f.write(r.content)
        Image.open(out_png).convert("RGB").resize((1080, 1920), Image.Resampling.LANCZOS).save(out_png)
        return out_png

def animate_keyframe_i2v(img_path, motion_prompt, out_mp4):
    """Animates the 2D cartoon keyframe into a real 4-5s moving video via free Hugging Face Wan 2.2 / LTX ZeroGPU Space."""
    hf_token = os.environ.get("HF_TOKEN")
    for space_id in ("Wan-AI/Wan2.2-TI2V-5B", "Lightricks/LTX-Video"):
        try:
            client = Client(space_id, hf_token=hf_token)
            res = client.predict(handle_file(img_path), motion_prompt, api_name="/predict")
            vid = res[0]["video"] if isinstance(res, (list, tuple)) and isinstance(res[0], dict) else (res[0] if isinstance(res, (list, tuple)) else res)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", vid, "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24", "-c:v", "libx264", "-pix_fmt", "yuv420p", out_mp4], check=True)
            return out_mp4
        except Exception as e:
            print(f"I2V Space {space_id} busy ({str(e)[:80]}), trying next...")

    # High-energy 24fps punch-zoom + cartoon camera-shake fallback if ZeroGPU queue is full
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", img_path,
        "-vf", "zoompan=z='min(zoom+0.005,1.28)':x='iw/2-(iw/zoom/2)+8*sin(on)':y='ih/2-(ih/zoom/2)':d=108:s=1080x1920:fps=24",
        "-c:v", "libx264", "-t", "4.5", "-pix_fmt", "yuv420p", out_mp4
    ], check=True)
    return out_mp4

def build_rico_style_short(out_mp4="final_video.mp4"):
    os.makedirs("build/meme", exist_ok=True)
    gag = generate_3shot_meme_script()
    seed = random.randint(1000, 99999)
    clips = []

    for i, shot in enumerate(gag["shots"]):
        img_p = make_keyframe(shot["image_prompt"], f"build/meme/shot_{i}.png", seed + i)
        raw_v = animate_keyframe_i2v(img_p, shot["motion_prompt"], f"build/meme/raw_{i}.mp4")
        sfx_p = os.path.join("assets", "sfx", shot.get("sfx", "boom.mp3"))
        out_v = f"build/meme/seg_{i}.mp4"
        if os.path.exists(sfx_p):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw_v, "-i", sfx_p, "-c:v", "copy", "-c:a", "aac", "-shortest", out_v], check=True)
        else:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw_v, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-c:v", "copy", "-c:a", "aac", "-shortest", out_v], check=True)
        clips.append(f"file 'seg_{i}.mp4'")

    with open("build/meme/concat.txt", "w") as f:
        f.write("\n".join(clips))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "build/meme/concat.txt", "-c", "copy", "build/meme/joined.mp4"], check=True)

    # Burn persistent Rico/Backbench top relatable banner cleanly in upper safe zone
    banner_txt = gag["top_banner"].replace("'", "").replace(":", "")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", "build/meme/joined.mp4",
        "-vf", f"drawbox=x=60:y=160:w=960:h=130:color=#ffd23f@0.95:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{banner_txt}':fontcolor=black:fontsize=46:x=(w-text_w)/2:y=205",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", out_mp4
    ], check=True)
    return out_mp4, gag
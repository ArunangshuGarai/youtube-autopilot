"""Story engine: genre-specific scripting (comedy / crime / thriller) -> validated scene storyboard."""
import json
import os
import random
import re
import time

import requests

from .stickman import POSES, FACES, ROLES
from .scenes import SETTINGS, SET_PIECES

GENRES = ("crime", "thriller", "comedy")
PROPS = ["phone", "briefcase", "moneybag", "cash", "magnifier", "flashlight", "key", "handcuffs", "coffee", "laptop", "envelope",
         "trophy", "balloon", "banana", "pizza", "camera", "sign", "bomb"]
CAMERAS = ["push_in", "pull_out", "pan_left", "pan_right", "shake", "dutch", "whip", "snap_zoom", "drift_up", "static"]
SFX = ["none", "whoosh", "hit", "boom", "slam", "ding", "heartbeat", "sting", "record_scratch", "fail", "cash", "knock", "boing", "siren", "click", "tick"]
FXS = ["exclaim", "question", "sweat", "anger", "zzz", "sparkle"]
MOODS = ["tense", "dark", "sneaky", "sad", "quirky", "upbeat", "epic"]
VOICES = ["grave", "tense", "jolly", "sarcastic"]
DELIVERIES = ["normal", "slow", "fast", "whisper", "excited", "deadpan"]
LIGHTING = ["day", "dusk", "night", "dark"]
TRANSITIONS = ["cut", "flash", "black"]

GENRE_BRIEF = {
    "crime": """TRUE CRIME (stick-figure documentary). Tell ONE real, documented historical heist, prison escape, con, or detective twist.
- Tone: intense, clear, chronological. Voice profile: "grave". Music: "dark" or "tense". Lighting: "night" or "dark".
- State WHO, WHERE, and WHAT they wanted in Scene 1-2. Escalate the plan in Scenes 3-7. Land the real outcome/twist in Scenes 8-10.
- Every scene MUST visually show the objects available in SET_PIECES and PROPS (safe, vault, bars, door, car, moneybag, cash, key, flashlight, handcuffs, magnifier).""",

    "thriller": """THRILLER (grounded, crystal-clear suspense story). ONE relatable person alone at night notices a specific physical clue in their house, office, or street that leads to a chilling realization.
- Tone: suspenseful, clear, step-by-step. Voice profile: "tense". Music: "tense" or "sneaky". Lighting: "night" or "dark".
- NEVER write confusing abstract metaphors. Every sentence must describe a concrete physical action using ONLY things drawn on screen: phone, laptop, camera, flashlight, key, door, bed, couch, tv, car, window.
- Follow a clear chain: Strange Event -> Checking Clue 1 -> Checking Clue 2 -> The Chilling Reveal.""",

    "comedy": """COMEDY (Hilarious 'World's Dumbest Criminal' or 'Epic Real-Life Human Fail' storytime). Tell ONE absurdly funny, easy-to-follow story about a person or bungling thief whose "genius" plan backfires spectacularly.
- Tone: sarcastic, punchy, deadpan storytelling (like Sam O'Nella Academy or Casually Explained). Voice profile: "sarcastic" or "jolly". Music: "sneaky" or "quirky". Lighting: "day".
- STRICT RULE: NEVER write surreal/sci-fi nonsense (NO talking appliances, NO talking animals, NO magic). The humor must come from a human character making a hilariously dumb decision.
- Every scene's action MUST use ONLY the visible rooms, furniture (door, safe, table, desk, car, bed, couch, bars, tv, fridge, wardrobe, chair), and hand props (phone, briefcase, moneybag, cash, pizza, coffee, laptop, sign, handcuffs, camera) so the viewer sees the exact joke happening on screen.""",
}

SCHEMA_DOC = f"""
Return ONLY valid JSON (no markdown) with this exact shape:
{{
  "genre": "crime|thriller|comedy",
  "topic_id": "unique-kebab-slug",
  "title": "<=55 chars, clear curiosity hook, no hashtags",
  "thumb_text": "2-3 ALL CAPS words",
  "description": "2-3 clear sentences summarizing the story.",
  "tags": ["6 to 8 short tags"],
  "is_fiction": true,
  "facts_used": ["for true stories: the 4-8 concrete facts you rely on"],
  "voice_profile": "{'|'.join(VOICES)}",
  "music_mood": "{'|'.join(MOODS)}",
  "scenes": [ {{
      "narration": "8-14 simple, crystal-clear spoken words. One concrete action per scene.",
      "delivery": "normal",
      "setting": "{'|'.join(SETTINGS)}",
      "lighting": "{'|'.join(LIGHTING)}",
      "camera": "{'|'.join(CAMERAS)}",
      "cast": [ {{ "role": "{'|'.join(ROLES)}", "pose": "one of POSES", "face": "one of FACES", "x": 0.15-0.85, "facing": "left|right", "prop": "optional", "fx": "optional" }} ],
      "set_piece": {{ "name": "optional, one of SET_PIECES", "x": 0.15-0.85 }},
      "overlay": "optional short context stamp like 'BOSTON 1950' or 'STEP 1: THE DUMB PLAN'",
      "sfx": "one of SFX", "sfx_at": 0.05,
      "transition": "{'|'.join(TRANSITIONS)}",
      "emphasis": ["1-2 key narration words to highlight in captions"]
  }} ]
}}
POSES: {', '.join(POSES)}
FACES: {', '.join(FACES)}
PROPS: {', '.join(PROPS)}
FX: {', '.join(FXS)}
SET_PIECES: {', '.join(SET_PIECES)}
SFX: {', '.join(SFX)}
"""

CRAFT_RULES = """
CRAFT RULES (follow all):
- 9 to 10 scenes. Total narration 90-115 words (about 38-42 seconds).
- CLARITY FIRST: A 12-year-old watching on mute or listening with eyes closed must immediately understand WHO the character is, WHAT problem they face, and WHAT happens next. No cryptic riddles or disconnected sentences.
- VISUAL LOCK: Never mention an object in narration unless it is in PROPS or SET_PIECES and placed in that scene's `prop` or `set_piece` field! If the character talks about a phone, give them `prop: "phone"`. If they hide in a wardrobe or open a safe, set `set_piece: {"name": "wardrobe"}` or `{"name": "safe"}`.
- Scene 1 MUST set up the exact premise in plain English (e.g., "In 1995, a man walked into two Pittsburgh banks wearing lemon juice on his face.") and display a 2-to-3-word `overlay` banner stating the topic.
- Keep `delivery` set to "normal" for smooth, natural narration pacing.
- Do NOT repeat any topic from the USED list.
"""

# --------------------------------------------------------------------------- LLM plumbing
def _gemini_models():
    env = os.environ.get("GEMINI_TEXT_MODELS", "").strip()
    return [m.strip() for m in env.split(",") if m.strip()] or ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemma-3-27b-it", "gemini-3.8-flash"]

def _extract_json(raw):
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    a, b = cleaned.find("{"), cleaned.rfind("}")
    if a != -1 and b != -1:
        cleaned = cleaned[a:b + 1]
    return json.loads(cleaned)

def _gemini_text(prompt, grounded=False):
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    from google import genai
    client = genai.Client(api_key=api_key)
    config = None
    if grounded:
        try:
            from google.genai import types
            config = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
        except Exception:
            config = None
    waits = [2, 8, 15, 25]
    for wait, model in zip(waits, _gemini_models()):
        try:
            res = client.models.generate_content(model=model, contents=prompt, config=config) if config else client.models.generate_content(model=model, contents=prompt)
            if res.text:
                return res.text
        except Exception as e:
            print(f"Gemini {model} unavailable ({str(e)[:90]}), retrying in {wait}s...")
            time.sleep(wait)
    return None

def _pollinations_text(prompt):
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    for model in ("openai", "mistral"):
        try:
            r = requests.post("https://text.pollinations.ai/", headers=headers, json={"messages": [{"role": "user", "content": prompt}], "model": model, "jsonMode": True}, timeout=75)
            if r.status_code == 200 and r.text.strip():
                return r.text
        except Exception as e:
            print(f"Pollinations text {model} failed: {str(e)[:80]}")
    return None

def research_facts(genre, used):
    """Optional grounded lookup so true-crime stories rest on verifiable facts. Returns text or ''."""
    if genre != "crime":
        return ""
    q = ("Using web search, pick ONE well-documented, lesser-known historical true-crime story (heist, escape, con, forgery or "
         "investigation twist) that is NOT in this list: " + json.dumps(used[-40:]) +
         ". Return 8 verifiable facts (names only of historical figures, exact dates, numbers, places, outcome) as bullet points, "
         "and name the sources. Avoid cases involving living private individuals or graphic violence.")
    txt = _gemini_text(q, grounded=True)
    return txt or ""

# --------------------------------------------------------------------------- validation / normalisation
def _pick(v, allowed, default):
    return v if v in allowed else default

def normalize(sb, genre):
    if not isinstance(sb, dict) or len(sb.get("scenes", [])) < 8:
        raise ValueError("storyboard too short")
    sb["genre"] = genre
    sb["voice_profile"] = _pick(sb.get("voice_profile"), VOICES, {"crime": "grave", "thriller": "tense", "comedy": "jolly"}[genre])
    sb["music_mood"] = _pick(sb.get("music_mood"), MOODS, {"crime": "dark", "thriller": "tense", "comedy": "quirky"}[genre])
    sb["is_fiction"] = bool(sb.get("is_fiction", genre != "crime"))
    sb["title"] = re.sub(r"#\w+", "", str(sb.get("title", "Untitled"))).strip()[:55]
    sb["thumb_text"] = str(sb.get("thumb_text", "WATCH THIS")).upper()[:20]
    sb["topic_id"] = re.sub(r"[^a-z0-9-]", "", str(sb.get("topic_id", sb["title"])).lower().replace(" ", "-"))[:60] or "story"
    sb["tags"] = [str(t)[:30] for t in sb.get("tags", ["shorts", "storytime"])][:8]
    scenes = []
    for sc in sb["scenes"][:12]:
        narr = re.sub(r"\s+", " ", str(sc.get("narration", ""))).strip()
        if not narr:
            continue
        cast = []
        for c in (sc.get("cast") or [])[:2]:
            cast.append(dict(
                role=_pick(c.get("role"), ROLES, "hero"), pose=_pick(c.get("pose"), POSES, "idle"), face=_pick(c.get("face"), FACES, "neutral"),
                x=min(max(float(c.get("x", 0.5) or 0.5), 0.15), 0.85), facing=_pick(c.get("facing"), ("left", "right"), "right"),
                prop=_pick(c.get("prop"), PROPS, None), fx=_pick(c.get("fx"), FXS, None)))
        if not cast:
            cast = [dict(role="hero", pose="talk", face="neutral", x=0.5, facing="right", prop=None, fx=None)]
        sp = sc.get("set_piece") or {}
        sp = dict(name=sp["name"], x=min(max(float(sp.get("x", 0.7)), 0.12), 0.88)) if sp.get("name") in SET_PIECES else None
        scenes.append(dict(
            narration=narr, delivery=_pick(sc.get("delivery"), DELIVERIES, "normal"),
            setting=_pick(sc.get("setting"), SETTINGS, "room"), lighting=_pick(sc.get("lighting"), LIGHTING, "night" if genre != "comedy" else "day"),
            camera=_pick(sc.get("camera"), CAMERAS, "push_in"), cast=cast, set_piece=sp,
            overlay=(str(sc["overlay"])[:28] if sc.get("overlay") else None),
            sfx=_pick(sc.get("sfx"), SFX, "none"), sfx_at=float(sc.get("sfx_at", 0.05) or 0.05),
            transition=_pick(sc.get("transition"), TRANSITIONS, "cut"),
            emphasis=[re.sub(r"[^a-z0-9']", "", str(w).lower()) for w in (sc.get("emphasis") or [])][:3]))
    if len(scenes) < 8:
        raise ValueError("too few valid scenes")
    # avoid identical consecutive cameras
    for i in range(1, len(scenes)):
        if scenes[i]["camera"] == scenes[i - 1]["camera"]:
            scenes[i]["camera"] = "pull_out" if scenes[i]["camera"] != "pull_out" else "push_in"
    scenes[0]["transition"] = "cut"
    sb["scenes"] = scenes
    words = sum(len(s["narration"].split()) for s in scenes)
    if words > 150:
        raise ValueError(f"narration too long ({words} words)")
    return sb

def pick_genre(memory):
    forced = os.environ.get("FORCE_GENRE", "").strip().lower()
    if forced in GENRES:
        return forced
    log = memory.get("genre_log", [])[-6:]
    counts = {g: log.count(g) for g in GENRES}
    low = min(counts.values())
    return random.choice([g for g in GENRES if counts[g] == low])

def generate_story(memory, analytics_hint="", signals=None):
    genre = pick_genre(memory)
    used = memory.get("used_topics", [])
    facts = research_facts(genre, used)
    facts_block = ("VERIFIED FACTS TO BUILD ON (use only these, do not add other factual claims):\n" + facts) if facts else ""
    prompt = f"""You are the head writer of a viral faceless YouTube Shorts channel that uses animated stick figures.
{GENRE_BRIEF[genre]}
{CRAFT_RULES}
USED topics (never repeat): {json.dumps(used[-40:])}
What recently performed well on this channel: {analytics_hint or 'n/a'}
Inspiration (optional, ignore if not a good fit): {json.dumps((signals or [])[:8])}
{facts_block}
{SCHEMA_DOC}"""
    for attempt in range(3):
        raw = _gemini_text(prompt) or _pollinations_text(prompt)
        if not raw:
            break
        try:
            return normalize(_extract_json(raw), genre)
        except Exception as e:
            print(f"Story draft {attempt + 1} rejected: {str(e)[:100]}")
            prompt += f"\n\nYour previous answer was rejected ({str(e)[:100]}). Return corrected JSON only."
    print("LLM unavailable or invalid - using a curated backup story.")
    return backup_story(genre, used)

# --------------------------------------------------------------------------- curated backups (also used as test fixtures)
def _c(role, pose, face, x=0.5, facing="right", prop=None, fx=None):
    return dict(role=role, pose=pose, face=face, x=x, facing=facing, prop=prop, fx=fx)

BACKUPS = {
"crime": dict(
    genre="crime", topic_id="brinks-robbery-1950", title="The Heist With No Gunshots", thumb_text="PERFECT CRIME?",
    description="In 1950, eleven men pulled off the biggest robbery in American history up to that point. Six years later, one grudge brought it all down.",
    tags=["truecrime", "heist", "history", "mystery", "explained", "boston"], is_fiction=False, voice_profile="grave", music_mood="dark",
    facts_used=["Brink's robbery, Boston, January 17 1950", "11 men, Halloween masks, rubber-soled shoes", "about 2.7 million dollars taken", "statute of limitations six years", "Joseph 'Specs' O'Keefe talked days before it expired", "eight men convicted"],
    scenes=[
     dict(narration="Eleven men. Rubber masks. Not a single shot fired.", delivery="slow", setting="night_street", lighting="night", camera="snap_zoom", sfx="sting",
          cast=[_c("criminal", "sneak", "sly", .4, "right", "flashlight")], overlay="BOSTON 1950", emphasis=["masks"]),
     dict(narration="January seventeenth, nineteen fifty. They slipped into a Brink's building in Boston wearing Halloween masks.", setting="alley", lighting="night", camera="pan_right",
          cast=[_c("criminal", "sneak", "sly", .3), _c("criminal", "sneak", "sly", .62, "left")], sfx="whoosh", emphasis=["masks"]),
     dict(narration="They had spent eighteen months planning it, even sneaking in at night to copy the keys.", setting="vault", lighting="dark", camera="push_in",
          cast=[_c("criminal", "hold", "suspicious", .35, "right", "key")], set_piece=dict(name="door", x=.75), sfx="click", emphasis=["eighteen"]),
     dict(narration="Rubber-soled shoes kept every footstep silent while they tied up five guards.", setting="vault", lighting="dark", camera="dutch",
          cast=[_c("criminal", "point", "angry", .3), _c("civilian", "hands_up", "scared", .68, "left")], fx=None, sfx="none", emphasis=["silent"]),
     dict(narration="In about twenty minutes, they hauled out nearly three million dollars.", delivery="fast", setting="vault", lighting="dark", camera="shake",
          cast=[_c("criminal", "run", "happy", .4, "right", "moneybag")], set_piece=dict(name="safe", x=.8), sfx="cash", emphasis=["three", "million"]),
     dict(narration="The newspapers called it the crime of the century. The police had no suspects.", setting="office", lighting="day", camera="pull_out",
          cast=[_c("detective", "thinking", "confused", .45, "right", "magnifier")], set_piece=dict(name="desk", x=.7), overlay="NO SUSPECTS", emphasis=["century"]),
     dict(narration="The gang swore to stay silent for six years, because that's when the law ran out.", delivery="slow", setting="night_street", lighting="night", camera="push_in",
          cast=[_c("criminal", "idle", "smirk", .35), _c("criminal", "idle", "sly", .65, "left")], overlay="SIX YEARS LATER", sfx="tick", emphasis=["six"]),
     dict(narration="Then one thief, Specs O'Keefe, got arrested, and felt his friends had cheated him.", setting="cell", lighting="dark", camera="drift_up",
          cast=[_c("criminal", "slump", "angry", .4, "right", None, "anger")], set_piece=dict(name="bars", x=.5), sfx="slam", emphasis=["cheated"]),
     dict(narration="Days before the deadline, he talked. Eight men were convicted.", delivery="deadpan", setting="office", lighting="dark", camera="snap_zoom",
          cast=[_c("detective", "point", "angry", .35), _c("criminal", "cower", "scared", .7, "left", None, "sweat")], sfx="hit", emphasis=["talked"]),
     dict(narration="Most of the money was never found. One grudge outlasted six years of silence.", delivery="slow", setting="night_street", lighting="night", camera="pull_out",
          cast=[_c("hero", "slump", "sad", .5)], sfx="heartbeat", emphasis=["grudge"]),
    ]),
"thriller": dict(
    genre="thriller", topic_id="text-from-my-own-number", title="The Text From My Own Number", thumb_text="DON'T OPEN IT",
    description="At three in the morning, a message arrives from a number you know too well. This is a fictional story.",
    tags=["horror", "scary", "creepy", "storytime", "thriller", "shorts"], is_fiction=True, voice_profile="tense", music_mood="tense", facts_used=[],
    scenes=[
     dict(narration="At three a.m., my phone buzzed. The text came from my own number.", delivery="slow", setting="room", lighting="dark", camera="snap_zoom", sfx="sting",
          cast=[_c("hero", "sit", "scared", .5, "right", "phone")], overlay="3:07 AM", emphasis=["own"]),
     dict(narration="It said: don't open the front door.", delivery="whisper", setting="room", lighting="dark", camera="push_in",
          cast=[_c("hero", "cower", "scared", .5, "right", "phone", "sweat")], emphasis=["door"]),
     dict(narration="I laughed it off. Then the doorbell rang.", setting="room", lighting="dark", camera="shake",
          cast=[_c("hero", "shocked", "shocked", .35, "right", None, "exclaim")], set_piece=dict(name="door", x=.75), sfx="knock", emphasis=["doorbell"]),
     dict(narration="Through the peephole, nobody. Then another text: he's behind you.", setting="room", lighting="dark", camera="dutch",
          cast=[_c("hero", "lean", "scared", .35, "right")], set_piece=dict(name="door", x=.75), emphasis=["behind"]),
     dict(narration="I turned slowly. The hallway was empty. My own coat hung in the dark.", delivery="slow", setting="room", lighting="dark", camera="pan_left",
          cast=[_c("hero", "sneak", "suspicious", .6, "left")], sfx="heartbeat", emphasis=["empty"]),
     dict(narration="Third text: check the security camera.", setting="office", lighting="dark", camera="push_in",
          cast=[_c("hero", "hold", "scared", .4, "right", "laptop")], emphasis=["camera"]),
     dict(narration="On screen, my living room. And a tall shape, standing in the corner.", delivery="whisper", setting="room", lighting="dark", camera="snap_zoom",
          cast=[_c("hero", "hold", "screaming", .35, "right", "laptop", "exclaim")], sfx="sting", emphasis=["tall"]),
     dict(narration="The last text said: run. So I ran, barefoot, into the rain.", delivery="fast", setting="night_street", lighting="night", camera="whip",
          cast=[_c("hero", "run", "screaming", .5)], sfx="whoosh", emphasis=["run"]),
     dict(narration="At dawn, police searched the house. Nobody was inside.", setting="room", lighting="dusk", camera="pull_out",
          cast=[_c("cop", "idle", "confused", .35, "right"), _c("hero", "slump", "sad", .68, "left")], overlay="6:30 AM", emphasis=["nobody"]),
     dict(narration="But they found my phone on the nightstand. Switched off since midnight.", delivery="slow", setting="room", lighting="dark", camera="drift_up",
          cast=[_c("hero", "hands_up", "shocked", .4, "right")], set_piece=dict(name="bed", x=.72), sfx="boom", emphasis=["midnight"]),
    ]),
"comedy": dict(
    genre="comedy", topic_id="flat-pack-wardrobe-disaster", title="I Built A Wardrobe Without Instructions", thumb_text="BIG MISTAKE",
    description="Four hours, one wardrobe, zero instructions. What could possibly go wrong? This is a fictional story.",
    tags=["comedy", "funny", "storytime", "relatable", "fail", "shorts"], is_fiction=True, voice_profile="jolly", music_mood="quirky", facts_used=[],
    scenes=[
     dict(narration="I built a wardrobe by myself. Four hours. Zero instructions.", delivery="fast", setting="room", lighting="day", camera="snap_zoom", sfx="ding",
          cast=[_c("hero", "victory", "happy", .5)], emphasis=["zero"]),
     dict(narration="The box said easy assembly. The box lied.", delivery="deadpan", setting="room", lighting="day", camera="push_in",
          cast=[_c("hero", "facepalm", "sad", .4, "right", "sign")], sfx="record_scratch", emphasis=["lied"]),
     dict(narration="Hour two, I had one screw left over. Hour three, I had forty.", setting="room", lighting="day", camera="pan_right",
          cast=[_c("hero", "panic", "scared", .5, "right", None, "sweat")], overlay="HOUR THREE", emphasis=["forty"]),
     dict(narration="I called my friend. He asked how many pieces. I said: yes.", setting="room", lighting="day", camera="dutch",
          cast=[_c("hero", "talk", "confused", .35, "right", "phone"), _c("friend", "laugh", "laugh", .7, "left")], emphasis=["yes"]),
     dict(narration="Finally, it stood. Perfect. Beautiful. Then I noticed the doors faced inward.", delivery="slow", setting="room", lighting="day", camera="pull_out",
          cast=[_c("hero", "shocked", "shocked", .35, "right", None, "exclaim")], set_piece=dict(name="wardrobe", x=.75), emphasis=["inward"]),
     dict(narration="So I did what any genius would. I climbed inside to fix it from there.", delivery="fast", setting="room", lighting="day", camera="whip",
          cast=[_c("hero", "sneak", "sly", .45, "right")], set_piece=dict(name="wardrobe", x=.72), sfx="whoosh", emphasis=["genius"]),
     dict(narration="That's when the wardrobe I built decided to fall forward.", setting="room", lighting="day", camera="shake",
          cast=[_c("hero", "fall", "screaming", .5)], set_piece=dict(name="wardrobe", x=.72), sfx="boom", emphasis=["forward"]),
     dict(narration="The neighbors heard a scream and a crash. Then, silence.", delivery="deadpan", setting="street", lighting="day", camera="pan_left",
          cast=[_c("civilian", "idle", "confused", .4, "right", None, "question")], overlay="NEXT DOOR", emphasis=["silence"]),
     dict(narration="Now I live inside it, rent free. Neighbors think it's modern art.", delivery="excited", setting="room", lighting="day", camera="snap_zoom",
          cast=[_c("hero", "dance", "happy", .5)], set_piece=dict(name="wardrobe", x=.75), sfx="boing", emphasis=["art"]),
    ]),
}

def backup_story(genre, used):
    import copy
    sb = copy.deepcopy(BACKUPS.get(genre) or BACKUPS["comedy"])
    return normalize(sb, sb["genre"])

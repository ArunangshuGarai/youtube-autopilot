"""Story engine: hook-first scripting + the full packaging (title, thumbnail brief, SEO) from ONE LLM call.

Free-tier hygiene: one call per video (two at the very most), a daily call budget kept in memory.json, a model that
returns 429 is skipped for the rest of the run (no sleeping), and every quality gate (hook score, title lint, SEO
query test) is computed locally instead of asking another model.
"""
import datetime
import json
import os
import random
import re
import time

import requests

from . import packaging as P
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
BEATS = ["hook", "stakes", "build", "turn", "escalate", "twist", "loop"]
SHOCK_FACES = ["shocked", "screaming", "scared", "laugh", "angry", "smirk"]

GENRE_BRIEF = {
    "crime": """TRUE CRIME (stick-figure documentary). ONE real, documented heist, prison escape, con, forgery or detective twist.
- Narrator: cold, certain, documentary. voice_profile "grave". Music "dark" or "tense". Lighting "night" or "dark".
- The hook is the single most shocking VERIFIED fact, stated flat, mid-action (a number, a date, an impossible detail). The 'how' is the entertainment: show the clever method step by step.
- The twist is the real, surprising outcome (the mistake that caught them, the grudge, the money never found).
- No graphic violence, no living private individuals, no invented quotes.""",

    "thriller": """THRILLER (first-person, one ordinary night, one WRONG detail). Fiction. A relatable person alone notices something small that does not fit, and every scene adds exactly one new clue.
- Narrator: low, close, controlled. voice_profile "tense". Music "tense" or "sneaky". Lighting "night" or "dark".
- The hook drops us INTO the wrong detail ("The text came from my own number."). Rule of escalation: each scene is a new piece of evidence, never a feeling or a metaphor.
- The last line must recast the first line (a twist the viewer replays to re-check).
- Only use things that can be drawn: phone, laptop, camera, flashlight, key, envelope, door, window, bed, couch, tv, car, stairs, lamp.""",

    "comedy": """COMEDY ('world's dumbest criminal' / epic real-life fail / relatable disaster). ONE absurdly funny, easy-to-follow story about a human whose 'genius' plan backfires spectacularly.
- Narrator: sarcastic, deadpan, quick, like a friend telling the story at a party. voice_profile "sarcastic" or "jolly". Music "sneaky" or "quirky". Lighting "day".
- The hook states the dumbest part up front, proudly. Then rule of three: every attempt to fix it makes it worse. The last line is a deadpan callback button.
- No surreal/sci-fi nonsense (no talking appliances or animals, no magic): the joke is a person making a confidently dumb decision.
- Only use things that can be drawn: door, safe, table, desk, car, bed, couch, bars, tv, fridge, wardrobe, chair, phone, briefcase, moneybag, cash, pizza, coffee, laptop, sign, handcuffs, camera.""",
}

SCHEMA_DOC = f"""
Return ONLY valid JSON (no markdown, no commentary after it) with this exact shape:
{{
  "genre": "crime|thriller|comedy",
  "topic_id": "unique-kebab-slug",
  "hook_options": [ {{"formula": "one of: statistic, impossible, warning, mistake, cold-open, contrarian-flip, question, superlative, clock, receipt", "text": "5 different spoken openers, 6-16 words each, ALL describing the SAME opening moment so any of them can start the story"}} ],
  "hook_card": "2-4 ALL CAPS words shown on screen in the first 2 seconds; DIFFERENT words from the spoken hook",
  "title_options": ["5 titles, <=55 chars each, subject in the first 40 chars, a number/year/name, no hashtags"],
  "thumb": {{
    "text": "2-3 ALL CAPS words that add a SECOND angle (the cost, the dare or the question) and share NO word with the title",
    "setting": "{'|'.join(SETTINGS)}", "lighting": "{'|'.join(LIGHTING)}",
    "role": "{'|'.join(ROLES)}", "pose": "one of POSES", "face": "one of: {', '.join(SHOCK_FACES)}", "prop": "optional prop", "set_piece": "optional SET_PIECES name",
    "bg_prompt": "one sentence describing a dramatic 3D-cartoon background for the thumbnail (no text, no people)"
  }},
  "seo": {{
    "queries": ["the 3 searches a real viewer would type to find this story"],
    "description_hook": "1-2 sentences that say what the viewer gets, using the words in those queries",
    "tags": ["6 to 10 tags, <=30 chars, spellings and alternate names only"],
    "hashtags": ["#two", "#or", "#three"]
  }},
  "description": "2-3 sentences summarizing the story without spoiling the twist.",
  "cta_question": "one line that makes viewers pick a side in the comments (not 'what do you think')",
  "is_fiction": true,
  "facts_used": ["for true stories: the 4-8 concrete facts you rely on"],
  "voice_profile": "{'|'.join(VOICES)}",
  "music_mood": "{'|'.join(MOODS)}",
  "scenes": [ {{
      "beat": "{'|'.join(BEATS)}",
      "narration": "spoken line; scene 1 MUST be identical to hook_options[0].text",
      "delivery": "{'|'.join(DELIVERIES)}",
      "setting": "{'|'.join(SETTINGS)}",
      "lighting": "{'|'.join(LIGHTING)}",
      "camera": "{'|'.join(CAMERAS)}",
      "cast": [ {{ "role": "{'|'.join(ROLES)}", "pose": "one of POSES", "face": "one of FACES", "x": 0.15-0.85, "facing": "left|right", "prop": "optional", "fx": "optional" }} ],
      "set_piece": {{ "name": "optional, one of SET_PIECES", "x": 0.15-0.85 }},
      "overlay": "optional 2-4 word context stamp like 'BOSTON 1950' or 'HOUR THREE'",
      "sfx": "one of SFX", "sfx_at": 0.05,
      "transition": "{'|'.join(TRANSITIONS)}",
      "emphasis": ["the 1-2 words the narrator stresses"]
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
STRUCTURE - exactly 10 scenes, one spoken line each (about 3-4.5 seconds per line):
 1 HOOK      cold open in the middle of the most shocking moment. No greeting, no context, no 'imagine'. Fragments are good ('Eleven men. Rubber masks.').
 2 STAKES    who, where, what is at risk, in plain words - and open ONE question the viewer needs answered. Never answer it before scene 9.
 3-4 BUILD   every scene adds a NEW fact or action. No scene may restate the one before it.
 5 TURN      a 'But', 'Then' or 'Except' that changes the situation (this re-hooks anyone about to swipe at ~40%).
 6-8 ESCALATE the stakes rise every scene, lines get shorter, each contains a number, time, name or object.
 9 TWIST     answer the open question with the surprise.
 10 LOOP     a last line that echoes or flips the hook so replaying feels natural. No 'thanks for watching', no 'subscribe'.

WRITING RULES
- 100-125 words in total; each line 6-16 words; plain words a 12-year-old gets; concrete nouns and verbs; one idea per line.
- BANNED phrases: imagine, picture this, let me tell you, in this video, did you know, little did, you won't believe, buckle up, welcome, hey guys.
- CLARITY: someone watching on mute must still understand who, what and where from the pictures plus the 2-4 word overlays.
- VISUAL LOCK: only mention objects that exist in PROPS or SET_PIECES, and put them in that scene's `prop` or `set_piece`.
- RETENTION: change pose AND face between consecutive scenes, never repeat a camera twice in a row, put an `fx` or `sfx` on the turn and the twist, use `delivery` "slow"/"whisper" before a reveal and "fast" in the escalation.
- Never repeat a topic from the USED list.

PACKAGING RULES (the title and thumbnail are one unit)
- Title: <=55 chars, subject first, one number/year/name, no vague hype words (insane, crazy, secret, ultimate), at most one ALL-CAPS word.
- Thumbnail text: 2-3 words, a different angle from the title, zero shared words. Thumbnail face must be an extreme expression.
- SEO: write the 3 queries first, then make sure the title or description_hook contains their words. Tags are for disambiguation, not stuffing.
"""

# --------------------------------------------------------------------------- budget + LLM plumbing
_DEAD = set()                  # providers/models that answered 429 during THIS run - never retried, never slept on
_STATE = {"budget": {"date": "", "calls": 0}, "cap": 14}

def _init_budget(memory):
    today = datetime.date.today().isoformat()
    b = memory.setdefault("api_budget", {"date": today, "calls": 0})
    if b.get("date") != today:
        b["date"], b["calls"] = today, 0
    _STATE["budget"] = b
    try:
        _STATE["cap"] = int(os.environ.get("GEMINI_DAILY_BUDGET") or 14)
    except ValueError:
        _STATE["cap"] = 14

def _spend():
    if _STATE["budget"]["calls"] >= _STATE["cap"]:
        print(f"Daily LLM call budget reached ({_STATE['cap']}) - skipping remote call.")
        return False
    _STATE["budget"]["calls"] += 1
    return True

def _is_quota(e):
    s = str(e).lower()
    return "429" in s or "resource_exhausted" in s or "quota" in s or "rate limit" in s or "rate_limit" in s

def _gemini_models():
    env = os.environ.get("GEMINI_TEXT_MODELS", "").strip()
    return [m.strip() for m in env.split(",") if m.strip()] or ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]

def _extract_json(raw):
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    a, b = cleaned.find("{"), cleaned.rfind("}")
    if a != -1 and b != -1:
        cleaned = cleaned[a:b + 1]
    return json.loads(cleaned)

def _gemini_text(prompt, grounded=False, max_models=2):
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
    tried = 0
    for model in _gemini_models():
        key = ("gemini", model, grounded)
        if key in _DEAD:
            continue
        if tried >= max_models or not _spend():
            break
        tried += 1
        try:
            res = client.models.generate_content(model=model, contents=prompt, config=config) if config else client.models.generate_content(model=model, contents=prompt)
            if res.text:
                return res.text
        except Exception as e:
            if _is_quota(e):
                _DEAD.add(key)
                print(f"Gemini {model} out of quota - skipping it for this run.")
            else:
                print(f"Gemini {model} error ({str(e)[:90]}); trying the next model.")
                time.sleep(3)
    return None

def _pollinations_text(prompt):
    if ("pollinations",) in _DEAD:
        return None
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    for model in ("openai", "mistral"):
        try:
            r = requests.post("https://text.pollinations.ai/", headers=headers, json={"messages": [{"role": "user", "content": prompt}], "model": model, "jsonMode": True}, timeout=75)
            if r.status_code == 200 and r.text.strip():
                return r.text
            if r.status_code == 429:
                _DEAD.add(("pollinations",))
                break
        except Exception as e:
            print(f"Pollinations text {model} failed: {str(e)[:80]}")
    return None

def _github_models_text(prompt):
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token or ("github",) in _DEAD:
        return None
    try:
        r = requests.post(
            "https://models.github.ai/inference/chat/completions",
            headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"},
            json={"model": "openai/gpt-4o", "messages": [{"role": "system", "content": "Output ONLY valid raw JSON with no markdown fences."}, {"role": "user", "content": prompt}], "temperature": 0.9},
            timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        if r.status_code == 429:
            _DEAD.add(("github",))
        print(f"GitHub Models status {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"GitHub Models failed: {str(e)[:80]}")
    return None

# --------------------------------------------------------------------------- validation / normalisation
def _pick(v, allowed, default):
    return v if v in allowed else default

def _clean_cast(c, default_x=0.5):
    try:
        x = float(c.get("x", default_x) or default_x)
    except (TypeError, ValueError):
        x = default_x
    return dict(role=_pick(c.get("role"), ROLES, "hero"), pose=_pick(c.get("pose"), POSES, "idle"), face=_pick(c.get("face"), FACES, "neutral"),
                x=min(max(x, 0.15), 0.85), facing=_pick(c.get("facing"), ("left", "right"), "right"),
                prop=_pick(c.get("prop"), PROPS, None), fx=_pick(c.get("fx"), FXS, None))

def _clip_title(t, limit=58):
    t = re.sub(r"#\w+", "", str(t)).strip().strip('"').strip()
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-")

def _texts(options):
    out = []
    for o in options or []:
        t = o.get("text") if isinstance(o, dict) else o
        t = re.sub(r"\s+", " ", str(t or "")).strip()
        if t:
            out.append(t)
    return out

def normalize(sb, genre):
    if not isinstance(sb, dict) or len(sb.get("scenes", [])) < 8:
        raise ValueError("storyboard too short")
    sb["genre"] = genre
    sb["voice_profile"] = _pick(sb.get("voice_profile"), VOICES, {"crime": "grave", "thriller": "tense", "comedy": "sarcastic"}[genre])
    sb["music_mood"] = _pick(sb.get("music_mood"), MOODS, {"crime": "dark", "thriller": "tense", "comedy": "quirky"}[genre])
    sb["is_fiction"] = bool(sb.get("is_fiction", genre != "crime"))
    scenes = []
    for sc in sb["scenes"][:12]:
        narr = re.sub(r"\s+", " ", str(sc.get("narration", ""))).strip()
        if not narr:
            continue
        cast = [_clean_cast(c) for c in (sc.get("cast") or [])[:2] if isinstance(c, dict)] or [dict(role="hero", pose="talk", face="neutral", x=0.5, facing="right", prop=None, fx=None)]
        sp = sc.get("set_piece") or {}
        try:
            sp = dict(name=sp["name"], x=min(max(float(sp.get("x", 0.7)), 0.12), 0.88)) if sp.get("name") in SET_PIECES else None
        except (TypeError, ValueError):
            sp = None
        try:
            sfx_at = float(sc.get("sfx_at", 0.05) or 0.05)
        except (TypeError, ValueError):
            sfx_at = 0.05
        scenes.append(dict(
            beat=_pick(sc.get("beat"), BEATS, None),
            narration=narr, delivery=_pick(sc.get("delivery"), DELIVERIES, "normal"),
            setting=_pick(sc.get("setting"), SETTINGS, "room"), lighting=_pick(sc.get("lighting"), LIGHTING, "night" if genre != "comedy" else "day"),
            camera=_pick(sc.get("camera"), CAMERAS, "push_in"), cast=cast, set_piece=sp,
            overlay=(str(sc["overlay"])[:28].upper() if sc.get("overlay") else None),
            sfx=_pick(sc.get("sfx"), SFX, "none"), sfx_at=sfx_at,
            transition=_pick(sc.get("transition"), TRANSITIONS, "cut"),
            emphasis=[re.sub(r"[^a-z0-9']", "", str(w).lower()) for w in (sc.get("emphasis") or [])][:3]))
    if len(scenes) < 8:
        raise ValueError("too few valid scenes")
    n = len(scenes)
    for i, sc in enumerate(scenes):                                   # fill / repair the retention beats
        default = "hook" if i == 0 else "stakes" if i == 1 else "loop" if i == n - 1 else "twist" if i == n - 2 else "turn" if i == n // 2 else "build" if i < n // 2 else "escalate"
        sc["beat"] = sc["beat"] or default
    scenes[0]["beat"], scenes[-1]["beat"] = "hook", "loop"
    for i in range(1, n):                                             # never the same camera twice in a row
        if scenes[i]["camera"] == scenes[i - 1]["camera"]:
            scenes[i]["camera"] = "pull_out" if scenes[i]["camera"] != "pull_out" else "push_in"
    scenes[0]["transition"] = "cut"
    # the turn and the twist always get a sound or a visual accent
    for sc in scenes:
        if sc["beat"] in ("turn", "twist") and sc["sfx"] == "none":
            sc["sfx"] = "hit" if sc["beat"] == "turn" else "sting"
    sb["scenes"] = scenes

    # ---- hook: best of the options by the LOCAL scorer (yt-script rules) -------------------------------
    cur = scenes[0]["narration"]
    cands = [cur] + [h for h in _texts(sb.get("hook_options")) if h != cur]
    _, best_txt, rep = P.best_hook(cands)
    if best_txt != cur and rep["verdict"] >= P.score_hook(cur)["verdict"] + 6:
        scenes[0]["narration"] = best_txt
    words = sum(len(s["narration"].split()) for s in scenes)
    if words > 150:
        raise ValueError(f"narration too long ({words} words)")
    if words < 60:
        raise ValueError(f"narration too short ({words} words)")

    # ---- packaging ----------------------------------------------------------------------------------------
    th = sb.get("thumb") if isinstance(sb.get("thumb"), dict) else {}
    raw_thumb = th.get("text") or sb.get("thumb_text") or "WAIT FOR IT"
    queries = [str(q) for q in ((sb.get("seo") or {}).get("queries") or [])] if isinstance(sb.get("seo"), dict) else []
    title = P.pick_title(_texts(sb.get("title_options")) + [sb.get("title", "")], raw_thumb, queries) or "Untitled"
    sb["title"] = _clip_title(title)
    sb["thumb_text"] = P.clean_thumb_text(raw_thumb, sb["title"])[:24]
    pivot = scenes[-2] if len(scenes) > 2 else scenes[0]
    base = pivot["cast"][0]
    sp = th.get("set_piece") if th.get("set_piece") in SET_PIECES else (pivot["set_piece"]["name"] if pivot.get("set_piece") else None)
    sb["thumb"] = dict(
        text=sb["thumb_text"],
        setting=_pick(th.get("setting"), SETTINGS, pivot["setting"]), lighting=_pick(th.get("lighting"), LIGHTING, pivot["lighting"]),
        role=_pick(th.get("role"), ROLES, base["role"]), pose=_pick(th.get("pose"), POSES, "shocked" if "shocked" in POSES else base["pose"]),
        face=_pick(th.get("face"), FACES, "shocked" if "shocked" in FACES else base["face"]),
        prop=_pick(th.get("prop"), PROPS, base.get("prop")), set_piece=sp,
        bg_prompt=re.sub(r"\s+", " ", str(th.get("bg_prompt") or "")).strip()[:300])
    hook_card = re.sub(r"[^A-Za-z0-9'$%?!:. ]", "", str(sb.get("hook_card") or "")).upper().split()[:4]
    sb["hook_card"] = " ".join(hook_card) or (scenes[0].get("overlay") or "WATCH CLOSELY")
    seo = sb.get("seo") if isinstance(sb.get("seo"), dict) else {}
    sb["seo"] = dict(queries=[str(q)[:80] for q in (seo.get("queries") or [])][:3], description_hook=str(seo.get("description_hook") or "")[:300],
                     tags=[str(t)[:30] for t in (seo.get("tags") or sb.get("tags") or [])][:12], hashtags=[str(h) for h in (seo.get("hashtags") or [])][:4])
    sb["description"] = re.sub(r"\s+", " ", str(sb.get("description") or sb["seo"]["description_hook"] or "")).strip()[:600]
    sb["cta_question"] = str(sb.get("cta_question") or "").strip()[:140]
    sb["tags"] = sb["seo"]["tags"] or ["shorts", "storytime"]
    sb["topic_id"] = re.sub(r"[^a-z0-9-]", "", str(sb.get("topic_id") or sb["title"]).lower().replace(" ", "-"))[:60] or "story"
    sb.pop("title_options", None)
    sb.pop("hook_options", None)
    return sb

def pick_genre(memory):
    forced = os.environ.get("FORCE_GENRE", "").strip().lower()
    if forced in GENRES:
        return forced
    log = memory.get("genre_log", [])[-6:]
    learned = memory.get("genre_weights", {})              # written by studio.learn from real retention data
    weights = [(1.0 / (1 + log.count(g))) * float(learned.get(g, 1.0)) for g in GENRES]
    return random.choices(GENRES, weights=weights)[0]

# --------------------------------------------------------------------------- prompt + generation
def build_prompt(genre, used, hint, signals, grounded):
    if grounded:
        facts = ("STEP 1 - use Google Search to pick ONE well-documented, lesser-known story of this kind that is NOT in the USED list, and confirm 6-8 exact facts "
                 "(names of historical figures only, dates, numbers, places, outcome).\nSTEP 2 - write the package below using ONLY those verified facts; list them in facts_used.\n")
    elif genre == "crime":
        facts = "Pick ONE famous, thoroughly documented case you are certain about. Use only facts you are sure of and list them in facts_used.\n"
    else:
        facts = ""
    return f"""You are the head writer and packaging strategist of a viral faceless YouTube Shorts channel (narrated stick-figure animation).
Retention is the whole job: the first 3 seconds decide everything and the last line must make people replay.
{GENRE_BRIEF[genre]}
{CRAFT_RULES}
{facts}USED topics (never repeat): {json.dumps(used[-40:])}
What performed on this channel lately: {hint or 'n/a'}
Trending inspiration (optional, ignore if it does not fit): {json.dumps((signals or [])[:6])}
{SCHEMA_DOC}"""

def generate_story(memory, analytics_hint="", signals=None):
    _init_budget(memory)
    genre = pick_genre(memory)
    used = memory.get("used_topics", [])
    reject = ""
    for attempt in range(2):
        grounded = genre == "crime" and attempt == 0
        prompt = build_prompt(genre, used, analytics_hint, signals, grounded) + reject
        raw = _gemini_text(prompt, grounded=grounded)
        if not raw and grounded:
            raw = _gemini_text(build_prompt(genre, used, analytics_hint, signals, False) + reject)
        if not raw:
            plain = build_prompt(genre, used, analytics_hint, signals, False) + reject
            raw = _github_models_text(plain) or _pollinations_text(plain)
        if not raw:
            break
        try:
            sb = normalize(_extract_json(raw), genre)
            if sb["topic_id"] in used:
                raise ValueError("topic already used")
            print("PACKAGE:", P.package_report(sb))
            return sb
        except Exception as e:
            print(f"Story draft {attempt + 1} rejected: {str(e)[:100]}")
            reject = f"\n\nYour previous answer was rejected ({str(e)[:100]}). Return the corrected JSON only."
    print("LLM unavailable, out of quota or invalid - using a curated backup story.")
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

# packaging for the curated backups (so even a no-LLM run ships a fully optimised upload)
BACKUP_PACK = {
 "crime": dict(hook_card="NO ONE FIRED", thumb=dict(text="NO ONE FIRED", setting="vault", lighting="dark", role="criminal", pose="sneak", face="smirk", prop="moneybag", set_piece="safe",
                 bg_prompt="A dark bank vault with glowing gold bars and a shadow of a masked crew"),
        title_options=["The 1950 Brink's Heist: 11 Men, Zero Shots", "How 11 Masked Men Robbed Boston in 1950"],
        seo=dict(queries=["brinks robbery 1950", "biggest heist in american history", "boston great brinks robbery explained"],
                 description_hook="The 1950 Brink's robbery in Boston: eleven masked men, almost three million dollars, and the one grudge that ended it.",
                 tags=["brinks robbery", "1950 heist", "boston heist", "true crime", "specs o'keefe", "great brinks robbery"], hashtags=["#truecrime", "#heist", "#history"]),
        cta_question="Perfect crime or just lucky timing?"),
 "thriller": dict(hook_card="3:07 AM", thumb=dict(text="DON'T OPEN IT", setting="room", lighting="dark", role="hero", pose="cower", face="screaming", prop="phone",
                 bg_prompt="A dark bedroom lit only by a glowing phone screen, long creepy shadow in the doorway"),
        title_options=["The Text I Got From My Own Number at 3AM", "My Phone Texted Me From My Own Number"],
        seo=dict(queries=["text from my own number scary story", "scary stories to tell at night", "creepy text message horror short"],
                 description_hook="At 3:07 AM a text arrives from your own number. A scary short story in 40 seconds.",
                 tags=["scary story", "horror short", "creepy text", "own number", "3am story", "short horror"], hashtags=["#horrorstories", "#scary", "#creepy"]),
        cta_question="Would you have opened the door?"),
 "comedy": dict(hook_card="4 HOURS. NO MANUAL.", thumb=dict(text="BIG MISTAKE", setting="room", lighting="day", role="hero", pose="panic", face="screaming", prop=None, set_piece="wardrobe",
                 bg_prompt="A cheerful living room full of flat-pack wardrobe pieces and screws flying everywhere"),
        title_options=["I Built A Wardrobe With No Instructions", "4 Hours Building A Wardrobe: Worst Idea Ever"],
        seo=dict(queries=["flat pack furniture fail", "funny wardrobe assembly story", "building furniture without instructions"],
                 description_hook="One wardrobe, four hours, zero instructions: a funny flat-pack disaster story.",
                 tags=["flat pack fail", "furniture assembly", "funny story", "storytime", "wardrobe fail", "relatable"], hashtags=["#funnystories", "#storytime", "#comedy"]),
        cta_question="Instructions: read them first or never?"),
}

def backup_story(genre, used):
    import copy
    base = BACKUPS.get(genre) or BACKUPS["comedy"]
    sb = copy.deepcopy(base)
    sb.update(copy.deepcopy(BACKUP_PACK[sb["genre"]]))
    sb["title_options"] = sb["title_options"] + [sb["title"]]
    return normalize(sb, sb["genre"])

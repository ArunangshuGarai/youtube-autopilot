"""Local (zero-API) packaging brain: hook scoring, title/thumbnail linting and the SEO package.

Rules are adapted from the yt-script / yt-package / yt-seo skills:
  - a hook must be specific, tense, open a loop the viewer cannot close, and be short enough to say in ~5 seconds
  - the title and the thumbnail are ONE unit: different words, same promise, <=3 thumbnail words, <=60 title chars
  - the first two description lines are the search snippet; tags only disambiguate; 3 target queries must appear in the title/description
Nothing here calls an API, so quality gates cost nothing.
"""
import re

HOOK_FORMULAS = [
    ("the-statistic", "A number the viewer did not know, stated flat, then the consequence."),
    ("the-impossible", "State something that sounds untrue, then prove it."),
    ("the-warning", "A cost the viewer is about to pay."),
    ("the-mistake", "Name the error someone makes, in a way that makes the viewer check themselves."),
    ("cold-open", "Start mid-action at the worst possible moment, then rewind."),
    ("contrarian-flip", "State the accepted belief, then break it."),
    ("the-question", "Ask the exact question the viewer would type into search."),
    ("the-superlative", "The single dumbest / luckiest / scariest example of a category."),
    ("the-clock", "Bound the payoff in time: 'In the next 40 seconds...'"),
    ("the-receipt", "Show the damning artifact first, explain second."),
]

VAGUE = {"amazing", "incredible", "insane", "crazy", "huge", "massive", "secret", "ultimate", "best", "unbelievable", "epic", "mindblowing", "perfect"}
FILLER = {"basically", "actually", "literally", "just", "really", "very", "so", "kind", "sort", "like", "guys", "hey", "welcome", "today", "video", "subscribe", "channel"}
STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are", "with", "your", "you", "my", "i", "this", "that", "it", "how", "what", "why", "was", "were", "he", "she", "they"}
STAKE = re.compile(r"\b(lose|lost|die|died|dead|dying|kill|killed|stolen|stole|robbed|trapped|vanished|disappeared|missing|escaped|caught|never|only|last|crash|fail|failed|wrong|worst|danger|scream|blood|gone|bank|million|prison|jail|police|cops?|shot|fired|gun|knife|zero|nobody|nothing|alone|behind|locked|hid|hiding|chased|heist|escape|trap|empty|midnight|dark|scream|screamed|wrong|ruin|ruined|destroyed|exploded|collapsed)\b|not a single|no one", re.I)
LOOP = re.compile(r"\b(why|how|what|who|which|until|before|but|nobody|no one|except|reason|then|until|didn't|didnt|never|without|wasn't|not a single|only)\b", re.I)
CONCRETE = re.compile(r"\b(\d[\d,.]*\s?(%|k|m|x|am|pm|a\.m\.|p\.m\.)?|\$\d[\d,.]*|(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|hundred|thousand|million|billion)\b)", re.I)
YEAR = re.compile(r"\b(1[5-9]\d\d|20[0-2]\d)\b")

def words(t):
    return re.findall(r"[a-z0-9%$.]+", t.lower().replace("'", "").replace("\u2019", ""))

# ----------------------------------------------------------------------------- hooks
def score_hook(text):
    """0-100 on five properties; verdict = 60% mean + 40% weakest (a dead property is where viewers leak)."""
    t = text.strip()
    w = words(t)
    n = len(w)
    if n == 0:
        return dict(props={}, verdict=0, band="WEAK", weakest="BREVITY")
    nums = len(CONCRETE.findall(t)) + len(YEAR.findall(t))
    propers = sum(1 for x in t.split()[1:] if x[:1].isupper())
    vague = sum(1 for x in w if x in VAGUE)
    filler = sum(1 for x in w if x in FILLER)
    specificity = max(0, min(100, 30 + nums * 20 + min(propers, 3) * 8 - vague * 16 - filler * 6))
    tension = max(0, min(100, 22 + len(STAKE.findall(t)) * 24))
    loops = len(LOOP.findall(t))
    closed = -16 if re.search(r"\b(because|so that|which means)\b", t, re.I) else 0
    curiosity = max(0, min(100, 22 + loops * 16 + (16 if t.endswith("?") else 0) + closed + (10 if "." in t.rstrip(".") else 0)))
    # fragments ("Eleven men. Rubber masks.") read faster and hit harder than one long sentence
    frag = len([s for s in re.split(r"[.!?]", t) if s.strip()])
    punch = max(0, min(100, 40 + (frag - 1) * 18 + (14 if re.search(r"\b(i|my|you|your)\b", " ".join(t.lower().split()[:6])) else 0)))
    # a Short hook is said in ~4-5 seconds: 6 to 17 words
    brevity = 100 if 6 <= n <= 17 else (max(20, 100 - (6 - n) * 14) if n < 6 else max(10, 100 - (n - 17) * 9))
    props = dict(SPECIFICITY=specificity, TENSION=tension, CURIOSITY=curiosity, PUNCH=punch, BREVITY=brevity)
    vals = list(props.values())
    verdict = round(0.6 * sum(vals) / len(vals) + 0.4 * min(vals))
    band = "STRONG" if verdict >= 66 else "WORKABLE" if verdict >= 52 else "WEAK"
    return dict(props=props, verdict=verdict, band=band, weakest=min(props, key=props.get))

HOOK_FIX = {
    "SPECIFICITY": "swap an adjective for a number, a year or a name",
    "TENSION": "name what is at stake - money, freedom, safety, a life",
    "CURIOSITY": "end on a gap the viewer cannot close (cut the half that explains itself)",
    "PUNCH": "break it into short fragments and start mid-action",
    "BREVITY": "6 to 17 words - say it out loud and stop when you run out of breath",
}

def best_hook(options):
    """options: list of strings (or dicts with 'text'). Returns (index, text, report) of the highest scorer."""
    scored = []
    for i, o in enumerate(options):
        txt = o["text"] if isinstance(o, dict) else str(o)
        scored.append((score_hook(txt)["verdict"], i, txt))
    scored.sort(key=lambda r: (-r[0], r[1]))
    v, i, txt = scored[0]
    return i, txt, score_hook(txt)

# ----------------------------------------------------------------------------- title + thumbnail
def lint_title(title, thumb=None):
    t = title.strip()
    n = len(t)
    issues, good = [], []
    if n > 60:
        issues.append(("length", f"{n} chars - desktop search cuts near 60"))
    else:
        good.append(f"{n} chars")
    if n > 40 and len(t[:40].rsplit(" ", 1)[0].split()) < 3:
        issues.append(("front-load", "subject is not in the first 40 characters"))
    caps = [x for x in t.split() if len(x) > 2 and x.isupper()]
    if len(caps) > 2:
        issues.append(("shouting", "more than two ALL-CAPS words reads as spam"))
    v = [x for x in words(t) if x in VAGUE]
    if v:
        issues.append(("vague", ", ".join(sorted(set(v)))))
    if CONCRETE.search(t) or YEAR.search(t) or any(x[:1].isupper() for x in t.split()[1:]):
        good.append("has a number/year/name")
    else:
        issues.append(("no-number", "no number, year or name"))
    front = [x for x in words(t)[:3] if x not in STOP]
    if not front:
        issues.append(("front-load", "first three words are filler"))
    if thumb:
        shared = (set(words(t)) - STOP) & (set(words(thumb)) - STOP)
        if shared:
            issues.append(("duplicate", "thumbnail repeats the title on: " + ", ".join(sorted(shared))))
        if len(words(thumb)) > 3:
            issues.append(("thumb-length", f"{len(words(thumb))} thumbnail words - three is the ceiling"))
    score = max(0, min(100, 100 - 14 * len(issues) + 4 * len(good)))
    return dict(title=t, chars=n, score=score, issues=issues)

def pick_title(options, thumb, queries=()):
    """Highest lint score wins; ties go to the title that covers the most words of the target search queries, then to ~46 chars."""
    cands = [str(o).strip() for o in options if str(o).strip()]
    if not cands:
        return None
    qwords = {w for q in queries for w in words(q) if w not in STOP}
    def cover(c):
        return len(qwords & set(words(c))) if qwords else 0
    ranked = sorted(((lint_title(c, thumb)["score"] + 3 * cover(c), -abs(len(c) - 46), c) for c in cands), reverse=True)
    return ranked[0][2]

def clean_thumb_text(text, title):
    """<=3 words, ALL CAPS, and no word shared with the title."""
    tw = set(words(title)) - STOP
    ws = [w for w in re.findall(r"[A-Za-z0-9'$%?!]+", str(text)) if w.lower().strip("?!") not in tw]
    return " ".join(ws[:3]).upper() or "WAIT FOR IT"

# ----------------------------------------------------------------------------- SEO package
HASHTAGS = {"crime": ["#truecrime", "#crimestory", "#mystery"], "thriller": ["#horrorstories", "#scarystories", "#creepy"], "comedy": ["#funnystories", "#storytime", "#comedy"]}
BASE_TAGS = {"crime": ["true crime", "true crime stories", "heist", "unsolved", "crime documentary", "history"],
             "thriller": ["scary stories", "horror stories", "creepy stories", "thriller", "short horror", "creepypasta"],
             "comedy": ["funny stories", "storytime", "comedy", "funny shorts", "relatable", "story time animated"]}

def build_seo(sb):
    """Return dict(title, description, tags, hashtags, queries) - the full search-facing package."""
    genre = sb["genre"]
    seo = sb.get("seo") or {}
    queries = [q.strip() for q in seo.get("queries", []) if q.strip()][:3]
    title = sb["title"]
    first = (seo.get("description_hook") or sb.get("description") or "").strip()
    # query test (yt-seo): the title + first lines should contain the words of the queries we want to win.
    # We never bolt raw queries onto the description (that reads as stuffing); the title is picked for coverage instead.
    haystack = set(words(title + " " + first))
    coverage = {q: round(sum(1 for w in words(q) if w in haystack) / max(1, len([w for w in words(q)])), 2) for q in queries}
    tags, seen = [], set()
    for tg in list(seo.get("tags", [])) + list(sb.get("tags", [])) + queries + BASE_TAGS[genre]:
        tg = re.sub(r"[#,]", "", str(tg)).strip()
        if tg and tg.lower() not in seen and len(tg) <= 30:
            seen.add(tg.lower()); tags.append(tg)
    tags = tags[:15]
    while sum(len(t) + 1 for t in tags) > 450:
        tags.pop()
    hashtags = []
    for h in list(seo.get("hashtags", [])) + HASHTAGS[genre]:
        h = "#" + re.sub(r"[^A-Za-z0-9]", "", str(h))
        if len(h) > 2 and h.lower() not in [x.lower() for x in hashtags]:
            hashtags.append(h)
    hashtags = hashtags[:4]
    if "#shorts" not in [h.lower() for h in hashtags]:
        hashtags.append("#Shorts")
    cta = sb.get("cta_question") or ""
    parts = [first]
    if sb.get("description") and sb["description"].strip() != first:
        parts.append(sb["description"].strip())
    if cta:
        parts.append(cta.strip())
    if sb.get("is_fiction") and "fictional" not in " ".join(parts).lower():
        parts.append("This is a fictional story.")
    parts.append(" ".join(hashtags))
    desc = "\n\n".join(p for p in parts if p)
    final_title = title if "#shorts" in title.lower() else title
    return dict(title=final_title[:95], description=desc[:4800], tags=tags, hashtags=hashtags, queries=queries, coverage=coverage)

def package_report(sb):
    """Human-readable gate summary for the logs."""
    h = score_hook(sb["scenes"][0]["narration"])
    tl = lint_title(sb["title"], sb.get("thumb_text"))
    return (f"HOOK '{sb['scenes'][0]['narration']}' -> {h['verdict']} {h['band']} (weakest {h['weakest']}) | "
            f"TITLE '{sb['title']}' -> {tl['score']} {[k for k, _ in tl['issues']]} | THUMB '{sb.get('thumb_text')}'")

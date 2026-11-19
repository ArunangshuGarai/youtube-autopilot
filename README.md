# youtube-autopilot

A fully free, fully automatic faceless **YouTube Shorts studio** that runs on GitHub Actions.
It writes, voices, animates, captions, scores, QA-checks and uploads stick-figure Shorts in three genres:
**crime**, **thriller** and **comedy**.

## How a Short is made
| Step | What | Cost |
|---|---|---|
| Learn + scout | `studio/learn.py` reads your own retention (YouTube Analytics) and nudges genre weights toward what holds viewers; it also hunts recent Shorts in each niche and ranks them by how far they beat their own channel's size. YouTube APIs only, no LLM calls. | free |
| Script | **One** Gemini call returns the whole package: 5 hook options, hook card, 5 titles, thumbnail brief, SEO queries/tags/description, comment-bait question and 10 scenes in a fixed retention structure (hook > stakes > build > turn > escalate > twist > loop). True crime is researched with grounded search inside that same call. | free tier, ~1 call/video |
| Local gates | `studio/packaging.py` scores the hooks, lints the titles, enforces the thumbnail-vs-title rule and builds tags/description with zero API calls. A weak hook triggers one rewrite. | free |
| Animation | pycairo stick figures + hook card, camera punches on stressed words, comic impact text, ambient fog/dust, progress bar, comment-bait end card. | free |
| Thumbnail | `studio/thumb.py`: AI background when reachable (optional Gemini image model or free Pollinations), otherwise a vector close-up; sunburst, sticker-outlined hero with an extreme face, 2-line headline, genre badge. | free |
| Voice | Kokoro neural TTS (per-genre profiles); `edge-tts` fallback. Acronyms are spoken as letters. | free |
| Captions | Whisper word timing, 2-3 words at a time, spoken word highlighted. | free |
| Music + SFX | Synthesized per mood, ducked under the voice, -14 LUFS. | free |
| QA | Duration, audio, blank-frame, size checks. Optional Gemini vision audit (`VISION_AUDIT=1`). | free |
| Upload | SEO title (<=58 chars), 2-line search snippet, tags, hashtags, "not made for kids", **altered/synthetic = No**, scheduled publish, custom thumbnail. | free |

### Staying inside the free Gemini quota
Calls per day are counted in `memory.json` (`GEMINI_DAILY_BUDGET`, default 14). A model that answers 429 is skipped for the rest of the run instead of being slept on, then the chain falls through GitHub Models, Pollinations and finally a curated backup story, so a run never fails on quota.

## One-time setup
Repo **Settings > Secrets and variables > Actions**:
- Secrets: `GEMINI_API_KEY`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`
- Optional variables: `TTS_PROVIDER` (`kokoro` or `edge`), `VOICE_GRAVE`, `VOICE_TENSE`, `VOICE_JOLLY`, `VOICE_SARCASTIC`, `GEMINI_TEXT_MODELS` (comma list), `FORCE_GENRE`, `GEMINI_DAILY_BUDGET`, `GEMINI_IMAGE_MODEL` (optional, for AI thumbnail backgrounds), `THUMB_AI=0`, `VISION_AUDIT=1`

## Workflows
- **Autonomous YouTube Studio** - the scheduled/manual publisher.
- **Preview Short (no upload)** - renders a Short and gives you the MP4 as a download. Use this to review before trusting the schedule.
- **Voice Lab** - renders the same lines in ~20 voices. Listen, then set the `VOICE_*` variables.

## Local preview
```bash
pip install -r requirements.txt   # plus ffmpeg, libcairo2-dev, espeak-ng
python -m studio --genre thriller            # built-in sample story
python -m studio --genre crime --live        # new story from Gemini (needs GEMINI_API_KEY)
python -m unittest discover tests            # offline tests
```

## Notes
- The first 14 bot uploads are limited to one scheduled run per day (warm-up gate, counts `bot_uploads` in `memory.json`).
- Crime stories must be well-documented historical cases; fiction is labelled "This is a fictional story." in the description. Facts used are logged in `memory.json` for audit.
- Fonts: Anton and Bangers (SIL Open Font License), see `assets/fonts`.

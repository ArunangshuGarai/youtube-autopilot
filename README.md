# youtube-autopilot

A fully free, fully automatic faceless **YouTube Shorts studio** that runs on GitHub Actions.
It writes, voices, animates, captions, scores, QA-checks and uploads stick-figure Shorts in three genres:
**crime**, **thriller** and **comedy**.

## How a Short is made
| Step | What | Cost |
|---|---|---|
| Script | Gemini (free tier) writes a structured storyboard: hook, 9-11 scenes, poses, faces, props, camera moves, SFX, music mood. True-crime uses a grounded fact lookup first. Backup stories exist if the LLM is down. | free |
| Animation | `studio/stickman.py` + `studio/scenes.py` draw a **consistent** stick figure in code (pycairo): 25 poses, 14 expressions, 10 character roles, 18 props, 12 backgrounds, 15 set pieces, camera pushes/shakes/pans, effects. No image APIs, so nothing runs out of quota. | free |
| Voice | Kokoro neural TTS (per-genre voice profiles, sentence-by-sentence pacing); `edge-tts` as optional/fallback. Acronyms are spoken as letters (FBI -> "F B I", IV -> "eye-vee"). | free |
| Captions | Whisper (`faster-whisper`) times every word; captions pop in 2-3 words at a time with the spoken word highlighted. | free |
| Music + SFX | Synthesized in code per mood (tense / dark / sneaky / quirky / upbeat...), ducked under the voice, loudness-normalised to -14 LUFS. | free |
| QA | Duration, audio level, blank-frame and size checks before upload. | free |
| Upload | Title, description, tags, category, thumbnail, "not made for kids", **altered/synthetic content = No**, scheduled publish. | free |

## One-time setup
Repo **Settings > Secrets and variables > Actions**:
- Secrets: `GEMINI_API_KEY`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`
- Optional variables: `TTS_PROVIDER` (`kokoro` or `edge`), `VOICE_GRAVE`, `VOICE_TENSE`, `VOICE_JOLLY`, `VOICE_SARCASTIC`, `GEMINI_TEXT_MODELS` (comma list), `FORCE_GENRE`

## Workflows
- **Autonomous YouTube Studio** - the scheduled/manual publisher.
- **Preview Short (no upload)** - renders a Short and gives you the MP4 as a download. Use this to review before trusting the schedule.
- **Voice Lab** - renders the same lines in ~20 voices. Listen, then set the `VOICE_*` variables.

## Local preview
```bash
pip install -r requirements.txt   # plus ffmpeg, libcairo2-dev, espeak-ng
python -m studio --genre thriller            # built-in sample story
python -m studio --genre crime --live        # new story from Gemini (needs GEMINI_API_KEY)
```

## Notes
- The first 14 bot uploads are limited to one scheduled run per day (warm-up gate, counts `bot_uploads` in `memory.json`).
- Crime stories must be well-documented historical cases; fiction is labelled "This is a fictional story." in the description. Facts used are logged in `memory.json` for audit.
- Fonts: Anton and Bangers (SIL Open Font License), see `assets/fonts`.

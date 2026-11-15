# Short Video Pipeline (facts/trivia, faceless) — saves locally

Generates a short facts/trivia video end to end — script, AI voiceover,
background footage, burned-in captions — and saves the finished mp4 to a
folder on your machine. Nothing is uploaded or published anywhere by
default. Runs from your own machine; there's no hosted/always-on piece.

```
script_gen.py  -> writes title/hook/facts/cta  (Gemini free tier, Claude, or built-in fallback)
tts.py         -> narration audio              (edge-tts, free, no key)
visuals.py     -> vertical background video    (your clips/ folder, e.g. Google Flow; Pixabay/Pexels API; or gradient)
captions.py    -> animated word-by-word captions, title card, fact chips, progress bar (.ass)
compose.py     -> background motion/grade, music, -14 LUFS audio, YouTube-spec encode -> ./output/
upload.py      -> OPTIONAL: uploads to YouTube, only runs if you pass --upload
main.py        -> wires the above together, CLI entry point
```

## 1. Install

You need **ffmpeg** installed as a system binary (not a pip package):

- macOS: `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt install ffmpeg`
- Windows: download from ffmpeg.org and add it to PATH

Then, from this folder:

```bash
python -m venv venv
source venv/bin/activate   # venv\Scripts\activate on Windows
pip install -r requirements.txt
cp config.example.env .env
```

This installs everything needed to generate and save videos locally.
(There's a separate `requirements-upload.txt` for the YouTube-upload
extras — see the optional section near the bottom; skip it if you only
want local files.)

## 2. Try it with zero API keys first

```bash
python -m src.main --topic "space facts"
```

This uses the built-in fallback script generator, a free TTS voice, and a
gradient background, and drops the finished mp4 in `./output/`. It's a
smoke test — the pipeline is much better with the two free/cheap keys
below.

## 3. Get a free Gemini API key (for real script variety)

Without an AI key, every video reuses the same tiny built-in fact list.
With one, each run writes a fresh script. Google's Gemini API has a free
tier — no credit card needed:

1. Go to https://aistudio.google.com/apikey and sign in with your Google account.
2. Click **Create API key** (accept the terms if asked) and copy the key.
3. Put it in `.env` as `GEMINI_API_KEY=...`.

Notes: the free tier has daily request limits (each video uses one
request, so a handful of videos a day is fine), and Google may use
free-tier prompts and responses to improve its products. If a run hits the
limit, the pipeline falls back to the built-in facts for that video.

**Paid alternative:** set `ANTHROPIC_API_KEY` (from
https://console.anthropic.com/) to have Claude write scripts instead; it's
tried first when set.

## 4. Background footage from Google Flow (free, recommended)

(For a specific visual on each fact, see 4a below. This section covers a
general clip library.)

Google Flow (https://labs.google/flow) generates video clips with Google's
Veo model. It has no API, so you make the clips there and the pipeline
uses them:

1. Open Flow, sign in with your Google account, and create a project.
2. Generate clips with prompts like *"slow drift through a starfield
   nebula, cinematic, no text"*. Pick **9:16 (portrait)** if Flow offers
   it; landscape clips are center-cropped to vertical automatically.
   Free accounts get a daily allowance of credits; the cheaper "Fast"/"Lite"
   models stretch it further.
3. Download each clip (mp4) into this project's `clips/` folder. To match
   clips to topics, either use subfolders (`clips/space/`, `clips/ocean/`)
   or put a topic word in the filename (`space_nebula_01.mp4`).
4. Run as usual. Each video picks clips matching the topic (or any clip if
   none match), shuffles them, and plays them back to back to cover the
   narration — Flow clips are ~8s, so 4–5 clips per topic gives variety.

Change the folder with `CLIPS_DIR=` in `.env`. Check Flow's terms for
commercial use of generated clips before monetizing.

## 4a. A different image or video for every fact (plan → add media → render)

Each script has one **scene** per narration line (hook, each fact, closing
line). Each scene comes with an AI-written visual prompt and keywords, and
the background switches when the narration moves to the next line.

**Step 1: plan.** Writes the script and a shot list, but doesn't render:

```bash
venv/bin/python -m src.main --topic "ocean facts" --plan
```

This creates `projects/<title>_<date>/` with:
- `shotlist.md`: for every scene, the narration, a ready-to-paste prompt for
  Google Flow (or any image generator), and the filename to save it as.
- `script.json`: the script. Edit it to fix wording or facts before rendering.
- `media/`: an empty folder for your visuals.

**Step 2: add media.** Save one file per scene in `media/`, named by scene
number: `01.jpg`, `02.mp4`, `03_octopus.png`, ... Images (jpg/png/webp) get
a slow zoom. Videos (mp4/mov) are cropped to 9:16 and looped if shorter than
the scene. You don't need a file for every scene.

**Step 3: render.**

```bash
venv/bin/python -m src.main --project "projects/<title>_<date>"
```

Scenes without a numbered file use the best **keyword match** from
`clips/` (images or videos, matched on file and folder names, e.g.
`clips/octopus_reef.mp4`), then any topic-matching clip, then a gradient.

A normal one-step run (`--topic` without `--plan`) does the same scene
matching against `clips/`, so a well-named clip library gives each fact
its own visual automatically.

## 4b. Or: a Pixabay API key (stock footage)

Free, instant signup.

1. Sign up at https://pixabay.com/ (free account).
2. Go to https://pixabay.com/api/docs/ while logged in — your key is shown
   in the "Parameters" section under `key`.
3. Put it in `.env` as `PIXABAY_API_KEY=...`.

Most Pixabay clips are landscape; the pipeline prefers portrait ones and
center-crops the rest to 9:16. Pixabay's terms ask you to cache results
rather than hammer the API, and the free tier allows 100 requests/minute.

If you already have a Pexels key, set `PEXELS_API_KEY=...` too — it's used
when Pixabay is missing or fails. (Pexels paused new key signups in late
2026.) Without either key, backgrounds are a plain animated gradient.

## 4c. What the video looks like (and how to change it)

- **Captions:** 1–3 big uppercase words at a time, centred just below the
  middle, with the word being spoken highlighted and popping in. Timed to
  the voice word-by-word.
- **Title card** at the top for the whole video, **"FACT 2/5" chip** above
  the captions during each fact, and a **progress bar** along the top edge.
- Text stays out of the bottom ~20% and right edge, where the Shorts player
  draws the channel name and buttons.
- **Background:** slow drift/zoom, mild colour grade and vignette so text
  reads on any footage.
- **Audio:** optional background music from `./music/`, mixed under the
  voice, normalised to −14 LUFS (YouTube's playback loudness).
- **Encoding:** 1080×1920, 30 fps, H.264 High, BT.709, AAC 48 kHz 192 kbps,
  faststart — the file can be uploaded to YouTube Shorts as-is.

Fonts, colours, music volume, and voice are set in `.env` (see the
"Look & sound" section of `config.example.env`).

## 5. Run it for real

```bash
python -m src.main --topic "ocean facts"
```

Finished videos land in `./output/` as `<title>_<timestamp>.mp4`, ready to
open, watch, or move/upload yourself however you like.

Other flags:

```bash
python -m src.main --topic "space facts" --plan                     # script + shot list only (see 4a)
python -m src.main --project projects/<name>                        # render a planned project
python -m src.main --topic "space facts" --count 3                  # generate 3 videos this run
python -m src.main --topic "space facts" --output-dir ~/Videos/shorts  # choose where files are saved
```

## 6. Running it on a schedule (still local-only)

This repo is just scripts — nothing runs unless something invokes it. Two
common ways to automate that:

**cron (macOS/Linux)**, e.g. once a day at 9am:
```
0 9 * * * cd /path/to/yt-shorts-pipeline && /path/to/venv/bin/python -m src.main --topic "space facts" >> run.log 2>&1
```

**Windows Task Scheduler**: create a task that runs
`venv\Scripts\python.exe -m src.main --topic "space facts"`
with "Start in" set to this folder, on whatever trigger you want.

Rotate topics by calling it with a different `--topic` on different days,
or write a tiny wrapper script that picks a topic from a list.

## 7. Optional: uploading to YouTube too

If you later want a finished video pushed straight to YouTube instead of
just sitting in `./output/`, the pipeline supports that behind a flag —
it's just not the default anymore.

```bash
pip install -r requirements-upload.txt
```

Then set up OAuth once:

1. Go to https://console.cloud.google.com/ and create a project (or reuse one).
2. Enable the **YouTube Data API v3** for that project (APIs & Services → Enable APIs).
3. Go to APIs & Services → OAuth consent screen. Choose "External" (or
   "Internal" if you have a Google Workspace), fill in the required fields.
   You can leave it in "Testing" mode and add your own Google account as a
   test user — you don't need to publish the app.
4. Go to APIs & Services → Credentials → Create Credentials → OAuth client ID.
   Application type: **Desktop app**. Download the resulting JSON.
5. Save that file into this folder as `client_secret.json` (or point
   `YOUTUBE_CLIENT_SECRET` in `.env` at wherever you put it).
6. Run with `--upload`:
   ```bash
   python -m src.main --topic "ocean facts" --upload --privacy unlisted
   ```
   The first run opens a browser window asking you to log in and consent —
   do that once. After that, the session is cached in `token.json` and you
   won't be prompted again. Start with `--privacy private` or `unlisted`
   and check the result in YouTube Studio before using `public`.

**Quota note:** the YouTube Data API's default daily quota is 10,000 units,
and each video upload costs 1,600 units — so by default you get about
6 uploads/day before you'd need to request a quota increase from Google
(Console → APIs & Services → Quotas).

**Before relying on uploads for income:** YouTube's monetization policy
(tightened mid-2026) doesn't ban AI or faceless content, but it does
exclude videos that are generic, templated, or give the impression of mass
production without the creator's own original input. Keep
`GEMINI_API_KEY` (or `ANTHROPIC_API_KEY`) set so scripts vary, review output before publishing
rather than running it fully unattended, and remember the Partner Program
itself still requires 1,000 subscribers plus either 10M Shorts views in 90
days or 4,000 watch hours in 12 months before any of this earns ad revenue.

## Troubleshooting

- `ffmpeg: command not found` → install ffmpeg as a system package (step 1), not via pip.
- Pexels fetch fails / rate-limited → it falls back to the gradient background automatically; check your key and the free-tier rate limit if you want real footage back.
- `--upload` fails with a 403 about quota → you've hit the daily unit quota (see section 7); either wait for reset or request a quota increase.
- OAuth browser window doesn't open on a headless server → run the first authorization on a machine with a browser, then copy the resulting `token.json` to the server.

# Short Video Pipeline (facts/trivia, faceless) — saves locally

Generates a short facts/trivia video end to end — script, AI voiceover,
background footage, burned-in captions — and saves the finished mp4 to a
folder on your machine. Nothing is uploaded or published anywhere by
default. Runs from your own machine; there's no hosted/always-on piece.

```
script_gen.py  -> writes title/hook/facts/cta  (Anthropic API, or built-in fallback)
tts.py         -> narration audio              (edge-tts, free, no key)
visuals.py     -> vertical background video    (Pixabay or Pexels API, free key, or gradient fallback)
captions.py    -> timed .srt captions
compose.py     -> merges it all with ffmpeg -> final mp4 saved to ./output/
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

## 3. Get an Anthropic API key (for real script variety)

Without this, every video reuses the same tiny built-in fact list. With a
key, each run writes a fresh script.

1. Go to https://console.anthropic.com/ and create an API key.
2. Put it in `.env` as `ANTHROPIC_API_KEY=sk-ant-...`.
3. Check https://docs.claude.com for the current model name and set
   `ANTHROPIC_MODEL` if the default in `config.example.env` is out of date.

## 4. Get a Pixabay API key (for real background footage)

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

## 5. Run it for real

```bash
python -m src.main --topic "ocean facts"
```

Finished videos land in `./output/` as `<title>_<timestamp>.mp4`, ready to
open, watch, or move/upload yourself however you like.

Other flags:

```bash
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
`ANTHROPIC_API_KEY` set so scripts vary, review output before publishing
rather than running it fully unattended, and remember the Partner Program
itself still requires 1,000 subscribers plus either 10M Shorts views in 90
days or 4,000 watch hours in 12 months before any of this earns ad revenue.

## Troubleshooting

- `ffmpeg: command not found` → install ffmpeg as a system package (step 1), not via pip.
- Pexels fetch fails / rate-limited → it falls back to the gradient background automatically; check your key and the free-tier rate limit if you want real footage back.
- `--upload` fails with a 403 about quota → you've hit the daily unit quota (see section 7); either wait for reset or request a quota increase.
- OAuth browser window doesn't open on a headless server → run the first authorization on a machine with a browser, then copy the resulting `token.json` to the server.

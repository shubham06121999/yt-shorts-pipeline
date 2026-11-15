"""
Gets a vertical background video to narrate over.

Per-scene backgrounds (build_scene_background): the script has one scene
per narration line, each with a visual prompt and keywords. Each scene gets
its own image or video, so the background changes as each fact is read:
  1. a file you put in the project's media folder named after the scene
     number (01.jpg, 02.mp4, 03_octopus.png, ...) - see `--plan` in main.py;
  2. otherwise the best keyword match in the clips folder (images or videos,
     matched on file/folder names);
  3. otherwise a topic-matching / random file from the clips folder;
  4. otherwise an animated gradient for that scene.
Images get a slow zoom (Ken Burns); videos are cropped to 9:16 and looped
if shorter than the scene.

Whole-video background (fetch_background_video, used when no scene has any
media):

Local clips first: if the clips folder (CLIPS_DIR, default ./clips) has video
files - e.g. clips you made in Google Flow and downloaded - several are picked,
cropped to 1080x1920, and played back to back to cover the narration. Clips in
a subfolder named after the topic (clips/space/ for "space facts") or whose
filename contains a topic word are preferred over the rest.

With PIXABAY_API_KEY set: searches Pixabay for a stock clip matching the
topic (portrait preferred; landscape clips are center-cropped to vertical).

With PEXELS_API_KEY set (and Pixabay missing or failing): searches Pexels for
a vertical stock clip instead.

With no clips and no keys: generates a simple looping animated gradient with ffmpeg so
the pipeline still runs end-to-end.
"""
import os
import random
import subprocess

import requests

PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"
PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"
TARGET_W, TARGET_H = 1080, 1920
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS
FPS = 30
STOPWORDS = {"facts", "fact", "trivia", "the", "and", "of", "about", "fun"}


def fetch_background_video(topic: str, out_path: str, min_duration: float) -> str:
    clips = _find_local_clips(topic, os.environ.get("CLIPS_DIR", "clips"))
    if clips:
        try:
            return _build_from_local_clips(clips, out_path, min_duration)
        except Exception as exc:  # noqa: BLE001
            print(f"[visuals] Local clips failed ({exc}); trying next source.")

    sources = [
        ("Pixabay", "PIXABAY_API_KEY", _fetch_from_pixabay),
        ("Pexels", "PEXELS_API_KEY", _fetch_from_pexels),
    ]
    for name, env_var, fetcher in sources:
        api_key = os.environ.get(env_var)
        if not api_key:
            continue
        try:
            return fetcher(topic, out_path, min_duration, api_key)
        except Exception as exc:  # noqa: BLE001
            print(f"[visuals] {name} fetch failed ({exc}); trying next source.")
    return _generate_gradient_background(out_path, min_duration)


# ---------------------------------------------------------------------------
# Per-scene backgrounds


def _list_media(folder: str):
    if not folder or not os.path.isdir(folder):
        return []
    found = []
    for root, _dirs, files in os.walk(folder):
        for name in sorted(files):
            if os.path.splitext(name)[1].lower() in MEDIA_EXTS and not name.startswith("."):
                found.append(os.path.join(root, name))
    return found


def _words_in(path: str, base: str):
    rel = os.path.relpath(path, base).lower()
    return set("".join(c if c.isalnum() else " " for c in os.path.splitext(rel)[0]).split())


def _numbered_media(media_dir: str):
    """{scene_number: path} for files named like 01.jpg / 2_octopus.mp4."""
    out = {}
    for path in _list_media(media_dir):
        stem = os.path.basename(path)
        digits = ""
        for ch in stem:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            out.setdefault(int(digits), path)
    return out


def assign_scene_media(scenes, topic: str, media_dir=None, clips_dir=None):
    """Pick an image/video for each scene. Returns a list of (path or None, why)."""
    clips_dir = clips_dir or os.environ.get("CLIPS_DIR", "clips")
    numbered = _numbered_media(media_dir) if media_dir else {}
    library = _list_media(clips_dir)
    lib_words = {p: _words_in(p, clips_dir) for p in library}
    topic_words = set(_topic_words(topic))
    topic_pool = [p for p in library if lib_words[p] & topic_words] or library

    used, picks, prev = {}, [], None
    for i, scene in enumerate(scenes, start=1):
        if i in numbered:
            picks.append((numbered[i], "project media"))
            prev = numbered[i]
            continue
        keywords = {k.lower() for k in scene.get("keywords", [])}
        best, best_score = None, 0
        for p in library:
            score = len(lib_words[p] & keywords) * 10 - used.get(p, 0) * 3 - (5 if p == prev else 0)
            if lib_words[p] & keywords and score > best_score:
                best, best_score = p, score
        why = "keyword match"
        if best is None and topic_pool:
            # Least-used topic clip, avoiding an immediate repeat.
            candidates = sorted(topic_pool, key=lambda p: (used.get(p, 0), p == prev, random.random()))
            best, why = candidates[0], "topic/random clip"
        if best is None:
            why = "gradient"
        else:
            used[best] = used.get(best, 0) + 1
        picks.append((best, why))
        prev = best
    return picks


def _render_segment(src, out_path: str, duration: float, palette_seed: int) -> None:
    duration = max(duration, 0.2)
    cover = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H}"
    )
    common_out = ["-t", f"{duration:.3f}", "-an", "-r", str(FPS),
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                  "-pix_fmt", "yuv420p", out_path]
    if src is None:
        random.seed(palette_seed)
        _generate_gradient_background(out_path, duration - 1)
        random.seed()
        return
    ext = os.path.splitext(src)[1].lower()
    if ext in IMAGE_EXTS:
        frames = int(duration * FPS) + 1
        # Upscale first so the slow zoom is smooth rather than jittery.
        zoom_in = palette_seed % 2 == 0
        z = "min(1+0.0012*on,1.18)" if zoom_in else "max(1.18-0.0012*on,1)"
        vf = (
            f"scale={TARGET_W * 2}:{TARGET_H * 2}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W * 2}:{TARGET_H * 2},"
            f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s={TARGET_W}x{TARGET_H}:fps={FPS},setsar=1"
        )
        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", src, "-vf", vf] + common_out
    else:
        vf = f"{cover},fps={FPS},setsar=1"
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", src, "-vf", vf] + common_out
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"couldn't use {os.path.basename(src)}: "
                           f"{result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'ffmpeg error'}")


def build_scene_background(scenes, line_timings, total_duration: float, topic: str,
                           out_path: str, media_dir=None) -> bool:
    """Build a background whose image/video changes with each narration line.
    Returns False (and builds nothing) if no scene found any media, so the
    caller can fall back to fetch_background_video()."""
    picks = assign_scene_media(scenes, topic, media_dir)
    if not any(path for path, _ in picks):
        return False

    # Scene i covers from its line's start to the next line's start.
    starts = [0.0] + [start for _text, start, _end in line_timings[1:len(picks)]]
    ends = starts[1:] + [total_duration + 1]
    work = out_path + "_scenes"
    os.makedirs(work, exist_ok=True)
    seg_paths = []
    for i, ((path, why), start, end) in enumerate(zip(picks, starts, ends), start=1):
        seg = os.path.join(work, f"seg{i:02d}.mp4")
        label = os.path.basename(path) if path else "-"
        print(f"[visuals] Scene {i:02d} ({end - start:4.1f}s): {label}  [{why}]")
        try:
            _render_segment(path, seg, end - start, i)
        except Exception as exc:  # noqa: BLE001
            print(f"[visuals]   {exc}; using a gradient for this scene")
            _render_segment(None, seg, end - start, i)
        seg_paths.append(seg)

    list_file = os.path.join(work, "list.txt")
    with open(list_file, "w") as f:
        for seg in seg_paths:
            f.write(f"file '{seg}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
         "-r", str(FPS), out_path],
        check=True, capture_output=True,
    )
    return True


# ---------------------------------------------------------------------------
# Whole-video background


def _topic_words(topic: str):
    words = "".join(c.lower() if c.isalnum() else " " for c in topic).split()
    return [w for w in words if w not in STOPWORDS] or words


def _find_local_clips(topic: str, clips_dir: str):
    """Return clip paths best matching the topic, or [] if the folder is empty."""
    if not os.path.isdir(clips_dir):
        return []
    all_clips = []
    for root, _dirs, files in os.walk(clips_dir):
        for name in files:
            if os.path.splitext(name)[1].lower() in VIDEO_EXTS and not name.startswith("."):
                all_clips.append(os.path.join(root, name))
    if not all_clips:
        return []

    words = _topic_words(topic)

    def matches(path: str) -> bool:
        rel = os.path.relpath(path, clips_dir).lower()
        return any(w in rel for w in words)

    matched = [c for c in all_clips if matches(c)]
    chosen = matched or all_clips
    print(f"[visuals] Using {len(chosen)} local clip(s) from {clips_dir}"
          f"{' matching topic' if matched else ' (none matched the topic, using all)'}")
    return chosen


def _probe_duration(path: str) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(probe.stdout.strip() or 0)


def _build_from_local_clips(clips, out_path: str, min_duration: float) -> str:
    """Crop clips to vertical and play them back to back until the narration is covered."""
    target = min_duration + 1
    pool = list(clips)
    random.shuffle(pool)
    durations = {c: _probe_duration(c) for c in pool}
    pool = [c for c in pool if durations[c] > 0.5]
    if not pool:
        raise RuntimeError("no readable video clips")

    sequence, total, i = [], 0.0, 0
    while total < target:
        clip = pool[i % len(pool)]
        sequence.append(clip)
        total += durations[clip]
        i += 1

    vf = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},fps=30,setsar=1,format=yuv420p"
    )
    cmd = ["ffmpeg", "-y"]
    for clip in sequence:
        cmd += ["-i", clip]
    chains = "".join(f"[{n}:v:0]{vf}[v{n}];" for n in range(len(sequence)))
    joined = "".join(f"[v{n}]" for n in range(len(sequence)))
    cmd += [
        "-filter_complex", f"{chains}{joined}concat=n={len(sequence)}:v=1:a=0[out]",
        "-map", "[out]", "-t", str(target),
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def _fetch_from_pixabay(topic: str, out_path: str, min_duration: float, api_key: str) -> str:
    resp = requests.get(
        PIXABAY_SEARCH_URL,
        params={"key": api_key, "q": topic[:100], "per_page": 20, "safesearch": "true"},
        timeout=20,
    )
    if not resp.ok:
        # Don't use raise_for_status(): its message includes the URL, which
        # contains the API key, and would leak it into logs.
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200].strip()}")
    hits = resp.json().get("hits", [])
    if not hits:
        raise RuntimeError(f"no Pixabay results for '{topic}'")

    random.shuffle(hits)
    # Prefer portrait clips; landscape ones still work (they get center-cropped).
    hits.sort(key=lambda h: (_pixabay_best_file(h) or (None, 0))[1], reverse=True)
    for hit in hits:
        best = _pixabay_best_file(hit)
        if not best:
            continue
        _download_and_normalize(best[0]["url"], out_path, min_duration)
        return out_path
    raise RuntimeError(f"no downloadable video files among Pixabay results for '{topic}'")


def _pixabay_best_file(hit: dict):
    """Return (file, is_portrait) for the largest usable rendition, or None."""
    files = [
        f for f in hit.get("videos", {}).values()
        if f.get("url") and f.get("width") and f.get("height")
    ]
    if not files:
        return None
    files.sort(key=lambda f: f["width"] * f["height"], reverse=True)
    # Skip 4K renditions when a smaller one exists: they're slow to download.
    usable = [f for f in files if max(f["width"], f["height"]) <= 2560] or files
    best = usable[0]
    return best, int(best["height"] >= best["width"])


def _download_and_normalize(url: str, out_path: str, min_duration: float) -> None:
    raw_path = out_path + ".raw.mp4"
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(raw_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    _normalize_and_loop(raw_path, out_path, min_duration)
    os.remove(raw_path)


def _fetch_from_pexels(topic: str, out_path: str, min_duration: float, api_key: str) -> str:
    resp = requests.get(
        PEXELS_SEARCH_URL,
        headers={"Authorization": api_key},
        params={"query": topic, "orientation": "portrait", "per_page": 15},
        timeout=20,
    )
    resp.raise_for_status()
    videos = resp.json().get("videos", [])
    if not videos:
        raise RuntimeError(f"no Pexels results for '{topic}'")

    random.shuffle(videos)
    for video in videos:
        files = [
            f for f in video.get("video_files", [])
            if f.get("width") and f.get("height") and f["height"] >= f["width"]
        ]
        if not files:
            continue
        files.sort(key=lambda f: f["width"], reverse=True)
        _download_and_normalize(files[0]["link"], out_path, min_duration)
        return out_path
    raise RuntimeError(f"no portrait video files among Pexels results for '{topic}'")


def _normalize_and_loop(src: str, out_path: str, min_duration: float) -> None:
    """Scale/crop to 1080x1920 and loop the clip until it covers min_duration."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", src],
        capture_output=True, text=True, check=True,
    )
    src_duration = float(probe.stdout.strip() or 1.0)
    loops = max(int(min_duration // src_duration) + 1, 1)

    vf = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H}"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-stream_loop", str(loops - 1), "-i", src,
            "-vf", vf, "-t", str(min_duration + 1),
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path,
        ],
        check=True, capture_output=True,
    )


def _generate_gradient_background(out_path: str, min_duration: float) -> str:
    """No API key fallback: a slow-panning two-color gradient."""
    duration = min_duration + 1
    # Rich two/three-colour palettes; dark enough for white text, not muddy.
    color1, color2, color3 = random.choice([
        ("0x1e3a8a", "0x7c3aed", "0x0f172a"),   # indigo -> violet
        ("0x0f766e", "0x1d4ed8", "0x0b1324"),   # teal -> blue
        ("0x9d174d", "0x6d28d9", "0x1a0b2e"),   # magenta -> purple
        ("0xb45309", "0xbe123c", "0x1c0a0a"),   # amber -> crimson
        ("0x047857", "0x0e7490", "0x05201a"),   # emerald -> cyan
    ])
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", (
                f"gradients=s={TARGET_W}x{TARGET_H}:c0={color1}:c1={color2}:c2={color3}"
                f":n=3:duration={duration}:speed=0.01"
            ),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", str(duration),
            out_path,
        ],
        check=True, capture_output=True,
    )
    return out_path


if __name__ == "__main__":
    import sys

    topic = sys.argv[1] if len(sys.argv) > 1 else "space"
    path = fetch_background_video(topic, "bg_test.mp4", 45)
    print(f"Wrote {path}")

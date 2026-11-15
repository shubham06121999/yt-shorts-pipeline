"""
Gets a vertical background video to narrate over.

With PIXABAY_API_KEY set: searches Pixabay for a stock clip matching the
topic (portrait preferred; landscape clips are center-cropped to vertical).

With PEXELS_API_KEY set (and Pixabay missing or failing): searches Pexels for
a vertical stock clip instead.

Without either key: generates a simple looping animated gradient with ffmpeg so
the pipeline still runs end-to-end.
"""
import os
import random
import subprocess

import requests

PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"
PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"
TARGET_W, TARGET_H = 1080, 1920


def fetch_background_video(topic: str, out_path: str, min_duration: float) -> str:
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
    color1 = random.choice(["0x1b2735", "0x2c1b35", "0x1b3528", "0x35251b"])
    color2 = random.choice(["0x3a4a5c", "0x4a2c5c", "0x2c5c3a", "0x5c3a2c"])
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", (
                f"gradients=s={TARGET_W}x{TARGET_H}:c0={color1}:c1={color2}"
                f":duration={duration}:speed=0.02"
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

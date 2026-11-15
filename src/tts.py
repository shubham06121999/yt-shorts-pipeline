"""
Text-to-speech using edge-tts (free, no API key, uses Microsoft Edge's
online neural voices). Produces an mp3 plus word-boundary timing data,
which captions.py uses for caption timing.
"""
import asyncio
import os
from dataclasses import dataclass
from typing import List, Tuple

DEFAULT_VOICE = os.environ.get("TTS_VOICE", "en-US-GuyNeural")
# Slightly faster than default reads as more energetic on Shorts.
DEFAULT_RATE = os.environ.get("TTS_RATE", "+8%")


@dataclass
class TTSResult:
    audio_path: str
    duration_seconds: float
    # (text_chunk, start_seconds, end_seconds) per input line
    line_timings: List[Tuple[str, float, float]]
    # (word, start_seconds, end_seconds) for every spoken word, in order.
    # Empty if the TTS service didn't return word timings.
    word_timings: List[Tuple[str, float, float]] = None


async def _synthesize(text_lines: List[str], out_path: str, voice: str) -> TTSResult:
    import edge_tts

    full_text = " ".join(text_lines)
    # edge-tts 7+ only emits sentence boundaries unless asked for words;
    # word timings are what keep captions in sync with the voice.
    communicate = edge_tts.Communicate(
        full_text, voice, rate=DEFAULT_RATE, boundary="WordBoundary"
    )

    word_boundaries = []
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_boundaries.append(chunk)

    if not word_boundaries:
        # Fallback: estimate duration from file size is unreliable for mp3,
        # so fall back to a words-per-minute estimate for timing only.
        total_words = len(full_text.split())
        est_duration = _probe_duration(out_path) or max(total_words / 2.5, 1.0)
        return TTSResult(out_path, est_duration, _even_split(text_lines, est_duration), [])

    last = word_boundaries[-1]
    spoken_end = (last["offset"] + last["duration"]) / 10_000_000  # 100ns units -> s
    # The mp3 has a little trailing silence; use its real length when available.
    duration = max(_probe_duration(out_path), spoken_end)

    words = [
        (b["text"], b["offset"] / 10_000_000, (b["offset"] + b["duration"]) / 10_000_000)
        for b in word_boundaries
    ]
    # Map word boundaries back onto the original lines in order.
    timings = _map_words_to_lines(text_lines, word_boundaries)
    return TTSResult(out_path, duration, timings, words)


def _probe_duration(path: str) -> float:
    import subprocess

    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True,
        )
        return float(probe.stdout.strip() or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def _even_split(lines: List[str], total_duration: float) -> List[Tuple[str, float, float]]:
    weights = [max(len(l), 1) for l in lines]
    total_w = sum(weights)
    out = []
    t = 0.0
    for line, w in zip(lines, weights):
        dur = total_duration * (w / total_w)
        out.append((line, t, t + dur))
        t += dur
    return out


def _map_words_to_lines(lines: List[str], word_boundaries: list) -> List[Tuple[str, float, float]]:
    """Walk the word-boundary stream and assign spans of it to each line
    in order, based on word counts."""
    out = []
    idx = 0
    for line in lines:
        n_words = max(len(line.split()), 1)
        chunk = word_boundaries[idx: idx + n_words]
        idx += n_words
        if not chunk:
            # Ran out of boundaries (shouldn't normally happen); pad with last end time.
            last_end = out[-1][2] if out else 0.0
            out.append((line, last_end, last_end + 1.0))
            continue
        start = chunk[0]["offset"] / 10_000_000
        end = (chunk[-1]["offset"] + chunk[-1]["duration"]) / 10_000_000
        out.append((line, start, end))
    return out


def text_to_speech(text_lines: List[str], out_path: str, voice: str = DEFAULT_VOICE) -> TTSResult:
    """Synchronous wrapper. text_lines are spoken in order, concatenated."""
    return asyncio.run(_synthesize(text_lines, out_path, voice))


if __name__ == "__main__":
    import sys

    lines = ["This is a test.", "Here is a second line.", "And a third one."]
    result = text_to_speech(lines, "test_audio.mp3")
    print(f"Duration: {result.duration_seconds:.2f}s")
    for line, start, end in result.line_timings:
        print(f"  [{start:5.2f}-{end:5.2f}] {line}")

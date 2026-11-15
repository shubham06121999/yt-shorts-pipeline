"""
Builds an SRT caption file from the TTS line timings, splitting long lines
into shorter on-screen chunks (good Shorts captions show ~3-6 words at a time).
"""
from typing import List, Tuple

MAX_WORDS_PER_CAPTION = 5


def _srt_timestamp(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    h, millis = divmod(millis, 3_600_000)
    m, millis = divmod(millis, 60_000)
    s, millis = divmod(millis, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{millis:03d}"


def build_srt(line_timings: List[Tuple[str, float, float]], out_path: str) -> str:
    """line_timings: list of (text, start_seconds, end_seconds), one per
    narration line (as produced by tts.text_to_speech)."""
    entries = []
    for text, start, end in line_timings:
        words = text.split()
        if not words:
            continue
        duration = max(end - start, 0.01)
        # split into chunks of MAX_WORDS_PER_CAPTION, proportional timing
        chunks = [
            words[i: i + MAX_WORDS_PER_CAPTION]
            for i in range(0, len(words), MAX_WORDS_PER_CAPTION)
        ]
        per_chunk = duration / len(chunks)
        t = start
        for chunk in chunks:
            entries.append((t, t + per_chunk, " ".join(chunk)))
            t += per_chunk

    with open(out_path, "w", encoding="utf-8") as f:
        for i, (start, end, text) in enumerate(entries, start=1):
            f.write(f"{i}\n")
            f.write(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n")
            f.write(f"{text}\n\n")
    return out_path


if __name__ == "__main__":
    sample = [("This is a test of the caption system", 0.0, 3.0),
              ("It should split into short readable chunks", 3.0, 6.5)]
    build_srt(sample, "captions_test.srt")
    print(open("captions_test.srt").read())

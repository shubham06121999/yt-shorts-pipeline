"""
Builds the on-screen text layer as an ASS subtitle file (rendered by
ffmpeg/libass in compose.py):

- Word-by-word captions: 1-3 big uppercase words at a time, the word being
  spoken highlighted in an accent colour, each group popping in.
- A title card at the top for the whole video.
- A "FACT 2/5" chip above the captions while each fact is read.
- A thin progress bar along the top edge.

Layout keeps text out of the areas the Shorts player covers (the bottom
~20% with the channel name/description, and the right-hand button column).

Fonts/colours are configurable from .env (see config.example.env). An SRT
writer is kept for anyone who wants a plain caption file.
"""
import os
from typing import List, Optional, Sequence, Tuple

W, H = 1080, 1920
MAX_WORDS_PER_GROUP = 3
# Keep each caption group on one line at the caption font size.
MAX_GROUP_CHARS = 14
# Break a caption group early when the speaker pauses longer than this.
PAUSE_BREAK_S = 0.35


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """'#RRGGBB' -> ASS '&HAABBGGRR' (alpha 0 = opaque, 255 = invisible)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ass_time(seconds: float) -> str:
    cs = int(round(max(seconds, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _group_words(words: Sequence[Tuple[str, float, float]], line_starts: List[float]):
    """Split word timings into short caption groups, breaking on punctuation,
    pauses, and narration-line boundaries."""
    groups, current = [], []
    line_idx = 0
    for i, (word, start, end) in enumerate(words):
        # Starting a new narration line forces a new group.
        new_line = False
        while line_idx + 1 < len(line_starts) and start >= line_starts[line_idx + 1] - 0.01:
            line_idx += 1
            new_line = True
        paused = bool(current) and start - current[-1][2] > PAUSE_BREAK_S
        too_long = sum(len(w) + 1 for w, _, _ in current) + len(word) > MAX_GROUP_CHARS
        if current and (new_line or paused or too_long or len(current) >= MAX_WORDS_PER_GROUP):
            groups.append(current)
            current = []
        current.append((word, start, end))
        if word[-1:] in ".,!?;:":
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def build_ass(
    word_timings: Sequence[Tuple[str, float, float]],
    line_timings: Sequence[Tuple[str, float, float]],
    title: str,
    line_labels: Sequence[Optional[str]],
    duration: float,
    out_path: str,
) -> str:
    """word_timings: (word, start, end) for each spoken word.
    line_timings: (text, start, end) per narration line.
    line_labels: chip text per narration line (e.g. "FACT 1/5") or None."""
    font = os.environ.get("CAPTION_FONT", "Arial Black")
    title_font = os.environ.get("TITLE_FONT", font)
    accent = os.environ.get("CAPTION_ACCENT", "#FFD60A")      # highlight / chip
    title_bg = os.environ.get("TITLE_BG", "#E63946")          # title card box

    white = _ass_color("#FFFFFF")
    black = _ass_color("#000000")
    shadow = _ass_color("#000000", 0x60)
    accent_c = _ass_color(accent)

    # Fall back to evenly timed words if TTS gave no word timings.
    if not word_timings:
        word_timings = []
        for text, start, end in line_timings:
            ws = text.split() or [""]
            step = max(end - start, 0.01) / len(ws)
            word_timings += [(w, start + k * step, start + (k + 1) * step) for k, w in enumerate(ws)]

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},106,{white},{white},{black},{shadow},-1,0,0,0,100,100,1,0,1,8,4,5,110,110,0,1
Style: Title,{title_font},60,{white},{white},{_ass_color(title_bg)},{shadow},-1,0,0,0,100,100,0,0,3,18,0,8,90,90,250,1
Style: Chip,{font},46,{black},{black},{accent_c},{shadow},-1,0,0,0,100,100,2,0,3,14,0,5,0,0,0,1
Style: Bar,Arial,10,{accent_c},{accent_c},{black},{black},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []

    # Progress bar: a full-width rectangle revealed left-to-right over the video.
    dur_ms = int(duration * 1000)
    bar = "m 0 0 l 1080 0 1080 14 0 14"
    events.append(
        f"Dialogue: 5,{_ass_time(0)},{_ass_time(duration)},Bar,,0,0,0,,"
        f"{{\\pos(0,0)\\clip(0,0,0,14)\\t(0,{dur_ms},\\clip(0,0,1080,14))\\p1}}{bar}{{\\p0}}"
    )

    # Title card: drops in at the start, stays for the whole video.
    events.append(
        f"Dialogue: 4,{_ass_time(0)},{_ass_time(duration)},Title,,0,0,0,,"
        f"{{\\fad(150,0)\\fscx70\\fscy70\\t(0,180,\\fscx104\\fscy104)\\t(180,280,\\fscx100\\fscy100)}}"
        f"{_escape(title.upper())}"
    )

    # Fact chips.
    for li, ((text, start, end), label) in enumerate(zip(line_timings, line_labels)):
        if not label:
            continue
        # Keep the chip up through the pause until the next line starts.
        if li + 1 < len(line_timings):
            end = max(end, line_timings[li + 1][1])
        events.append(
            f"Dialogue: 3,{_ass_time(start)},{_ass_time(end)},Chip,,0,0,0,,"
            f"{{\\pos(540,1010)\\fscx60\\fscy60\\t(0,120,\\fscx108\\fscy108)\\t(120,200,\\fscx100\\fscy100)}}"
            f" {_escape(label.upper())} "
        )

    # Word-by-word captions.
    groups = _group_words(word_timings, [s for _, s, _ in line_timings])
    for gi, group in enumerate(groups):
        g_start = group[0][1]
        g_end = group[-1][2] + 0.12
        if gi + 1 < len(groups):
            nxt = groups[gi + 1][0][1]
            # Hold the caption through pauses (incl. between sentences) so
            # the screen is never empty mid-video.
            g_end = nxt if nxt - g_end < 1.2 else g_end
        else:
            g_end = max(g_end, min(duration, g_end + 0.4))

        upper = [_escape(w.upper()) for w, _, _ in group]
        for wi, (_word, w_start, _w_end) in enumerate(group):
            ev_start = g_start if wi == 0 else w_start
            ev_end = group[wi + 1][1] if wi + 1 < len(group) else g_end
            if ev_end <= ev_start:
                continue
            parts = []
            for k, w in enumerate(upper):
                if k == wi:
                    parts.append(f"{{\\c{accent_c}&\\fscx110\\fscy110}}{w}{{\\c{white}&\\fscx100\\fscy100}}")
                else:
                    parts.append(w)
            # Pop-in only on the group's first event, so it doesn't re-animate per word.
            anim = "\\fscx80\\fscy80\\t(0,90,\\fscx100\\fscy100)" if wi == 0 else ""
            events.append(
                f"Dialogue: 2,{_ass_time(ev_start)},{_ass_time(ev_end)},Caption,,0,0,0,,"
                f"{{\\pos(540,1180){anim}}}{' '.join(parts)}"
            )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(events) + "\n")
    return out_path


# ---------------------------------------------------------------------------
# Plain SRT (not used by the default pipeline; handy for uploading captions
# separately to YouTube).

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

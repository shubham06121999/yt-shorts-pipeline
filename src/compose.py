"""
Merges the background video, narration, optional background music, and the
ASS text layer (captions/title/progress bar) into the final vertical
1080x1920 mp4.

Output is encoded the way YouTube recommends for upload: H.264 High
profile, 30 fps, BT.709 colour, closed GOPs, AAC 48 kHz stereo, moov atom
at the front (faststart), and audio loudness-normalised to about -14 LUFS
(what YouTube normalises playback to), so it can go straight to YouTube.
"""
import os
import random
import subprocess
from typing import Optional

W, H = 1080, 1920
FPS = 30
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"}


def _filter_path(path: str) -> str:
    """Escape a file path for use inside an ffmpeg filtergraph option."""
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def pick_music(music_dir: Optional[str] = None) -> Optional[str]:
    music_dir = music_dir or os.environ.get("MUSIC_DIR", "music")
    if not os.path.isdir(music_dir):
        return None
    tracks = [
        os.path.join(music_dir, f) for f in os.listdir(music_dir)
        if os.path.splitext(f)[1].lower() in AUDIO_EXTS and not f.startswith(".")
    ]
    return random.choice(tracks) if tracks else None


def compose_video(
    background_path: str,
    audio_path: str,
    ass_path: str,
    out_path: str,
    audio_duration: float,
    music_path: Optional[str] = None,
) -> str:
    total = audio_duration + 0.6  # small tail so the last word isn't clipped
    fade_out_start = max(total - 0.5, 0)

    # Background: slight zoom with a slow side-to-side drift (keeps static
    # clips/gradients from looking frozen), a mild grade, and a vignette so
    # white text stays readable on any footage.
    zoom_w, zoom_h = int(W * 1.12) // 2 * 2, int(H * 1.12) // 2 * 2
    fonts_dir = os.environ.get("FONTS_DIR", "fonts")
    subs = f"subtitles=filename='{_filter_path(ass_path)}'"
    if os.path.isdir(fonts_dir):
        subs += f":fontsdir='{_filter_path(os.path.abspath(fonts_dir))}'"

    video_chain = (
        f"[0:v]fps={FPS},scale={zoom_w}:{zoom_h}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H}:x='(iw-ow)/2+(iw-ow)/2*sin(t/7)':y='(ih-oh)/2',"
        f"eq=brightness=-0.02:contrast=1.05:saturation=1.15,"
        f"vignette=angle=PI/6,"
        f"{subs},"
        f"fade=t=out:st={fade_out_start:.2f}:d=0.5,"
        f"format=yuv420p,setsar=1[v]"
    )

    # Audio: narration (+ quiet looping music if provided), then loudness
    # normalisation to YouTube's playback target.
    if music_path:
        music_vol = os.environ.get("MUSIC_VOLUME", "0.10")
        audio_chain = (
            f"[1:a]aresample=48000,aformat=channel_layouts=stereo,apad[narr];"
            f"[2:a]aresample=48000,aformat=channel_layouts=stereo,volume={music_vol},"
            f"afade=t=in:d=1,afade=t=out:st={fade_out_start:.2f}:d=0.5[mus];"
            f"[narr][mus]amix=inputs=2:duration=first:normalize=0,"
            f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
        )
    else:
        audio_chain = (
            "[1:a]aresample=48000,aformat=channel_layouts=stereo,apad,"
            "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
        )

    cmd = ["ffmpeg", "-y", "-i", background_path, "-i", audio_path]
    if music_path:
        cmd += ["-stream_loop", "-1", "-i", music_path]
    cmd += [
        "-filter_complex", f"{video_chain};{audio_chain}",
        "-map", "[v]", "-map", "[a]",
        "-t", f"{total:.2f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-g", str(FPS * 2), "-bf", "2", "-flags", "+cgop",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"ffmpeg failed composing the video:\n{tail}")
    return out_path

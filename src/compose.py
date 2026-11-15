"""
Merges the background video, the narration audio, and the burned-in
captions into the final vertical (1080x1920) mp4 ready for upload.
"""
import os
import subprocess


def compose_video(
    background_path: str,
    audio_path: str,
    srt_path: str,
    out_path: str,
    audio_duration: float,
) -> str:
    # Escape the srt path for the ffmpeg filtergraph (colons/backslashes on
    # Windows paths need escaping; on posix this is usually a no-op).
    srt_escaped = srt_path.replace("\\", "\\\\").replace(":", "\\:")

    subtitles_style = (
        "FontName=Arial,FontSize=14,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=3,Outline=2,"
        "Alignment=2,MarginV=180"
    )

    vf = f"subtitles='{srt_escaped}':force_style='{subtitles_style}'"

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", background_path,
            "-i", audio_path,
            "-vf", vf,
            "-t", str(audio_duration),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            out_path,
        ],
        check=True, capture_output=True,
    )
    return out_path


if __name__ == "__main__":
    # Smoke test expects bg_test.mp4 / test_audio.mp3 / captions_test.srt
    # to already exist from running the other modules' __main__ blocks.
    compose_video("bg_test.mp4", "test_audio.mp3", "captions_test.srt", "final_test.mp4", 10)
    print("Wrote final_test.mp4")

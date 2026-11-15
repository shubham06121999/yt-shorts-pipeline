"""
End-to-end CLI: generate a script, narrate it, fetch a background,
burn captions, and compose the final video. By default this only saves
the finished mp4 to your local output folder - nothing is uploaded
anywhere unless you pass --upload.

Usage:
    python -m src.main --topic "space facts"
    python -m src.main --topic "space facts" --count 3
    python -m src.main --topic "space facts" --output-dir ~/Videos/shorts
    python -m src.main --topic "space facts" --upload --privacy unlisted
"""
import argparse
import os
import shutil
import sys
import tempfile
import time

from dotenv import load_dotenv

from . import captions, compose, script_gen, tts, visuals


def run_once(topic: str, args: argparse.Namespace, workdir: str) -> str:
    print(f"[main] Generating script for topic: {topic}")
    script = script_gen.generate_script(topic)
    print(f"[main] Title: {script.title}")

    audio_path = os.path.join(workdir, "narration.mp3")
    print("[main] Synthesizing narration...")
    tts_result = tts.text_to_speech(script.lines, audio_path)
    print(f"[main] Narration duration: {tts_result.duration_seconds:.1f}s")

    bg_path = os.path.join(workdir, "background.mp4")
    print("[main] Fetching background video...")
    visuals.fetch_background_video(topic, bg_path, tts_result.duration_seconds)

    srt_path = os.path.join(workdir, "captions.srt")
    print("[main] Building captions...")
    captions.build_srt(tts_result.line_timings, srt_path)

    final_path = os.path.join(workdir, "final.mp4")
    print("[main] Composing final video...")
    compose.compose_video(bg_path, audio_path, srt_path, final_path, tts_result.duration_seconds)

    out_dir = args.output_dir
    os.makedirs(out_dir, exist_ok=True)
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in script.title)[:60]
    dest_path = os.path.join(out_dir, f"{safe_title or topic}_{int(time.time())}.mp4")
    shutil.copy(final_path, dest_path)
    print(f"[main] Saved video to {dest_path}")

    if args.upload:
        # Imported lazily so the google-auth/google-api-python-client
        # packages are only required when you actually ask to upload.
        from . import upload

        description = (
            script.cta
            + "\n\n"
            + " ".join(f"#{t.replace(' ', '')}" for t in script.tags)
        )
        try:
            upload.upload_video(
                video_path=dest_path,
                title=script.title,
                description=description,
                tags=script.tags,
                privacy_status=args.privacy,
                category_id=os.environ.get("YOUTUBE_CATEGORY_ID", "27"),
            )
        except FileNotFoundError as exc:
            print(f"[main] Skipping upload: {exc}")
        except ImportError:
            print(
                "[main] --upload needs the upload extras installed: "
                "pip install -r requirements-upload.txt"
            )

    return dest_path


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Generate a facts/trivia short video and save it locally."
    )
    parser.add_argument("--topic", required=True, help="Topic/niche, e.g. 'space facts'")
    parser.add_argument("--count", type=int, default=1, help="How many videos to generate in this run")
    parser.add_argument(
        "--upload", action="store_true",
        help="Also upload to YouTube after saving locally (needs YouTube API setup - see README).",
    )
    parser.add_argument(
        "--privacy",
        default=os.environ.get("YOUTUBE_PRIVACY_STATUS", "private"),
        choices=["private", "unlisted", "public"],
        help="Only used with --upload.",
    )
    parser.add_argument("--output-dir", default="./output", help="Where to save finished mp4 files")
    args = parser.parse_args()

    for i in range(args.count):
        print(f"\n=== Video {i + 1}/{args.count} ===")
        with tempfile.TemporaryDirectory() as workdir:
            run_once(args.topic, args, workdir)


if __name__ == "__main__":
    main()

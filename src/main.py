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

Two-step workflow with your own images/videos per scene:
    python -m src.main --topic "ocean facts" --plan
        -> writes projects/<name>/script.json, shotlist.md and an empty media/
           folder. Make a visual for each scene (Google Flow, your photos...),
           save them as media/01.jpg, media/02.mp4, ... and edit script.json
           if you want to fix any wording or facts.
    python -m src.main --project projects/<name>
        -> renders the video from that script and media.
"""
import json
import re
import argparse
import os
import shutil
import sys
import tempfile
import time

from dotenv import load_dotenv

from . import captions, compose, script_gen, tts, visuals


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "video"


def write_plan(topic: str, projects_dir: str) -> str:
    """Generate a script and save it with a shot list for making visuals."""
    print(f"[main] Generating script for topic: {topic}")
    script = script_gen.generate_script(topic)
    project = os.path.join(projects_dir, f"{_slug(script.title)}_{time.strftime('%Y%m%d-%H%M%S')}")
    media = os.path.join(project, "media")
    os.makedirs(media, exist_ok=True)
    data = script.to_dict()
    data["topic"] = topic
    with open(os.path.join(project, "script.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    labels = ["Hook"] + [f"Fact {i}" for i in range(1, len(script.facts) + 1)] + ["Closing"]
    out = [f"# Shot list: {script.title}", "",
           f"Topic: {topic}", "",
           "Make one image or video clip per scene and save it in `media/` named by",
           "scene number: `01.jpg`, `02.mp4`, `03_anything.png` ... (jpg/png/webp or",
           "mp4/mov). Vertical 9:16 looks best; others are cropped to fit. Scenes",
           "without a file fall back to keyword matches in clips/, then a gradient.",
           "Video clips loop if shorter than the scene; images get a slow zoom.", "",
           "You can also edit `script.json` (wording, facts, prompts) before rendering.", ""]
    for i, (label, line, scene) in enumerate(zip(labels, script.lines, script.scenes), start=1):
        out += [f"## {i:02d}. {label}",
                f"**Narration:** {line}", "",
                f"**Prompt (Flow / image generator):** {scene['prompt']}", "",
                f"**Keywords:** {', '.join(scene['keywords'])}  ",
                f"**Save as:** `media/{i:02d}.mp4` or `media/{i:02d}.jpg`", ""]
    out += ["---", "When the media is in place, render with:", "",
            f"    venv/bin/python -m src.main --project \"{project}\"", ""]
    with open(os.path.join(project, "shotlist.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"[main] Title: {script.title}")
    print(f"[main] Plan saved to {project}/  (shotlist.md has a prompt per scene)")
    return project


def load_project(project: str):
    with open(os.path.join(project, "script.json"), encoding="utf-8") as f:
        data = json.load(f)
    return data.get("topic") or data["title"], script_gen.Script.from_dict(data)


def run_once(topic: str, args: argparse.Namespace, workdir: str, script=None, media_dir=None) -> str:
    if script is None:
        print(f"[main] Generating script for topic: {topic}")
        script = script_gen.generate_script(topic)
    print(f"[main] Title: {script.title}")

    audio_path = os.path.join(workdir, "narration.mp3")
    print("[main] Synthesizing narration...")
    tts_result = tts.text_to_speech(script.lines, audio_path)
    print(f"[main] Narration duration: {tts_result.duration_seconds:.1f}s")

    bg_path = os.path.join(workdir, "background.mp4")
    print("[main] Building background...")
    built = visuals.build_scene_background(
        script.scenes, tts_result.line_timings, tts_result.duration_seconds,
        topic, bg_path, media_dir=media_dir,
    )
    if not built:
        visuals.fetch_background_video(topic, bg_path, tts_result.duration_seconds)

    ass_path = os.path.join(workdir, "captions.ass")
    print("[main] Building captions and on-screen text...")
    n_facts = len(script.facts)
    labels = [None] + [f"Fact {i}/{n_facts}" for i in range(1, n_facts + 1)] + [None]
    captions.build_ass(
        tts_result.word_timings,
        tts_result.line_timings,
        script.title,
        labels,
        tts_result.duration_seconds + 0.6,
        ass_path,
    )

    music_path = compose.pick_music()
    if music_path:
        print(f"[main] Background music: {os.path.basename(music_path)}")

    final_path = os.path.join(workdir, "final.mp4")
    print("[main] Composing final video...")
    compose.compose_video(
        bg_path, audio_path, ass_path, final_path, tts_result.duration_seconds, music_path
    )

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
    parser.add_argument("--topic", help="Topic/niche, e.g. 'space facts'")
    parser.add_argument(
        "--plan", action="store_true",
        help="Only write the script + a shot list (one visual prompt per scene) to "
             "projects/<name>/ so you can add your own images/videos, then render with --project.",
    )
    parser.add_argument(
        "--project",
        help="Render from a folder made by --plan (uses its script.json and media/).",
    )
    parser.add_argument("--projects-dir", default="./projects", help="Where --plan saves projects")
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

    if args.project:
        topic, script = load_project(args.project)
        with tempfile.TemporaryDirectory() as workdir:
            run_once(topic, args, workdir, script=script,
                     media_dir=os.path.join(args.project, "media"))
        return
    if not args.topic:
        parser.error("--topic is required (or use --project)")
    if args.plan:
        for _ in range(args.count):
            write_plan(args.topic, args.projects_dir)
        return

    for i in range(args.count):
        print(f"\n=== Video {i + 1}/{args.count} ===")
        with tempfile.TemporaryDirectory() as workdir:
            run_once(args.topic, args, workdir)


if __name__ == "__main__":
    main()

"""
Generates the script for one short "facts/trivia" video:
a title, a hook line, a handful of facts, and a closing call-to-action.

Uses an AI model to write a fresh script each run - Claude when
ANTHROPIC_API_KEY is set, otherwise Google Gemini's free tier when
GEMINI_API_KEY is set. That's what keeps each video's content distinct
rather than templated, which matters for YouTube's monetization policy on
generic/repetitive AI content. Falls back to a small built-in generator otherwise, purely so the pipeline
is runnable end-to-end without any keys.
"""
import json
import os
import random
from dataclasses import dataclass, field
from typing import List

SYSTEM_PROMPT = """You write scripts for 40-55 second YouTube Shorts in the \
"quick facts" niche. Output ONLY valid JSON, no commentary, matching this \
shape:

{
  "title": "string, <=70 chars, punchy, no clickbait lies",
  "hook": "string, one sentence, said in the first 2 seconds to stop the scroll",
  "facts": ["string", "string", "string", "string", "string"],
  "cta": "string, one short closing line (e.g. asks a question or teases a follow)",
  "tags": ["string", "string", "..."],
  "scenes": [{"prompt": "string", "keywords": ["string", "string"]}, "..."]
}

Rules:
- 5 to 7 facts, each ONE sentence, each genuinely surprising or little-known,
  each verifiably true to the best of your knowledge (no invented stats).
- Facts must be concrete and specific, not generic filler.
- For mythology, folklore, religion or history, keep what the source text
  says separate from later tradition: if a detail comes from legend, folk
  retellings or popular belief rather than the primary source, say so in
  the sentence ("Legend says...", "According to tradition...", "Folk
  retellings say...") instead of stating it as fact.
- Plain spoken language - this gets read aloud by a text-to-speech voice.
- tags: 8-12 relevant single/double word YouTube tags, no hashtags.
- Do not repeat the same fact structure 3+ times in a row (vary the angle).
- scenes: exactly one per narration line, in order: hook, each fact, cta
  (so len(scenes) == len(facts) + 2). Each is the background visual shown
  while that line is spoken.
  - prompt: a text-to-video/image prompt (for Google Flow / Veo or an image
    generator) - 1-2 sentences describing a single concrete, filmable
    subject that illustrates the line, plus camera movement and lighting.
    Vertical 9:16 framing, photorealistic/cinematic, no text, no logos, no
    real people's faces.
  - keywords: 2-4 lowercase single words naming what's on screen (e.g.
    ["octopus", "reef", "underwater"]), used to match stock clip filenames.
"""


@dataclass
class Script:
    title: str
    hook: str
    facts: List[str]
    cta: str
    tags: List[str] = field(default_factory=list)
    # One per narration line (hook, facts..., cta):
    # {"prompt": str, "keywords": [str, ...]}
    scenes: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title, "hook": self.hook, "facts": list(self.facts),
            "cta": self.cta, "tags": list(self.tags), "scenes": list(self.scenes),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Script":
        script = cls(
            title=str(data["title"]).strip(),
            hook=str(data["hook"]).strip(),
            facts=[str(f).strip() for f in data["facts"] if str(f).strip()],
            cta=str(data["cta"]).strip(),
            tags=[str(t).strip() for t in data.get("tags", []) if str(t).strip()],
            scenes=list(data.get("scenes") or []),
        )
        script.scenes = _normalize_scenes(script)
        return script

    @property
    def full_text(self) -> str:
        """The complete narration text, in speaking order."""
        parts = [self.hook, *self.facts, self.cta]
        return " ".join(p.strip() for p in parts if p.strip())

    @property
    def lines(self) -> List[str]:
        """Narration split into caption-sized chunks, in order."""
        return [self.hook, *self.facts, self.cta]


_SCENE_STOPWORDS = {
    "about", "there", "their", "which", "would", "could", "these", "those", "than",
    "that", "this", "with", "from", "into", "your", "have", "made", "here", "facts",
    "sound", "entire", "likely", "tell", "most", "surprised", "comments", "called",
}


def _keywords_for(text: str, limit: int = 3) -> List[str]:
    words = "".join(c.lower() if c.isalpha() else " " for c in text).split()
    picked = []
    for w in sorted(set(words), key=lambda w: (-len(w), w)):
        if len(w) > 3 and w not in _SCENE_STOPWORDS:
            picked.append(w)
        if len(picked) >= limit:
            break
    return picked


def _normalize_scenes(script: "Script") -> List[dict]:
    """Make sure there's exactly one well-formed scene per narration line,
    filling gaps with a prompt/keywords derived from the line itself."""
    lines = script.lines
    raw = script.scenes if isinstance(script.scenes, list) else []
    out = []
    for i, line in enumerate(lines):
        scene = raw[i] if i < len(raw) and isinstance(raw[i], dict) else {}
        prompt = str(scene.get("prompt") or "").strip() or (
            f"Cinematic vertical 9:16 shot illustrating: {line} Slow camera push-in, "
            f"dramatic lighting, photorealistic, no text."
        )
        keywords = [str(k).strip().lower() for k in (scene.get("keywords") or []) if str(k).strip()]
        out.append({"prompt": prompt, "keywords": keywords or _keywords_for(line)})
    return out


def _fallback_script(topic: str) -> Script:
    """A small offline generator so the pipeline runs with zero API keys.
    Replace with a real ANTHROPIC_API_KEY for actual content - this fallback
    is intentionally generic and should not be used for a real channel."""
    pool = {
        "space": [
            "A day on Venus is longer than its entire year.",
            "Neutron stars can spin over 600 times per second.",
            "There is a planet made largely of exposed diamond, called 55 Cancri e.",
            "The footprints on the Moon will likely last millions of years.",
            "Saturn's moon Titan has rivers and lakes made of liquid methane.",
        ],
        "ocean": [
            "We have mapped more of Mars than of our own ocean floor.",
            "The blue whale's heart alone can weigh as much as a small car.",
            "Some jellyfish species can revert back to a juvenile polyp stage.",
            "The deepest part of the ocean is taller than Mount Everest is tall, if flipped.",
            "Octopuses have three hearts and blue blood.",
        ],
    }
    subject = " ".join(w for w in topic.split() if w.lower() not in {"facts", "fact", "trivia"}) or topic
    facts = list(pool.get(subject.lower(), pool["space"]))
    random.shuffle(facts)
    script = Script(
        title=f"{subject.title()} Facts That Sound Fake (But Aren't)",
        hook=f"Here are {len(facts)} facts about {subject.lower()} that sound made up.",
        facts=facts,
        cta="Which one surprised you most? Tell me in the comments.",
        tags=[topic, "facts", "shorts", "trivia", "did you know"],
    )
    script.scenes = _normalize_scenes(script)
    return script


SCRIPT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "hook": {"type": "string"},
        "facts": {"type": "array", "items": {"type": "string"}, "minItems": 5, "maxItems": 7},
        "cta": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["prompt", "keywords"],
            },
        },
    },
    "required": ["title", "hook", "facts", "cta", "tags", "scenes"],
}


def _parse_script(raw_text: str) -> Script:
    """Turn the model's JSON reply into a Script, tolerating ```json fences."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    data = json.loads(text)
    script = Script.from_dict(data)
    if len(script.facts) < 3:
        raise ValueError(f"only {len(script.facts)} facts returned")
    if not (script.title and script.hook and script.cta):
        raise ValueError("title/hook/cta missing")
    script.facts = script.facts[:7]
    script.scenes = _normalize_scenes(script)
    return script


def _generate_with_anthropic(topic: str, api_key: str) -> Script:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    response = client.messages.create(
        model=model,
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Topic/niche for this video: {topic}"}],
    )
    raw_text = "".join(block.text for block in response.content if block.type == "text")
    script = _parse_script(raw_text)
    print(f"[script_gen] Script written by Claude ({model})")
    return script


# Tried in order after GEMINI_MODEL when a model is overloaded (503) or
# rate-limited (429) - common on the free tier at busy times.
# gemini-3.5-flash: best-quality model on the free tier (as of Nov 2026).
# Lite models are faster and rarely overloaded, so they make good backups.
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_BACKUP_MODELS = ["gemini-flash-lite-latest", "gemini-3.5-flash-lite"]
GEMINI_TIMEOUT_MS = 30_000


def _generate_with_gemini(topic: str, api_key: str) -> Script:
    """Free option: Google Gemini API free tier (key from aistudio.google.com)."""
    from google import genai
    from google.genai import types
    import logging

    # Newer models return "thought" parts; the SDK warns about them on every call.
    logging.getLogger("google_genai.types").setLevel(logging.ERROR)

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS))
    primary = os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
    models = [primary] + [m for m in GEMINI_BACKUP_MODELS if m != primary]
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=1.0,
        response_mime_type="application/json",
        response_json_schema=SCRIPT_JSON_SCHEMA,
    )
    contents = (
        f"Topic/niche for this video: {topic}\n"
        # Nudge variety so repeated runs on one topic don't reuse the same facts.
        f"Variation seed: {random.randint(1000, 9999)} - pick less obvious facts."
    )

    last_exc = None
    for model in models:
        for attempt in range(1):  # one try per model; backups are fast
            try:
                response = client.models.generate_content(model=model, contents=contents, config=config)
                # Join text parts directly (newer models also return "thought" parts).
                parts = response.candidates[0].content.parts if response.candidates else []
                raw = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))
                script = _parse_script(raw)
                print(f"[script_gen] Script written by Gemini ({model})")
                return script
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                text = str(exc)
                busy = type(exc).__name__ == "ServerError" or any(
                    code in text for code in ("429", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED")
                )
                timed_out = "timed out" in text.lower() or "timeout" in type(exc).__name__.lower()
                if "NOT_FOUND" in text or "404" in text:
                    print(f"[script_gen] Gemini {model} not available to this key; trying next model")
                    break
                if not (busy or timed_out or isinstance(exc, (ValueError, KeyError))):
                    raise  # e.g. bad key - no point trying other models
                reason = "busy" if busy else "timed out" if timed_out else "bad reply"
                print(f"[script_gen] Gemini {model} {reason}; trying next model")
    raise RuntimeError(f"all Gemini models failed; last error: {last_exc}")


def generate_script(topic: str) -> Script:
    """Generate a Script for the given topic/niche.

    Tries Claude (ANTHROPIC_API_KEY), then Gemini's free tier
    (GEMINI_API_KEY), then the small built-in fallback."""
    writers = [
        ("Claude", "ANTHROPIC_API_KEY", _generate_with_anthropic),
        ("Gemini", "GEMINI_API_KEY", _generate_with_gemini),
    ]
    for name, env_var, writer in writers:
        api_key = os.environ.get(env_var)
        if not api_key:
            continue
        try:
            return writer(topic, api_key)
        except Exception as exc:  # noqa: BLE001 - surfaced to the log
            msg = str(exc).replace(api_key, "***")[:300]
            print(f"[script_gen] {name} failed ({type(exc).__name__}: {msg}); trying next option.")
    print("[script_gen] No AI key set (or all failed) - using the built-in facts.")
    return _fallback_script(topic)


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    load_dotenv()

    s = generate_script(sys.argv[1] if len(sys.argv) > 1 else "space")
    print(json.dumps(s.to_dict(), indent=2))

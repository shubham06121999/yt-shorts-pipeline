"""
Generates the script for one short "facts/trivia" video:
a title, a hook line, a handful of facts, and a closing call-to-action.

Uses the Anthropic API when ANTHROPIC_API_KEY is set (recommended - this
is what keeps each video's content distinct rather than templated, which
matters for YouTube's monetization policy on generic/repetitive AI content).
Falls back to a small built-in generator otherwise, purely so the pipeline
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
  "tags": ["string", "string", "..."]
}

Rules:
- 5 to 7 facts, each ONE sentence, each genuinely surprising or little-known,
  each verifiably true to the best of your knowledge (no invented stats).
- Facts must be concrete and specific, not generic filler.
- Plain spoken language - this gets read aloud by a text-to-speech voice.
- tags: 8-12 relevant single/double word YouTube tags, no hashtags.
- Do not repeat the same fact structure 3+ times in a row (vary the angle).
"""


@dataclass
class Script:
    title: str
    hook: str
    facts: List[str]
    cta: str
    tags: List[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """The complete narration text, in speaking order."""
        parts = [self.hook, *self.facts, self.cta]
        return " ".join(p.strip() for p in parts if p.strip())

    @property
    def lines(self) -> List[str]:
        """Narration split into caption-sized chunks, in order."""
        return [self.hook, *self.facts, self.cta]


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
    facts = pool.get(topic.lower(), pool["space"])
    random.shuffle(facts)
    return Script(
        title=f"{topic.title()} Facts That Sound Fake (But Aren't)",
        hook=f"Here are {len(facts)} facts about {topic} that sound made up.",
        facts=facts,
        cta="Which one surprised you most? Tell me in the comments.",
        tags=[topic, "facts", "shorts", "trivia", "did you know"],
    )


def generate_script(topic: str) -> Script:
    """Generate a Script for the given topic/niche."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_script(topic)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Topic/niche for this video: {topic}",
                }
            ],
        )
        raw_text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        data = json.loads(raw_text)
        return Script(
            title=data["title"],
            hook=data["hook"],
            facts=list(data["facts"]),
            cta=data["cta"],
            tags=list(data.get("tags", [])),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller/log
        print(f"[script_gen] Anthropic generation failed ({exc}); using fallback.")
        return _fallback_script(topic)


if __name__ == "__main__":
    import sys

    s = generate_script(sys.argv[1] if len(sys.argv) > 1 else "space")
    print(json.dumps(s.__dict__, indent=2))

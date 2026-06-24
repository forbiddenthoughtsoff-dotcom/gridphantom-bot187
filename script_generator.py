import os
import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

VISUAL_CONSTANT = ("3D animated style, Pixar-like character design, vibrant colors, "
                   "cinematic lighting, depth of field, 9:16 aspect ratio")

SYSTEM_PROMPT = """You are an autonomous chief screenwriter and prompt engineer for viral YouTube Shorts, specialized in timely niche content with viral potential.

Analyze the provided story, psychologically optimize it, and produce an exact production script with consistent image prompts.

Follow these 3 stages strictly:

1. RETENTION PSYCHOLOGY
- Hook (0-3s): Simultaneous audio, text and visual hook. No intro, no greeting. Direct entry at the moment of maximum curiosity/tension.
- Body: Short, universally understandable sentences. Each line describes one clear visual action. Fast pacing, 0% filler.
- Reward: The emotional or shocking payoff sits exactly at the end of the last line.

2. CHARACTER CONSISTENCY
- Identify the core characters up front. Keep their specific traits (clothing, hair, age) IDENTICAL across all scene prompts.

3. STRUCTURE
- Strict 1:1 mapping: 1 script line (voiceover) = 1 visual scene = 1 precise image prompt.

Output ONLY valid JSON in this exact structure (no markdown, no code blocks):
{
  "title": "Viral title with emoji (max 60 chars)",
  "thumbnail_text": "3-5 word on-screen hook",
  "characters": "Brief description of recurring characters and their fixed traits",
  "scenes": [
    {
      "segment": "hook",
      "voiceover": "Opening line in English, max 12 words",
      "image_prompt": "full image prompt including character details and action",
      "onscreen_text": "short punchy on-screen text"
    }
  ],
  "tags": ["shorts", "ai", "tech", "viral", "trending", "gridphantom"]
}

Produce 5-7 scenes total. Each voiceover line max 12 words. Always start the image_prompt with the visual style constant.
"""


def _sanitize_json(raw: str) -> str:
    raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
    raw = raw.strip()
    start = raw.find('{')
    end = raw.rfind('}') + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    return raw


class ScriptGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    def generate(self, topic: dict, language: str = 'en') -> dict:
        user_prompt = f"""Process this raw material into a viral Short script:

Title: {topic.get('title', '')}
Summary: {topic.get('summary', '')}

Create 5-7 scenes with 1:1 voiceover-to-scene mapping. Consistent characters across all scenes.
Each image_prompt must begin with: "{VISUAL_CONSTANT}".
Return ONLY valid JSON."""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=3000,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"}
                    }
                ],
                messages=[{"role": "user", "content": user_prompt}]
            )

            raw = message.content[0].text
            try:
                script = json.loads(raw)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error, sanitizing: {e}")
                script = json.loads(_sanitize_json(raw))

            # Ensure every image prompt starts with the visual constant
            for scene in script.get('scenes', []):
                ip = scene.get('image_prompt', '')
                if not ip.startswith("3D animated"):
                    scene['image_prompt'] = f"{VISUAL_CONSTANT}, {ip}"

            # Build a single narration string from all voiceover lines
            script['narration'] = " ".join(
                s.get('voiceover', '') for s in script.get('scenes', [])
            )
            script['language'] = language
            script['source_topic'] = topic
            logger.info(f"Script generated: {script.get('title','?')} "
                        f"({len(script.get('scenes', []))} scenes)")
            return script

        except Exception as e:
            logger.error(f"Script generation error: {e}")
            raise

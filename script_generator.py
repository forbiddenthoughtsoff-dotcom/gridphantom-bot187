import os
import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a viral short-form content creator. You create shocking, fascinating facts and stories for YouTube Shorts.

Your content style:
- ONE powerful fact or story, told in 3-5 short punchy sentences
- Each sentence max 10 words
- Hook in the first sentence — shocking or unbelievable
- No fluff, no intro, no "did you know"
- Direct, fast, memorable

Also generate a vivid image prompt for an AI image that visually matches the topic.
The image should look like a real, cinematic, dramatic photo or painting — NOT cartoon, NOT Pixar.
Example topics: historical figures, athletes, celebrities, shocking world facts, science, money, power

Output ONLY valid JSON, no markdown:
{
  "title": "Catchy title with emoji (max 60 chars)",
  "image_prompt": "Cinematic, photorealistic, dramatic image of [subject]. High detail, moody lighting, 9:16 portrait format. NO cartoon, NO animation.",
  "sentences": ["sentence 1", "sentence 2", "sentence 3", "sentence 4", "sentence 5"],
  "tags": ["shorts", "facts", "viral", "trending", "didyouknow", "gridphantom"]
}"""


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
        user_prompt = f"""Create a viral short about this topic:
Title: {topic.get('title', '')}
Summary: {topic.get('summary', '')}

Make it shocking and fascinating. 3-5 sentences max 10 words each.
Return ONLY valid JSON."""

        message = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_prompt}]
        )

        raw = message.content[0].text
        try:
            script = json.loads(raw)
        except json.JSONDecodeError:
            script = json.loads(_sanitize_json(raw))

        # Build narration from sentences
        script['narration'] = " ".join(script.get('sentences', []))
        script['language'] = language
        script['source_topic'] = topic
        logger.info(f"Script: {script.get('title','?')} ({len(script.get('sentences',[]))} sentences)")
        return script

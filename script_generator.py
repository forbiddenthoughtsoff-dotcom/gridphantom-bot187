import os
import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a viral short-form content creator for YouTube Shorts and Instagram Reels.

Your style:
- Shocking, fascinating, or controversial facts about real people, history, science, money, or power
- ONE topic per video — deep, not broad
- 4-6 sentences max, each under 12 words
- Hook sentence first: shocking or unbelievable, makes people stop scrolling
- No filler, no "did you know", no intro
- Fast, punchy, direct

For the background image: always generate a beautiful AI woman — attractive, stylish, confident. 
The woman should visually match the topic mood (mysterious, powerful, playful, elegant).
Photorealistic, cinematic lighting, portrait 9:16. No nudity, no explicit content.

Output ONLY valid JSON, no markdown, no code blocks:
{
  "title": "Punchy title with emoji (max 60 chars)",
  "image_prompt": "Beautiful attractive woman, [mood matching topic], cinematic lighting, photorealistic, portrait 9:16, high detail",
  "sentences": ["hook sentence max 12 words", "sentence 2", "sentence 3", "sentence 4"],
  "tags": ["shorts", "facts", "viral", "trending", "gridphantom"]
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
        user_prompt = f"""Create a viral YouTube Short about:
Title: {topic.get('title', '')}
Summary: {topic.get('summary', '')}

Rules:
- 4-6 sentences, each max 12 words
- First sentence must be shocking hook
- English only
- Return ONLY valid JSON"""

        message = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_prompt}]
        )

        raw = message.content[0].text
        try:
            script = json.loads(raw)
        except json.JSONDecodeError:
            script = json.loads(_sanitize_json(raw))

        script['narration'] = " ".join(script.get('sentences', []))
        script['language'] = 'en'  # Always English
        script['source_topic'] = topic
        logger.info(f"Script: {script.get('title','?')} ({len(script.get('sentences',[]))} sentences)")
        return script

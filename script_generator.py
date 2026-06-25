import os
import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a viral content creator for YouTube Shorts. Your videos feature a recurring AI woman character with powerful quotes and hard truths that stop men from scrolling.

Content style:
- Bold, provocative quotes about life, success, money, relationships, or power
- The kind of truth that hits hard and makes people share
- 3-5 short punchy sentences, each MAX 8 WORDS
- First sentence is the hook — stops scroll instantly
- Tone: confident, raw, real — like a beautiful woman telling hard truths
- ALWAYS ENGLISH. Never German, never any other language.

IMPORTANT — the background image is ALWAYS the same recurring character:
A beautiful young woman, around 20 years old, long blonde hair, slim figure, stunning gorgeous face, blue eyes, flawless skin. Only the setting, pose, outfit, and mood change between videos — the woman herself stays the same.

For the image_prompt: always start with the exact character description, then vary the scene/mood to match the quote. ALWAYS end with these quality keywords: "cinematic Hollywood lighting, shot on ARRI Alexa, 85mm lens, shallow depth of field, professional color grading, ultra photorealistic, 8k, magazine cover quality".

Output ONLY valid JSON, no markdown:
{
  "title": "Short punchy title with emoji (max 55 chars, English only)",
  "image_prompt": "Beautiful young woman around 20 years old, long blonde hair, slim figure, stunning gorgeous face, blue eyes, flawless skin, [scene/outfit/mood matching quote], cinematic Hollywood lighting, shot on ARRI Alexa, 85mm lens, shallow depth of field, professional color grading, ultra photorealistic, 8k, magazine cover quality",
  "sentences": ["hook", "sentence 2", "sentence 3", "sentence 4"],
  "tags": ["shorts", "viral", "motivation", "mindset", "gridphantom"]
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

    def generate(self, topic: dict = None, language: str = 'en') -> dict:
        mode = os.environ.get('VIDEO_MODE', 'long')
        if mode == 'short':
            count = "2-3 sentences — ultra short, under 20 seconds when spoken"
        else:
            count = "4-6 sentences — 45-60 seconds when spoken"

        user_prompt = f"""Create a viral YouTube Short with a powerful quote.
Generate {count}. Each sentence MAX 8 WORDS.
Bold, confident quotes — what a stunning woman says that stops men scrolling.
First sentence is the hook. Make it hit hard.
ENGLISH ONLY. Return ONLY valid JSON."""

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
        script['language'] = 'en'
        logger.info(f"Script: {script.get('title','?')} ({len(script.get('sentences',[]))} sentences)")
        return script

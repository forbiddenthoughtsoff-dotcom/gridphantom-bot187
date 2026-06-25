import os
import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a viral content creator for YouTube Shorts. Your videos feature stunning AI women with powerful quotes and hard truths that stop men from scrolling.

Your content style:
- Bold, provocative quotes about life, success, money, relationships, or power
- The kind of truth that hits hard and makes people share
- 3-5 short punchy sentences, each max 10 words
- First sentence must be a hook that stops the scroll instantly
- Tone: confident, raw, real — like a beautiful woman telling hard truths
- Examples: "A real man never chases. He attracts." / "The wrong people always leave at the right time." / "Your silence is your power. Use it."

For the background image: generate a stunningly beautiful, attractive AI woman.
She should look confident, mysterious, or seductive — matching the mood of the quote.
Photorealistic, cinematic studio lighting, sharp detail, portrait 9:16.

Output ONLY valid JSON, no markdown:
{
  "title": "Short punchy title with emoji (max 55 chars)",
  "image_prompt": "Stunning beautiful woman, [specific look: e.g. dark hair, intense eyes, elegant dress], cinematic lighting, photorealistic, sharp detail, 9:16 portrait, high quality",
  "sentences": ["hook sentence", "sentence 2", "sentence 3", "sentence 4"],
  "tags": ["shorts", "viral", "motivation", "facts", "mindset", "gridphantom"]
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
        user_prompt = f"""Create a viral YouTube Short with a powerful quote or hard truth.
Topic inspiration: {topic.get('title', 'life, success, relationships, power')}

Generate original bold quotes — not news, not facts.
The kind of thing a confident, beautiful woman would say.
3-5 sentences, each max 10 words. First sentence stops the scroll.
Return ONLY valid JSON."""

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

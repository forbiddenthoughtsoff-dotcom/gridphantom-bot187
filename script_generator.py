import os
import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

SHORT_PROMPT = """You are an expert YouTube Shorts script writer for a viral tech channel called GridPhantom.
CRITICAL RULES:
- Maximum 15 WORDS total narration — one single shocking sentence
- No intro, no outro, just the punch
- CRITICAL: Output raw valid JSON only. No markdown. No code blocks.
Output this exact JSON structure:
{
  "title": "Viral title with emoji (max 60 chars)",
  "thumbnail_text": "3-4 words MAX",
  "thumbnail_keyword": "2-3 word stock video keyword",
  "narration": "ONE shocking sentence, maximum 15 words.",
  "tags": ["shorts", "ai", "tech", "viral", "trending", "gridphantom"]
}"""

LONG_PROMPT = """You are an expert YouTube script writer for a tech channel called GridPhantom.
CRITICAL RULES:
- Narration: 300-400 words (2-3 minutes when read aloud)
- Engaging hook intro, 2-3 clear main points, strong CTA outro
- CRITICAL: Output raw valid JSON only. No markdown. No code blocks.
Output this exact JSON structure:
{
  "title": "Engaging title with emoji (max 60 chars)",
  "thumbnail_text": "4-5 word thumbnail text",
  "thumbnail_keyword": "2-3 word stock video keyword",
  "narration": "300-400 words. Hook, main points, CTA.",
  "tags": ["ai", "tech", "technews", "artificialintelligence", "technology", "gridphantom"]
}"""


def _sanitize_json(raw: str) -> str:
    raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
    raw = raw.strip()
    start = raw.find('{')
    end = raw.rfind('}') + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    raw = re.sub(r'(")\s*\n(\s*")', r'\1,\n\2', raw)
    raw = re.sub(r'(})\s*\n(\s*")', r'\1,\n\2', raw)
    raw = re.sub(r'(])\s*\n(\s*")', r'\1,\n\2', raw)
    return raw


class ScriptGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    def generate(self, topic: dict, language: str) -> dict:
        mode = os.environ.get('VIDEO_MODE', 'short')
        system = LONG_PROMPT if mode == 'long' else SHORT_PROMPT
        max_tok = 2000 if mode == 'long' else 500
        lang_name = "German" if language == 'de' else "English"

        if mode == 'short':
            user_prompt = f"""Create a VIRAL YouTube Short script in {lang_name} about:
Title: {topic.get('title', '')}
ONE shocking sentence, maximum 15 words. Return ONLY valid JSON."""
        else:
            user_prompt = f"""Create a YouTube video script in {lang_name} about:
Title: {topic.get('title', '')}
Summary: {topic.get('summary', '')}
300-400 words, engaging and informative. Return ONLY valid JSON."""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tok,
                system=[
                    {
                        "type": "text",
                        "text": system,
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
                sanitized = _sanitize_json(raw)
                script = json.loads(sanitized)

            script['language'] = language
            script['source_topic'] = topic
            logger.info(f"Script generated: {script.get('title', 'Unknown')}")
            return script

        except Exception as e:
            logger.error(f"Script generation error: {e}")
            raise

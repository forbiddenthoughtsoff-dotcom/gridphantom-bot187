import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert YouTube Shorts script writer for a viral tech channel called GridPhantom.

Create PUNCHY, viral YouTube Shorts scripts about AI and technology.

CRITICAL RULES:
- Maximum 60 words total narration (this is a SHORT, not a long video)
- Hook must be in the FIRST 3 seconds — shocking, controversial or surprising fact
- Fast-paced, energetic tone
- End with a cliffhanger or call to action
- CRITICAL: Output raw valid JSON only. No markdown. No code blocks.

Output this exact JSON structure:
{
  "title": "Viral YouTube Shorts title with emoji (max 60 chars)",
  "thumbnail_text": "3-4 words MAX for thumbnail",
  "thumbnail_keyword": "2-3 word keyword for stock video search",
  "narration": "MAXIMUM 60 WORDS. Hook in first sentence. Fast, punchy, shocking.",
  "tags": ["shorts", "ai", "tech", "viral", "tag4", "tag5"]
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
        lang_name = "German" if language == 'de' else "English"
        user_prompt = f"""Create a VIRAL YouTube Shorts script in {lang_name} about:
Title: {topic.get('title', '')}
Summary: {topic.get('summary', '')}

MAXIMUM 60 WORDS for narration. Make it SHOCKING and VIRAL.
Return ONLY valid JSON. No markdown. No code blocks."""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )

            raw = message.content[0].text

            try:
                script = json.loads(raw)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error, sanitizing: {e}")
                sanitized = _sanitize_json(raw)
                try:
                    script = json.loads(sanitized)
                except json.JSONDecodeError as e2:
                    logger.error(f"JSON sanitization failed: {e2}")
                    raise

            script['language'] = language
            script['source_topic'] = topic
            logger.info(f"Script generated: {script.get('title', 'Unknown')}")
            return script

        except Exception as e:
            logger.error(f"Script generation error: {e}")
            raise

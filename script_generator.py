import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert YouTube script writer for a tech channel called GridPhantom.
Create engaging, informative scripts about AI and technology topics.

CRITICAL: Output raw valid JSON only. No markdown formatting. No code blocks.
Ensure ALL array elements and key-value pairs are strictly comma-separated.
Do NOT wrap output in ```json or ``` blocks. Return ONLY the JSON object.

Output this exact JSON structure:
{
  "title": "YouTube video title (max 60 chars)",
  "thumbnail_text": "Short punchy text for thumbnail (max 6 words)",
  "thumbnail_keyword": "2-3 word keyword for stock video search",
  "narration": "Full narration script (8-10 minutes when read aloud at normal pace)",
  "chapters": [
    {"title": "Chapter title", "start_time": "0:00"},
    {"title": "Chapter title", "start_time": "1:30"}
  ],
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}"""


def _sanitize_json(raw: str) -> str:
    """Pre-process LLM output to fix common JSON formatting errors."""
    # Remove markdown code blocks
    raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
    raw = raw.strip()

    # Extract JSON object between first { and last }
    start = raw.find('{')
    end = raw.rfind('}') + 1
    if start != -1 and end > start:
        raw = raw[start:end]

    # Fix missing commas between string values on adjacent lines:
    # "value"\n  "key" → "value",\n  "key"
    raw = re.sub(r'(")\s*\n(\s*")', r'\1,\n\2', raw)
    # Fix missing commas between } and "
    raw = re.sub(r'(})\s*\n(\s*")', r'\1,\n\2', raw)
    # Fix missing commas between ] and "
    raw = re.sub(r'(])\s*\n(\s*")', r'\1,\n\2', raw)

    return raw


class ScriptGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    def generate(self, topic: dict, language: str) -> dict:
        lang_name = "German" if language == 'de' else "English"
        user_prompt = f"""Create a YouTube script in {lang_name} about this topic:
Title: {topic.get('title', '')}
Summary: {topic.get('summary', '')}

The script should be engaging for a tech-savvy audience interested in AI and technology.
Make the narration 2-3 minutes when read at a normal pace (400-500 words maximum).
CRITICAL: Return ONLY valid JSON. No markdown. No code blocks."""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )

            raw = message.content[0].text

            # Try direct parse first
            try:
                script = json.loads(raw)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error, attempting sanitization: {e}")
                sanitized = _sanitize_json(raw)
                try:
                    script = json.loads(sanitized)
                except json.JSONDecodeError as e2:
                    logger.error(f"JSON sanitization failed: {e2}")
                    logger.error(f"Raw output (first 500 chars): {raw[:500]}")
                    raise

            script['language'] = language
            script['source_topic'] = topic
            logger.info(f"Script generated: {script.get('title', 'Unknown')}")
            return script

        except Exception as e:
            logger.error(f"Script generation error: {e}")
            raise

import anthropic
import json
import logging
from config import Config

logger = logging.getLogger(__name__)

class ScriptGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    def generate(self, topic: dict, language: str) -> dict:
        """Generate a full YouTube script from a trending topic"""

        lang_name = "English" if language == 'en' else "German"
        lang_instruction = "Write everything in English." if language == 'en' else "Schreibe alles auf Deutsch."

        prompt = f"""You are a viral YouTube scriptwriter specializing in AI & Tech content.

Topic: {topic['title']}
Background: {topic['summary']}

{lang_instruction}

Create a complete YouTube video script that:
- Is 8-10 minutes when read aloud (approximately 1200-1500 words)
- Has a hook in the first 15 seconds that stops scrolling
- Uses simple, engaging language anyone can understand
- Builds tension and curiosity throughout
- Has a strong call-to-action at the end

Return ONLY valid JSON in this exact format:
{{
    "title": "YouTube video title (max 70 chars, SEO optimized, no clickbait)",
    "description": "YouTube description (300-500 chars with keywords)",
    "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"],
    "thumbnail_text": "Short punchy text for thumbnail (max 5 words)",
    "thumbnail_keyword": "One word for thumbnail background image search",
    "narration": "Full narration script here...",
    "chapters": [
        {{"time": "0:00", "title": "Chapter name"}},
        {{"time": "1:30", "title": "Chapter name"}}
    ]
}}"""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )

            raw = message.content[0].text
            # Clean potential markdown
            raw = raw.replace('```json', '').replace('```', '').strip()

            # Try direct parse first
            try:
                script = json.loads(raw)
            except json.JSONDecodeError:
                # Extract JSON block between first { and last }
                start = raw.find('{')
                end = raw.rfind('}') + 1
                if start != -1 and end > start:
                    raw = raw[start:end]
                # Replace problematic characters in narration field only
                import re
                def fix_json_string(m):
                    return m.group(0).replace('\n', '\\n').replace('\t', '\\t')
                raw = re.sub(r'"narration"\s*:\s*"(.*?)"(?=\s*,\s*"chapters")', fix_json_string, raw, flags=re.DOTALL)
                script = json.loads(raw)

            script['language'] = language
            script['source_topic'] = topic

            logger.info(f"Script generated: {script['title']}")
            return script

        except Exception as e:
            logger.error(f"Script generation error: {e}")
            raise

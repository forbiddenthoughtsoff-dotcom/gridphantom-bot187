import os
import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a viral content creator for a faceless YouTube Shorts channel about AI and technology news.

Content style:
- Punchy, factual takes on the given trending tech topic
- The kind of insight that makes viewers stop scrolling and share
- Short crisp sentences, each MAX 10 WORDS
- First sentence is the hook — it must stop the scroll instantly
- Tone: confident, sharp, informative — no hype, no fluff
- Write ONLY in the requested language

For image_prompt: describe a cinematic, abstract tech visual matching the topic (circuit boards, data centers, glowing interfaces, futuristic cityscapes — NO people, NO faces). Always end with: "cinematic lighting, ultra detailed, photorealistic, 8k".

Output ONLY valid JSON, no markdown:
{
  "title": "Short punchy title with emoji (max 55 chars, in the requested language)",
  "image_prompt": "abstract tech visual description, cinematic lighting, ultra detailed, photorealistic, 8k",
  "sentences": ["Hook", "Sentence 2", "Sentence 3"],
  "tags": ["shorts", "ai", "tech", "technews", "gridphantom"]
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
        mode = os.environ.get('VIDEO_MODE', 'short')
        if mode == 'short':
            count = "2-3 sentences — ultra short, under 20 seconds spoken"
        else:
            count = "4-6 sentences — 45-60 seconds spoken"

        lang_name = {'en': 'ENGLISH', 'de': 'GERMAN'}.get(language, 'ENGLISH')
        topic_title = (topic or {}).get('title', 'the latest AI and tech news')
        topic_summary = (topic or {}).get('summary', '')

        user_prompt = f"""Create a viral YouTube Short about this trending tech topic:

TOPIC: {topic_title}
{f"CONTEXT: {topic_summary}" if topic_summary else ""}

Generate {count}. Each sentence MAX 10 WORDS.
First sentence is the hook. Make it impossible to scroll past.
Language: {lang_name} ONLY. Output ONLY valid JSON."""

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
        script['language'] = language
        logger.info(f"Script [{language}]: {script.get('title','?')} ({len(script.get('sentences',[]))} sentences)")
        return script

import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the content brain of a German YouTube Shorts channel about hidden AI superpowers — little-known capabilities of AI tools like Claude, ChatGPT, Gemini and Perplexity that become possible with clever, targeted prompts.

EVERY VIDEO = EXACTLY ONE little-known, concretely useful capability or prompt trick. The vibe (do NOT reuse these verbatim): turning a whiteboard photo into a working Excel sheet, rehearsing a salary negotiation with AI as the tough boss, making Claude build an interactive app from one sentence, XML-structured prompts, letting AI clone your writing style, analyzing whole contracts/PDFs for traps.

RULES:
- The trick must be REAL and work today — NEVER invent capabilities
- Pick tricks most people genuinely don't know — not "KI kann E-Mails schreiben"
- Hook first: sentence 1 creates an information gap the viewer NEEDS closed
- Short punchy sentences, each MAX 10 WORDS
- Sentence flow: 1) HOOK, 2) the capability in concrete terms, 3) payoff — and point to the ready-to-copy prompt in the description
- Tone: insider revealing a secret — never clickbait that underdelivers
- Write ONLY in the requested language

TITLE RULES (80% of the click decision):
- Max 55 chars, German, front-load the power words, ONE emoji max
- Numbers, power words (geheim, versteckt, niemand, endlich, krass) or curiosity gaps
- Never generic

DESCRIPTION RULES (decides WHO the algorithm shows the video to):
- 8-10 sentences, 200-280 words, German (longer descriptions rank higher on YouTube)
- Sentence 1: re-hook with exact keywords people search ("Claude PDF", "AI Verhandlung", etc.)
- Sentences 2-3: what the trick does concretely + real example / actual use case
- Sentence 4: WHY this matters / specific benefit to viewer (saves time, money, frustration)
- Sentences 5-7: step-by-step breakdown (3-5 actionable steps)
- THEN the ready-to-copy prompt on its own line, introduced with: 👉 Prompt zum Kopieren:
- Next: Name the audience explicitly ("Wenn du ChatGPT oder Claude nutzt, ...")
- Last sentence: engaging question that provokes comments + reply

pexels_query: ENGLISH 2-4 word stock-footage search query matching the topic visually (e.g. "laptop typing dark", "smartphone screen closeup", "office meeting")

TAGS: 12-15 — German search phrases first ("ki tricks", "chatgpt tipps deutsch", "claude ai deutsch", "prompt tipps"), then international ones (chatgpt, claude, prompts, ai)

For image_prompt: cinematic, dramatic abstract tech visual matching the topic (glowing interfaces, dark screens, neon — NO people, NO faces). Always end with: "dramatic cinematic lighting, high contrast, ultra detailed, photorealistic, 8k".

Output ONLY valid JSON, no markdown:
{
  "title": "German power title, max 55 chars",
  "description": "8-10 sentence, 200-280 word German SEO description following the DESCRIPTION RULES, with keywords, example, benefit, steps, and copy-paste prompt",
  "image_prompt": "dramatic abstract tech visual, dramatic cinematic lighting, high contrast, ultra detailed, photorealistic, 8k",
  "pexels_query": "english stock footage query",
  "sentences": ["Hook", "Satz 2", "Satz 3"],
  "tags": ["ki tricks", "chatgpt tipps deutsch", "..."]
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

    def generate(self, language: str = 'de', avoid_titles: list = None) -> dict:
        lang_name = {'en': 'ENGLISH', 'de': 'GERMAN'}.get(language, 'GERMAN')

        user_prompt = f"""Create today's video: pick EXACTLY ONE little-known AI capability or prompt trick that makes viewers think "das wusste ich nicht!".

2-3 sentences — ultra short, under 20 seconds spoken. Each sentence MAX 10 WORDS.
The description MUST contain the ready-to-copy prompt.
Language: {lang_name} ONLY. Output ONLY valid JSON."""

        if avoid_titles:
            published = "\n".join(f"- {t}" for t in avoid_titles[:15])
            user_prompt += f"""

ALREADY PUBLISHED on this channel (NEVER repeat these tricks, angles or titles):
{published}

Pick a genuinely DIFFERENT trick — a new tool feature, a new use case, a new prompt technique. Never re-tell the same one."""

        # Haiku: 3x cheaper than Sonnet, plenty for 3-sentence scripts
        message = self.client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1400,
            system=SYSTEM_PROMPT,
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

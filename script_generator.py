import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an elite viral content strategist for a faceless YouTube Shorts channel about AI and technology news. Your scripts consistently hit millions of views because you understand viral psychology.

VIRAL HOOK FORMULAS (first sentence MUST use one):
- Shock stat: "This AI just replaced 10,000 jobs overnight."
- Curiosity gap: "Nobody noticed what Apple just quietly did."
- Stakes: "This changes everything about your phone."
- Controversy: "Everyone is wrong about this AI update."
- Urgency: "This disappears in 48 hours."

VIRAL RULES:
- Hook must create an information gap the viewer NEEDS closed
- Every sentence earns the next second of watch time
- Use concrete numbers over vague claims (numbers stop scrolls)
- End with a payoff or open loop that drives comments
- Short punchy sentences, each MAX 10 WORDS
- Tone: confident insider revealing something big — never clickbait that underdelivers, the topic must back the hook
- Write ONLY in the requested language

TITLE RULES (this is 80% of the click decision):
- Max 55 chars, front-load the most powerful words
- Use ONE emoji maximum, placed for emphasis
- Numbers, power words (secret, banned, insane, finally, nobody), or curiosity gaps
- Never generic ("Tech News Today" = death)

DESCRIPTION RULES (this decides WHO the algorithm shows the video to):
- 5-7 sentences, 120-180 words, written for search AND for the viewer
- Sentence 1: re-hook with the main keywords people would type into YouTube
- Sentences 2-4: context packed with concrete searchable terms (product names, company names, numbers, "2026")
- Sentence 5: name the target audience explicitly ("If you follow AI news / tech trends / gadget releases, ...")
- Last sentence: a question that provokes comments
- Natural language, no keyword-stuffing gibberish

TAGS: 12-15 tags — 3 broad viral (shorts, viral, tech), 6+ topic-specific (e.g. openai, chatgpt, iphone 17), and 3+ audience search phrases people actually type ("ai news today", "tech news 2026", "latest tech gadgets").

For image_prompt: cinematic, dramatic abstract tech visual matching the topic's emotion (glowing circuits, dark server halls, neon interfaces, futuristic skylines — NO people, NO faces). Always end with: "dramatic cinematic lighting, high contrast, ultra detailed, photorealistic, 8k".

Output ONLY valid JSON, no markdown:
{
  "title": "Front-loaded power title, max 55 chars, in the requested language",
  "description": "5-7 sentence SEO description following the DESCRIPTION RULES, 120-180 words, in the requested language.",
  "image_prompt": "dramatic abstract tech visual, dramatic cinematic lighting, high contrast, ultra detailed, photorealistic, 8k",
  "sentences": ["Hook", "Sentence 2", "Sentence 3"],
  "tags": ["shorts", "viral", "tech", "ai", "topic-specific-tag-1", "topic-specific-tag-2", "topic-specific-tag-3", "gridphantom"]
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

    def generate(self, topic: dict = None, language: str = 'en',
                 avoid_titles: list = None) -> dict:
        count = "2-3 sentences — ultra short, under 20 seconds spoken"
        lang_name = {'en': 'ENGLISH', 'de': 'GERMAN'}.get(language, 'ENGLISH')
        topic_title = (topic or {}).get('title', 'the latest AI and tech news')
        topic_summary = (topic or {}).get('summary', '')

        user_prompt = f"""Create a MAXIMALLY VIRAL YouTube Short about this trending tech topic:

TOPIC: {topic_title}
{f"CONTEXT: {topic_summary}" if topic_summary else ""}

Generate {count}. Each sentence MAX 10 WORDS.
Pick the most viral-worthy angle of this topic — the angle that makes people share it.
First sentence: use a VIRAL HOOK FORMULA. Make scrolling past impossible.
Last sentence: payoff or open loop that provokes comments.
Language: {lang_name} ONLY. Output ONLY valid JSON."""

        if avoid_titles:
            published = "\n".join(f"- {t}" for t in avoid_titles[:15])
            user_prompt += f"""

ALREADY PUBLISHED on this channel (NEVER repeat these angles, hooks or titles):
{published}

If the topic overlaps with any of these, you MUST find a genuinely DIFFERENT angle: new facts, a new perspective, a new consequence, a new question — like telling the next chapter of a story, never re-telling the same one."""

        # Haiku: 3x cheaper than Sonnet, plenty for 3-sentence scripts.
        # No cache_control: runs are hours apart, the 5-min cache never
        # hits, so the 25% write premium was pure waste.
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

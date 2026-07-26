# -*- coding: utf-8 -*-
import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the content brain of a German YouTube Shorts channel all about GTA — Grand Theft Auto V, GTA Online and the upcoming GTA VI. The channel serves German-speaking GTA players with tips, facts, tricks, help and myth-busting.

EVERY VIDEO = EXACTLY ONE focused, genuinely useful or genuinely interesting piece of GTA content. Pick ONE content type per video from these pillars:
- TRICK/TIPP: a concrete in-game trick for GTA Online (money-making method, faster missions, hidden mechanic, quality-of-life setting, defensive trick vs griefers)
- FAKT/TRIVIA: a little-known, verifiable fact about GTA V / GTA Online (easter eggs, map secrets, dev details, world records, lore)
- HILFE/HOW-TO: solving a common player problem (how to avoid being kicked, how to change appearance, how to start a business, how to leave a bad lobby)
- FAILS/SITUATIONEN: a relatable funny GTA moment described entertainingly (the classic ways players die, griefer situations) — described generically, never claiming it's a specific real clip
- MYTHOS ENTLARVT / FAKE NEWS EXPOSED: debunk a well-known GTA myth or a common false rumor (Bigfoot, Mount Chiliad UFO, ghost of Mount Gordo, "GTA VI map leaks", fake money-glitch scams)
- GTA VI: only EVERGREEN, officially-confirmed basics (setting is Vice City, two protagonists Lucia & Jason, published by Rockstar) — framed as general knowledge, never as "breaking news"

ACCURACY IS SACRED (this channel's credibility depends on it):
- You may be given a list of REAL, CURRENT news headlines fetched live from news sources. When you make a NEWS/UPDATE video, ground it STRICTLY in those provided headlines — never add facts, numbers or dates that are not in the provided text.
- If NO news list is provided, do NOT invent news, dates, prices, patch numbers or "just announced" claims. Then pick an evergreen pillar (trick, fact, help, myth-bust).
- CRUCIAL — distinguish confirmed from rumor: if a headline is an official Rockstar announcement, you may state it as fact. If it is an insider claim, leak, speculation or "soll/angeblich/Gerücht", you MUST frame it clearly as a rumor ("laut Gerüchten", "ein Insider behauptet", "noch nicht offiziell bestätigt"). NEVER present a rumor as confirmed fact.
- For GTA VI officially-confirmed basics (Vice City, Lucia & Jason, Rockstar) you may always state as fact.
- When the video IS about debunking, that's the safe zone: say clearly "das ist ein Mythos / das stimmt nicht" and why.

HOOK (sentence 1 — decides if they stay past second 2):
- State the surprising RESULT or the payoff, not the topic. Bad: "Heute geht's um GTA Online Geld." Good: "Mit diesem Verkaufstrick verlierst du nie wieder deine Ware an Griefer."
- Concrete, specific, a little provocative. A real curiosity gap.

VOICE & TONE (this is spoken out loud — write for the EAR):
- Natural, spoken German — like a fellow player explaining something to a friend, casual and confident. Gamer-vibe, but clear.
- Contractions and flow ("das ist", "geht's", "kannst du"). Never stiff, never corporate.
- Vary sentence length for rhythm. Write full, grammatical German sentences — length follows meaning, never an arbitrary word cap.
- No empty hype ("unglaublich/krass" as filler). Let the actual tip or fact carry it.
- Sentence flow: 1) HOOK, 2) the concrete tip/fact/how it works, 3) payoff + a nudge to the description or a comment prompt.
- Write ONLY in the requested language.
- CHARACTER RULE, nothing more: NEVER use the character "ß" — always write "ss" instead (Strasse not Straße, weiss not weiß, heisst not heißt). This applies to title, narration, description, tags — everything. IMPORTANT: this changes ONLY that one character. The language itself stays STANDARD HIGH GERMAN (Hochdeutsch) — absolutely NO Swiss German dialect, no "Grüezi", no Helvetisms, no dialect vocabulary.

TITLE RULES (80% of the click decision):
- Max 55 chars, German, front-load the power words, ONE emoji max
- Include "GTA" and where it fits "GTA 5", "GTA Online" or "GTA 6" — that's what people search
- Numbers, power words (geheim, versteckt, niemand, endlich, Trick, Mythos) or curiosity gaps
- RUMOR TITLES: if the video is based on a rumor/leak/insider claim (not officially confirmed), the TITLE ITSELF must carry a rumor marker — "angeblich", "Gerücht", "soll", or a question mark ("Trailer 3 am 6. August?"). NEVER state a rumor as fact in the title. This rule outranks catchiness.
- Never generic

DESCRIPTION RULES (decides WHO the algorithm shows the video to):
- 8-10 sentences, 200-280 words, German (longer descriptions rank higher on YouTube)
- Sentence 1: re-hook with exact keywords people search ("GTA Online Geld verdienen", "GTA 5 Trick", "GTA 6 Release", etc.)
- Sentences 2-3: explain the tip/fact/myth concretely with the exact in-game names (business, mission, location, vehicle)
- Sentence 4: WHY it matters to the player (more money, less griefing, saves time, wins arguments)
- Sentences 5-7: step-by-step breakdown where it applies (3-5 actionable steps), OR the clear truth if it's a myth-bust
- Then: name the audience ("Egal ob du GTA 5 auf PS5, Xbox oder PC zockst, ...")
- Last sentence: an engaging question that provokes comments (e.g. "Welchen GTA-Mythos sollen wir als Nächstes checken?")

pexels_query: ENGLISH 3-5 word stock-footage query for a GAMING-VIBE background (real GTA footage is NOT available on stock sites, so evoke the mood). Examples: "gaming controller neon light", "night city street driving", "person gaming at night", "arcade neon lights", "sports car city night", "gamer setup rgb". Pick one that matches the video's mood (money trick → luxury car / cash vibe; myth → dark foggy mountain; help → focused gamer at screen).

TAGS: 12-15 — German + GTA search phrases first ("gta online geld verdienen", "gta 5 tricks deutsch", "gta 6 news deutsch", "gta online tipps", "gta 5 mythen"), then broader ones (gta, gta 5, gta online, gta 6, rockstar, gaming deutsch)

For image_prompt: cinematic gaming-city visual matching the topic (neon-lit night city, luxury sports car, dramatic skyline — NO real GTA logos or copyrighted characters). Always end with: "dramatic cinematic lighting, high contrast, ultra detailed, 8k".

Output ONLY valid JSON, no markdown:
{
  "title": "German GTA power title with GTA keyword, max 55 chars",
  "description": "8-10 sentence, 200-280 word German SEO description following the DESCRIPTION RULES",
  "image_prompt": "cinematic neon night city or luxury car visual, dramatic cinematic lighting, high contrast, ultra detailed, 8k",
  "pexels_query": "english gaming-vibe stock footage query",
  "sentences": ["Hook", "Satz 2", "Satz 3"],
  "tags": ["gta online geld verdienen", "gta 5 tricks deutsch", "..."]
}"""


def _swissify(obj):
    """Swiss spelling: replace ß with ss in every string, recursively.
    Hard guarantee — applies even if the model ignores the prompt rule."""
    if isinstance(obj, str):
        return obj.replace('ß', 'ss')
    if isinstance(obj, list):
        return [_swissify(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _swissify(v) for k, v in obj.items()}
    return obj


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

    def generate(self, language: str = 'de', avoid_titles: list = None,
                 news_items: list = None) -> dict:
        lang_name = {'en': 'ENGLISH', 'de': 'GERMAN'}.get(language, 'GERMAN')

        user_prompt = f"""Create today's video: pick EXACTLY ONE GTA topic that makes a GTA player think "das muss ich wissen!".

3 full, natural German sentences, ~20-30 seconds spoken. Write for the EAR: proper sentence structure, varied rhythm, the way a fellow player would actually say it out loud. Hook = the surprising result or payoff.
Language: {lang_name} ONLY. Output ONLY valid JSON."""

        if news_items:
            news_block = "\n".join(
                f"- [{n.get('published','')}] {n.get('title','')}"
                f" (Quelle: {n.get('source','?')})"
                for n in news_items[:8])
            user_prompt += f"""

REAL CURRENT GTA NEWS (fetched live today — this is your factual ground truth):
{news_block}

Decide: if ONE of these headlines is genuinely newsworthy and fits a Short (a real update, announcement, or noteworthy development), make a NEWS/UPDATE video grounded STRICTLY in that headline — do not add facts beyond it, and clearly mark anything that is a rumor/leak/insider claim as such (not as confirmed fact). Otherwise, if none is strong enough, make an evergreen video instead (trick, fact, help, or myth-bust). Never fabricate details not present in the headline."""
        else:
            user_prompt += """

No live news available right now — make an EVERGREEN video (trick, fact, help, or myth-bust). Do NOT invent news, dates or announcements."""

        if avoid_titles:
            published = "\n".join(f"- {t}" for t in avoid_titles[:15])
            user_prompt += f"""

ALREADY PUBLISHED on this channel (NEVER repeat these topics, angles or titles):
{published}

Pick a genuinely DIFFERENT GTA topic — a new trick, a new fact, a different myth, another content pillar. Never re-tell the same one."""

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

        script = _swissify(script)
        script['narration'] = " ".join(script.get('sentences', []))
        script['language'] = language
        logger.info(f"Script [{language}]: {script.get('title','?')} ({len(script.get('sentences',[]))} sentences)")
        return script

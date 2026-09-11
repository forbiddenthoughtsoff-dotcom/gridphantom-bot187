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
- WOCHEN-UPDATE (GTA Online): when the news list contains Rockstar's weekly GTA Online update (usually Thursday: bonuses, double money/RP, podium vehicle, discounts, new content, event weeks), make THE weekly briefing: what pays this week, what to grab, what is new — grounded strictly in the headlines
- GLITCHES: a currently reported GTA Online glitch or exploit ONLY when it is in the news list — describe what it does and that it can be patched any time; never money-glitch scams, never anything that risks a ban without saying so
- OUTFITS & STYLE: how to build a striking GTA Online outfit or a well-known "modded-look" legitimately — which store/clothing pieces, masks, how to combine them, how to save the outfit
- RARE ITEMS RANKING: the rarest / most sought-after vehicles, clothing pieces, masks, liveries or collectibles in GTA Online and how (or if) they can still be obtained — verifiable, no invented statistics
Mix these pillars across the day so the channel never feels repetitive; the audience should always get something new they can use, laugh at, or brag about.

ACCURACY IS SACRED (this channel's credibility depends on it):
- You may be given a list of REAL, CURRENT news headlines fetched live from news sources. When you make a NEWS/UPDATE video, ground it STRICTLY in those provided headlines — never add facts, numbers or dates that are not in the provided text.
- If NO news list is provided, do NOT invent news, dates, prices, patch numbers or "just announced" claims. Then pick an evergreen pillar (trick, fact, help, myth-bust).
- CRUCIAL — distinguish confirmed from rumor: if a headline is an official Rockstar announcement, you may state it as fact. If it is an insider claim, leak, speculation or "soll/angeblich/Gerücht", you MUST frame it clearly as a rumor ("laut Gerüchten", "ein Insider behauptet", "noch nicht offiziell bestätigt"). NEVER present a rumor as confirmed fact.
- For GTA VI officially-confirmed basics (Vice City, Lucia & Jason, Rockstar) you may always state as fact.
- When the video IS about debunking, that's the safe zone: say clearly "das ist ein Mythos / das stimmt nicht" and why.

HOOK (sentence 1 — decides if they stay past second 2):
- State the surprising RESULT or the payoff, not the topic. Bad: "Heute geht's um GTA Online Geld." Good: "Mit diesem Verkaufstrick verlierst du nie wieder deine Ware an Griefer."
- Concrete, specific, a little provocative. A real curiosity gap.
- MAX 10 WORDS. Never start with "Heute", "Wusstest du", "In diesem Video", "Hallo" or the channel name. A number or a hard claim in the first 5 words wins.
- Second sentence must already deliver the first concrete piece of the payoff — no "aber dazu gleich mehr" stalling.

AUDIENCE (measured with YouTube Analytics, September 2026): 90 % male, 32 % aged 25-34, 30 % aged 35-44, 11 % 45-54; only 8 % teenagers. Germany 78 %, Austria 10 %, Switzerland 5 %. Working adults who grew up with GTA: write for a 30-year-old, not a schoolkid — no youth slang, no "Bro", respect their time and intelligence, money/efficiency angles and "was Rockstar wirklich gesagt hat" beat memes. Nostalgia (San Andreas, GTA 4, Vice City) resonates.
RETENTION FACT: the average viewer currently leaves after 15 seconds (51 % of a Short). The first concrete payoff must land BEFORE second 8, the second before second 15; nothing important after second 25 unless the video is a series episode.

PSYCHOLOGY PLAYBOOK (why people stay, replay, comment — use every one, never lie):
- OPEN LOOP in the first 2 seconds: promise a specific payoff that only the LAST third delivers ("das Dritte kennt fast niemand", "der letzte Punkt entscheidet"). The viewer stays to close the loop. The payoff MUST be delivered.
- LOSS beats gain: "kostet dich", "verlierst du", "machst du falsch" outperforms "so verdienst du mehr". Frame the first sentence as a loss or a mistake where truthful.
- SPECIFICITY = credibility: exact numbers, names, places, dates (digits). "250.000 Dollar" not "viel Geld".
- PATTERN INTERRUPT every 5-7 seconds: a new fact, an "aber", a question, a reversal. No two consecutive sentences with the same structure.
- IDENTITY: address the viewer as part of the tribe ("wenn du seit Tag 1 dabei bist", "jeder echte Grinder weiss") — inclusive, never insulting.
- SOCIAL PROOF only when true ("Millionen Spieler machen genau diesen Fehler" only if it is genuinely common).
- ENDING = BINARY QUESTION: the last line asks an either/or the viewer can answer in two words ("Team Bunker oder Team Nightclub?", "Lucia oder Jason?"). Comments are the strongest ranking signal a small channel can trigger.
- ZEIGARNIK for series/episodes: name what the next episode reveals in one concrete, tempting clause.
- TITLE: number or power word in the first 3 words (Fehler, niemand, geheim, verboten, kostenlos, endlich, sofort), max 45 characters before any emoji, the promise must match the video.

RETENTION & LOOP (Shorts are ranked on watch-through and replays):
- Regular videos: 4-6 sentences, 55-85 words — about 25 to 35 seconds. Every sentence must add a new fact, step or twist; cut anything that only repeats.
- The LAST sentence is short (max 12 words) and snaps back to the hook — a punchline, a twist, or the comment question — so the Short loops naturally. NEVER "Danke fürs Zuschauen", never "das war's".
- In the last third, ONE natural subscribe reason tied to a benefit, max 9 words, e.g. "Abonnieren, hier gibt's jeden Tag die GTA 6 News." Not a plea, a promise.

VOICE & TONE (this is spoken out loud — write for the EAR):
- Natural, spoken German — like a fellow player explaining something to a friend, casual and confident. Gamer-vibe, but clear.
- Contractions and flow ("das ist", "geht's", "kannst du"). Never stiff, never corporate.
- Vary sentence length for rhythm. Write full, grammatical German sentences — length follows meaning, never an arbitrary word cap.
- No empty hype ("unglaublich/krass" as filler). Let the actual tip or fact carry it.
- Sentence flow: 1) HOOK, 2) the concrete tip/fact/how it works, 3) payoff + a nudge to the description or a comment prompt.
- PUNCTUATE FOR THE VOICE: the narration is read by a TTS engine whose prosody follows punctuation. Use commas for natural micro-pauses, a question here and there, an em-dash or ellipsis before a payoff — this is what makes the voice sound human instead of robotic. Avoid abbreviations and unit mashups in the narration where a written-out word sounds better ("sechzig FPS" statt "60fps"). Years, dates and prices stay digits everywhere ("2026", "19. November 2026", "84,99 Euro") — the voice reads them correctly, and spelled-out years have produced wrong years.
- PROOFREAD: the output must be flawless German — zero spelling, grammar or punctuation errors in title, narration, description and tags. Read your own output once before answering.
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

TAGS: 12-15 — German + GTA search phrases first ("gta online geld verdienen", "gta 5 tricks deutsch", "gta 6 news deutsch", "gta online tipps", "gta 5 mythen"), then broader ones (gta, gta 5, gta online, gta 6, rockstar, gaming deutsch)

For image_prompt: cinematic gaming-city visual matching the topic (neon-lit night city, luxury sports car, dramatic skyline — NO real GTA logos or copyrighted characters). Always end with: "dramatic cinematic lighting, high contrast, ultra detailed, 8k".

Output ONLY valid JSON, no markdown:
{
  "title": "German GTA power title with GTA keyword, max 55 chars",
  "description": "8-10 sentence, 200-280 word German SEO description following the DESCRIPTION RULES",
  "image_prompt": "cinematic neon night city or luxury car visual, dramatic cinematic lighting, high contrast, ultra detailed, 8k",
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


_GENERIC = {
    'gta', 'gta5', 'gta6', 'online', 'shorts', 'short', 'rockstar', 'games',
    'der', 'die', 'das', 'und', 'oder', 'mit', 'für', 'fuer', 'von', 'vom',
    'im', 'in', 'am', 'an', 'auf', 'aus', 'ist', 'sind', 'hat', 'wird',
    'du', 'dir', 'dich', 'dein', 'deine', 'deinen', 'so', 'ein', 'eine',
    'einen', 'einem', 'einer', 'dem', 'den', 'des', 'nicht', 'mehr', 'kein',
    'keine', 'keinen', 'aber', 'wie', 'was', 'warum', 'wer', 'wann', 'wo',
    'jetzt', 'neu', 'neue', 'neuer', 'neues', 'alle', 'alles', 'noch', 'nur',
    'ps5', 'xbox', 'kannst', 'kann', 'koennen', 'können', 'sollte', 'musst',
    'machen', 'macht', 'diese', 'dieser', 'dieses', 'diesen', 'trick',
    'tricks', 'tipp', 'tipps', 'fakten', 'fakt', 'geheim', 'wirklich',
    'endlich', 'offiziell', 'bestätigt', 'sofort', 'besser', 'grosse',
    'grosser', 'grosses', 'komplett', 'niemand', 'jeder', 'darum', 'deshalb',
    'ganz', 'sehr', 'viel', 'viele', 'wenig', 'schon', 'nie', 'immer',
}


def _keywords(title: str) -> set:
    import re
    low = str(title).lower()
    t = re.sub(r'[^\wäöü ]+', ' ', low)
    words = {w for w in t.split() if len(w) >= 4 and w not in _GENERIC
             and not w.isdigit()}
    if re.search(r'gta\s*6\s*online|gta\s*vi\s*online', low):
        words.add('gta6online')  # the subject itself, not just "online"
    return words


def too_similar(title: str, recent_titles: list) -> bool:
    """True when the new title shares its subject with a recently published
    one: two distinctive words in common, or one distinctive word of five or
    more letters (e.g. "Angeln", "Jagen"). A false positive only costs one
    regeneration."""
    k = _keywords(title)
    if not k:
        return False
    for r in recent_titles[:25]:
        shared = k & _keywords(r)
        if len(shared) >= 2 or any(len(w) >= 5 for w in shared):
            return True
    return False


class ScriptGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    def generate(self, language: str = 'de', avoid_titles: list = None,
                 news_items: list = None, top_performers: list = None,
                 topic_brief: str = None, brief_style: str = 'deep') -> dict:
        lang_name = {'en': 'ENGLISH', 'de': 'GERMAN'}.get(language, 'GERMAN')

        if topic_brief and brief_style == 'short':
            # Trend topic in the PROVEN winner format: every 900+ view video
            # on this channel is a 21-32 second single-fact Short. A hot
            # topic does not change that — it gets the same tight treatment.
            user_prompt = f"""TODAY'S ASSIGNED TOPIC — the video MUST be about exactly this, nothing else:

{topic_brief}

Write it in the channel's WINNING format: 4 to 6 full, natural German sentences, 55-85 words in total (~25-35 seconds spoken). ONE concrete core fact, hook first, binary question last. Use ONLY the facts given above; label rumours as rumours. Digits for years, dates, prices. Write for the EAR.
Language: {lang_name} ONLY. Output ONLY valid JSON."""
        elif topic_brief:
            # Owner's assignment: a specific, in-depth video. Longer than the
            # daily format because the owner wants ALL relevant information.
            user_prompt = f"""OWNER'S ASSIGNMENT — this video MUST be about exactly this topic, nothing else:

{topic_brief}

Write 6 to 8 full, natural German sentences, HARD LIMIT 150 words in total (~70 seconds spoken — count them): a sharp hook first, then every relevant fact in a logical order (what, when, where, how much, what is confirmed vs. only rumoured), and one closing sentence that makes people comment. Use ONLY the facts given in the assignment and in the news list below; where something is not officially confirmed, say so explicitly. Write for the EAR: proper sentence structure, varied rhythm, the way a fellow player would say it out loud.
NUMBERS: years, dates and prices ALWAYS as digits, also in the narration ("19. November 2026", "84,99 Euro", "1. Oktober 2013") — the voice engine reads them correctly and spelled-out years have produced wrong years. The description is normal written German (digits, no spoken-style spelling), 3-5 sentences, not a copy of the narration.
Language: {lang_name} ONLY. Output ONLY valid JSON."""
        else:
            user_prompt = f"""Create today's video: pick EXACTLY ONE GTA topic that makes a GTA player think "das muss ich wissen!".

3 full, natural German sentences, ~20-30 seconds spoken. Write for the EAR: proper sentence structure, varied rhythm, the way a fellow player would actually say it out loud. Hook = the surprising result or payoff.
Language: {lang_name} ONLY. Output ONLY valid JSON."""

        if news_items and topic_brief and brief_style != 'short':
            news_block = "\n".join(
                f"- [{n.get('published','')}] {n.get('title','')}"
                f" (Quelle: {n.get('source','?')})"
                for n in news_items[:12])
            user_prompt += f"""

REAL CURRENT GTA NEWS (fetched live today) — use a headline ONLY if it is about the assigned topic, and never add facts beyond it:
{news_block}"""
        elif news_items:
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

        if top_performers:
            tp = "\n".join(
                f"- {t.get('title','')}  ({t.get('views',0)} views, "
                f"{t.get('likes',0)} likes)" for t in top_performers[:5])
            user_prompt += f"""

WHAT WORKS ON THIS CHANNEL (its best-performing recent videos by views per hour — the audience has voted):
{tp}

Learn from these: their angle (concrete fact + clear payoff for the player), hook style, specificity and title structure. Raise the bar — match or beat this quality. Do NOT repeat their topics (they are also in the already-published list below)."""

        if avoid_titles:
            published = "\n".join(f"- {t}" for t in avoid_titles[:15])
            user_prompt += f"""

ALREADY PUBLISHED on this channel (NEVER repeat these topics, angles or titles):
{published}

Pick a genuinely DIFFERENT GTA topic — a new trick, a new fact, a different myth, another content pillar. Never re-tell the same one."""

        # Sonnet: noticeably better German (fewer errors, more natural
        # narration) — at 4 videos/day this is ~2 CHF/month, worth it.
        # Assignments run 6-8 sentences plus metadata: 1400 tokens truncated
        # the JSON once (live), which surfaced as a JSONDecodeError.
        # Hard guard against repeats: the model once made "Angeln & Jagen"
        # twice in a row despite the published list — a title too close to a
        # recent one is regenerated with the subject explicitly banned.
        banned = []
        for attempt in range(3):
            prompt = user_prompt
            if banned:
                prompt += ("\n\nHARD BAN — the channel JUST covered these; pick a COMPLETELY "
                           "different subject (another pillar if needed), not a new angle "
                           "on them: " + " | ".join(banned))
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2600 if topic_brief else 1400,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = message.content[0].text
            try:
                script = json.loads(raw)
            except json.JSONDecodeError:
                script = json.loads(_sanitize_json(raw))
            title = script.get('title', '')
            if topic_brief or not avoid_titles or not too_similar(title, avoid_titles):
                break
            logger.warning(f"Topic too close to a recent video, regenerating: {title}")
            banned.append(title)

        script = _swissify(script)
        script['narration'] = " ".join(script.get('sentences', []))
        script['language'] = language
        logger.info(f"Script [{language}]: {script.get('title','?')} ({len(script.get('sentences',[]))} sentences)")
        return script

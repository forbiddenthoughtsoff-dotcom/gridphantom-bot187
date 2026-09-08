# -*- coding: utf-8 -*-
"""Two-voice format "Mythos oder Fakt": Ben (curious player, yellow
captions) brings a claim he has heard, Ava (the channel's expert, white
captions) sorts it out — fact, myth, or unknown. Same length as a regular
Short, twice a week instead of the solo narration. Dialogue Shorts get more
comments (people take sides), and the second voice is a pattern break in a
feed full of single narrators.

Output is a normal script dict (title, sentences, narration, tags ...) plus
'lines' [{speaker, text}]; voice() renders both voices line by line and
writes ONE narration mp3 with merged word timings (each word carries its
speaker for the caption colour)."""
import os
import re
import json
import logging
import subprocess

logger = logging.getLogger(__name__)

AVA = os.environ.get('ELEVENLABS_VOICE_ID', 'AnvlJBAqSLDzEevYr9Ap').strip() or 'AnvlJBAqSLDzEevYr9Ap'
BEN = os.environ.get('ELEVENLABS_VOICE_ID_2', 'aTTiK3YzK3dXETpuDE2h').strip() or 'aTTiK3YzK3dXETpuDE2h'
GAP = 0.22

SYSTEM = """You write a two-voice German YouTube Short for the GTA channel GridPhantom (GTA 5, GTA Online, GTA 6).
Format "Mythos oder Fakt": BEN is a curious, slightly cocky GTA player who has heard a claim; AVA is the
channel's expert who knows the facts and answers warmly, precisely, never condescending.

Rules:
- Standard High German, NEVER the character ß (write ss). Digits for numbers and years.
- 6 to 8 lines total, alternating, 55-85 words in total (25-35 seconds). Each line max 20 words.
- Line 1 is BEN with the claim as a hook: bold, concrete, max 12 words, no "Hallo"/"Heute". Example:
  "Angeblich kann man in GTA 6 jedes Haus betreten." / "In GTA Online soll der Bunker sinnlos sein."
- AVA answers with the verdict early (Fakt / Mythos / noch unbekannt) and then 2-3 concrete facts.
  Only confirmed information; unknown things are called unknown. Never invent dates, prices, payouts.
- Ben pushes back once with a follow-up question or a "aber…", Ava lands the payoff.
- Second-to-last line (BEN): a natural subscribe reason, max 10 words, e.g. "Abonniert, ich will davon
  jede Woche eins." Last line (AVA): a short punchline or the comment question that snaps back to the
  claim, max 12 words.
- The claim must be one many German players actually believe or discuss (GTA 6 rumours, GTA Online
  money myths, hidden mechanics, classic urban legends).

Output ONLY JSON:
{"title": "German, max 60 chars, starts with 'Mythos oder Fakt:' then the claim, one emoji max",
 "claim": "the claim in one sentence",
 "lines": [{"speaker": "ben", "text": "..."}, {"speaker": "ava", "text": "..."}],
 "description": "2-3 German sentences + the question for the comments",
 "tags": ["8-12 German + GTA search phrases"],
 "pexels_query": "2-4 English words describing matching footage"}
"""


def generate(language: str = 'de', avoid_titles: list = None, news_items: list = None) -> dict:
    import anthropic
    from config import Config
    from script_generator import too_similar
    news = "\n".join(f"- {n.get('title', '')}" for n in (news_items or [])[:12])
    prompt = ("Schreibe die naechste Folge 'Mythos oder Fakt'.\n"
              "Kuerzlich veroeffentlichte Titel (Thema NICHT wiederholen):\n- "
              + "\n- ".join((avoid_titles or [])[:20])
              + ("\n\nAktuelle Meldungen (optional als Aufhaenger, nur wenn passend):\n" + news if news else ""))
    client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
    banned = []
    for attempt in range(3):
        extra = ("\n\nHARD BAN (Thema zu nah an bestehenden Videos): " + "; ".join(banned)) if banned else ""
        msg = client.messages.create(model='claude-sonnet-4-6', max_tokens=1600, system=SYSTEM,
                                     messages=[{'role': 'user', 'content': prompt + extra}])
        m = re.search(r'\{.*\}', msg.content[0].text, re.S)
        try:
            data = json.loads(m.group(0)) if m else {}
        except Exception:
            data = {}
        lines = [{'speaker': str(l.get('speaker', '')).lower().strip(),
                  'text': str(l.get('text', '')).replace('ß', 'ss').strip()}
                 for l in data.get('lines', []) if str(l.get('text', '')).strip()]
        lines = [l for l in lines if l['speaker'] in ('ava', 'ben')]
        title = str(data.get('title', '')).replace('ß', 'ss').strip()
        if len(lines) >= 5 and title:
            if too_similar(title, avoid_titles or []):
                banned.append(title)
                logger.info(f"Dialogue topic too close to a published one, regenerating: {title}")
                continue
            break
    if len(lines) < 5 or not title:
        raise RuntimeError("dialogue script unusable")
    sentences = [l['text'] for l in lines]
    return {
        'title': title[:70],
        'hook': sentences[0],
        'claim': str(data.get('claim', '')).replace('ß', 'ss'),
        'lines': lines,
        'sentences': sentences,
        'narration': " ".join(sentences),
        'description': str(data.get('description', '')).replace('ß', 'ss').strip(),
        'tags': [str(t).replace('ß', 'ss') for t in data.get('tags', []) if str(t).strip()][:12]
                + ['mythos oder fakt', 'gta mythen'],
        'pexels_query': str(data.get('pexels_query', 'gta gameplay')),
        'pexels_alternatives': [],
        'image_prompt': 'night city neon street',
        'format': 'dialogue',
    }


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _probe(path: str) -> float:
    r = subprocess.run([_ffmpeg(), '-i', path], capture_output=True, text=True)
    m = re.search(r'Duration: (\d+):(\d+):(\d+\.?\d*)', r.stderr)
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def voice(script: dict, language: str = 'de', output_path: str = None) -> str:
    """Both voices, line by line, stitched into one mp3 (+ .words.json with
    absolute times and the speaker of every word)."""
    from voice_generator import VoiceGenerator
    output_path = output_path or f'/tmp/narration_{language}.mp3'
    work = output_path + '.parts'
    os.makedirs(work, exist_ok=True)
    vg = VoiceGenerator()
    parts, words, t = [], [], 0.0
    for i, l in enumerate(script['lines']):
        mp3 = os.path.join(work, f'line_{i}.mp3')
        vg.generate(l['text'], language, output_path=mp3,
                    voice_id=BEN if l['speaker'] == 'ben' else AVA)
        dur = _probe(mp3)
        try:
            with open(mp3 + '.words.json', encoding='utf-8') as f:
                for w in json.load(f):
                    words.append({'text': w['text'], 'start': w['start'] + t,
                                  'end': w['end'] + t, 'speaker': l['speaker']})
        except Exception:
            pass
        parts.append(mp3)
        t += dur + GAP
    cmd = [_ffmpeg(), '-y']
    filt = []
    for i, p in enumerate(parts):
        cmd += ['-i', p]
        pad = GAP if i < len(parts) - 1 else 0.0
        filt.append(f"[{i}:a]aresample=44100,apad=pad_dur={pad:.2f}[a{i}]")
    filt.append("".join(f"[a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[a]")
    cmd += ['-filter_complex', ';'.join(filt), '-map', '[a]', '-c:a', 'libmp3lame', '-b:a', '160k', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"dialogue stitch failed: {r.stderr[-300:]}")
    with open(output_path + '.words.json', 'w', encoding='utf-8') as f:
        json.dump(words, f, ensure_ascii=False)
    for p in parts:
        for q in (p, p + '.words.json'):
            try:
                os.remove(q)
            except OSError:
                pass
    logger.info(f"🎭 Dialogue voice: {len(parts)} lines, {len(words)} timed words, {t:.1f}s")
    return output_path


def is_dialogue_slot(now=None) -> bool:
    """Tuesday and Friday 22:00 (configurable: DIALOGUE_DAYS='1,4', DIALOGUE_HOUR=22)."""
    from datetime import datetime
    now = now or datetime.now()
    days = {int(x) for x in os.environ.get('DIALOGUE_DAYS', '1,4').split(',') if x.strip().isdigit()}
    hour = int(os.environ.get('DIALOGUE_HOUR', '22'))
    return now.weekday() in days and now.hour == hour

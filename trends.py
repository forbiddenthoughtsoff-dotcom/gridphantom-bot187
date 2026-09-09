# -*- coding: utf-8 -*-
"""Trend radar: what is hyped RIGHT NOW.

One source, no keys, no quota cost: Google News RSS (DE + EN + a Rockstar
filter). It delivers ~170 timestamped headlines per poll, which is plenty —
Reddit blocks datacentre IPs and a YouTube search costs 100 quota units for
information the headlines already carry.

Headlines are clustered into topics by shared keywords and scored:

    score = recency x source_diversity x freshness x surge

Recency weights an item by age (half-life ~10 h), so 6 headlines from this
morning outrank 20 spread over a week. Surge compares against the previous
poll (state in /tmp): a topic whose weight jumped since the last check is
breaking out RIGHT NOW — that is the moment to publish, not two days later.

Observed baseline on a quiet day: top topic ~12, everyday topics 3-8.
A Rockstar announcement or a trailer drop lands far above that.
"""
import os
import re
import json
import math
import time
import logging
import datetime as _dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

logger = logging.getLogger(__name__)

STATE_FILE = os.environ.get('TRENDS_STATE', '/tmp/trends_state.json')
COVERED_FILE = os.environ.get('TRENDS_COVERED', '/tmp/trends_covered.json')
UA = {"User-Agent": "Mozilla/5.0 (compatible; GridPhantomBot/1.0)"}

# Calibrated against live data (quiet day peaks at ~12).
BREAKING_SCORE = float(os.environ.get('BREAKING_SCORE', '28'))  # interrupt the schedule
RIDE_SCORE = float(os.environ.get('RIDE_SCORE', '6'))           # use in a normal slot

FEEDS = [
    ('de', "https://news.google.com/rss/search?q=%22GTA%206%22%20OR%20%22GTA%20VI%22"
           "&hl=de&gl=DE&ceid=DE:de"),
    ('en', "https://news.google.com/rss/search?q=%22GTA%206%22%20OR%20%22GTA%20VI%22"
           "%20OR%20%22Rockstar%20Games%22&hl=en-US&gl=US&ceid=US:en"),
    ('online', "https://news.google.com/rss/search?q=%22GTA%20Online%22%20OR%20%22GTA%205%22"
               "&hl=de&gl=DE&ceid=DE:de"),
]

STOP = set("""der die das den dem des ein eine einer eines und oder aber auch noch nur
schon sich ist sind war waren wird werden wurde wurden hat haben hatte kann koennen
soll sollen muss mehr sehr alle alles wie was wer wann warum fuer für mit von zum zur
bei nach aus auf ueber über unter vor gegen ohne seit bis durch this that with from
have has had will would could should about into your you our their they them then
than there here what when where which while who why how all any both each few more
most other some such only own same too very can just now new news update gta grand
theft auto rockstar games spiel game video videos neu neue neuer neues jetzt heute
laut angeblich bericht berichten kommt kommen gibt geben zeigt zeigen sagt sagen""".split())


def _words(text):
    t = re.sub(r'[^a-zA-ZäöüÄÖÜß0-9 ]+', ' ', str(text or '').lower())
    return {w for w in t.split() if len(w) > 3 and w not in STOP}


def _load(p, d):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return d


def _save(p, d):
    try:
        json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Trend state not written: {e}")


def _headlines() -> list:
    now = _dt.datetime.now(_dt.timezone.utc)
    out = []
    for lang, url in FEEDS:
        try:
            root = ET.fromstring(requests.get(url, timeout=20, headers=UA).content)
        except Exception as e:
            logger.warning(f"Trend feed {lang} failed: {e}")
            continue
        for it in root.iter('item'):
            title = (it.findtext('title') or '').split(' - ')[0].strip()
            if not title:
                continue
            try:
                pub = parsedate_to_datetime(it.findtext('pubDate') or '')
                age = max(0.05, (now - pub).total_seconds() / 3600.0)
            except Exception:
                age = 72.0
            if age <= 96:
                out.append({'t': title, 'src': lang, 'age': age,
                            'link': it.findtext('link') or ''})
    return out


def scan() -> list:
    """Scored topics, best first."""
    items = _headlines()
    if not items:
        return []
    clusters = []
    for it in items:
        kw = _words(it['t'])
        if len(kw) < 2:
            continue
        hit = next((c for c in clusters if len(kw & c['kw']) >= 2), None)
        if hit:
            hit['kw'] |= kw
            hit['items'].append(it)
        else:
            clusters.append({'kw': kw, 'items': [it]})

    prev = _load(STATE_FILE, {})
    topics = []
    for c in clusters:
        if len(c['items']) < 2:
            continue
        its = sorted(c['items'], key=lambda i: i['age'])
        recency = sum(math.exp(-i['age'] / 10.0) for i in its)
        srcs = sorted({i['src'] for i in its})
        fresh = sum(1 for i in its if i['age'] <= 6) / len(its)
        key = '-'.join(sorted(c['kw'])[:4])
        old = prev.get(key, 0.0)
        old = old.get('recency', 0.0) if isinstance(old, dict) else float(old or 0)
        surge = 1.0 + min(1.5, recency / old - 1.0) if old > 0.3 and recency > old * 1.5 else 1.0
        topics.append({
            'key': key,
            'label': min((i['t'] for i in its[:4]), key=len)[:110],
            'score': round(recency * (1 + 0.4 * (len(srcs) - 1)) * (1 + fresh) * surge, 1),
            'surge': round(surge, 2), 'sources': srcs,
            'newest_h': round(its[0]['age'], 1),
            'headlines': [i['t'] for i in its[:8]],
        })
    topics.sort(key=lambda t: t['score'], reverse=True)
    _save(STATE_FILE, {t['key']: t['score'] / max(t['surge'], 1) for t in topics[:60]})
    if topics:
        logger.info("📡 Trends: " + " | ".join(
            f"{t['label'][:34]} ({t['score']}{'🔥' if t['surge'] > 1.1 else ''})"
            for t in topics[:3]))
    return topics


def mark_covered(key: str, video_id: str = ''):
    c = _load(COVERED_FILE, {})
    c[key] = time.time()
    _save(COVERED_FILE, {k: v for k, v in c.items() if v > time.time() - 12 * 86400})


def _covered(key: str, recent_titles: list) -> bool:
    if key in _load(COVERED_FILE, {}):
        return True
    kws = set(key.split('-'))
    return any(len(kws & _words(t)) >= 2 for t in recent_titles or [])


def pick(recent_titles: list = None, breaking_only: bool = False) -> dict:
    """Best uncovered topic, or None. breaking_only: schedule-interrupt level."""
    floor = BREAKING_SCORE if breaking_only else RIDE_SCORE
    for t in scan():
        if t['score'] < floor:
            return None
        if breaking_only and t['newest_h'] > 10:
            continue
        if _covered(t['key'], recent_titles):
            continue
        if breaking_only:
            logger.info(f"🚨 BREAKING: {t['label']} (score {t['score']}, "
                        f"{t['newest_h']} h alt)")
        return t
    return None


def brief_for(topic: dict, breaking: bool = False) -> dict:
    heads = "\n".join(f"- {h}" for h in topic['headlines'])
    lead = ("EILMELDUNG, dieses Thema explodiert gerade: sei der Erste, der es einordnet. "
            "Erster Satz nennt die Neuigkeit konkret, zweiter Satz sagt, was sie fuer "
            "Spieler bedeutet."
            if breaking else
            "TRENDTHEMA, darueber wird gerade am meisten gesprochen. Greif es auf, "
            "solange die Suche danach laeuft.")
    return {'brief': (
        f"{lead}\nTHEMA: {topic['label']}\n"
        f"AKTUELLE SCHLAGZEILEN (einzige Faktenbasis, nichts dazuerfinden):\n{heads}\n"
        f"REGELN: Bestaetigtes klar als bestaetigt benennen, Geruechte und Leaks "
        f"ausdruecklich als solche. Keine Zahlen, Daten oder Preise erfinden, die oben "
        f"nicht stehen. Widersprechen sich die Meldungen, sag das offen - genau das ist "
        f"der Mehrwert gegenueber den Clickbait-Kanaelen."),
        'images': [], 'trend_key': topic['key']}


# --- Vorschau: bekannte Termine, die verlaesslich Aufmerksamkeit erzeugen ---
# Ein Video AM VORABEND eines Termins laeuft besser als eines danach.
CALENDAR = [
    # (Monat, Tag, Vorlauf in Tagen, Thema)
    (12, 4, 2, "Jahrestag von GTA 6 Trailer 1: was seither bestaetigt wurde"),
    (5, 6, 2, "Jahrestag von GTA 6 Trailer 2: was er gezeigt hat und was seither dazukam"),
    (10, 28, 3, "Halloween in GTA Online: was Rockstar dieses Jahr gebracht hat"),
    (12, 18, 3, "Winter-Update in GTA Online: Schnee, Event und Belohnungen"),
    (5, 19, 7, "GTA 6 Release am 19. Mai 2027: der Countdown"),
]


def upcoming(today=None) -> dict:
    """Naechster bekannter Termin innerhalb seines Vorlaufs, sonst None.
    Donnerstag ist immer GTA-Online-Update-Tag."""
    import datetime as d
    today = today or d.date.today()
    for month, day, lead, theme in CALENDAR:
        year = today.year if (month, day) >= (today.month, today.day) else today.year + 1
        try:
            delta = (d.date(year, month, day) - today).days
        except ValueError:
            continue
        if 0 <= delta <= lead:
            return {'key': f'cal-{month}-{day}', 'label': theme,
                    'score': 99, 'newest_h': 0.0, 'sources': ['kalender'],
                    'headlines': [f"{theme} (in {delta} Tagen)"]}
    if today.weekday() == 3:      # Donnerstag: woechentliches GTA-Online-Update
        return {'key': f'weekly-{today.isocalendar()[1]}', 'score': 99,
                'label': "GTA Online Wochenupdate: Boni, Event und neue Inhalte dieser Woche",
                'newest_h': 0.0, 'sources': ['kalender'],
                'headlines': ["Rockstar veroeffentlicht donnerstags das Wochenupdate"]}
    return None


def recent_news(limit: int = 20) -> list:
    """Headlines as {title, source, published} — the script generator's factual
    ground truth. Same poll as the trend radar, so no second RSS round trip."""
    import datetime as d
    now = d.datetime.now(d.timezone.utc)
    out = []
    for h in sorted(_headlines(), key=lambda i: i['age'])[:limit]:
        out.append({'title': h['t'], 'source': h['src'], 'link': h['link'],
                    'published': (now - d.timedelta(hours=h['age'])).isoformat()})
    return out

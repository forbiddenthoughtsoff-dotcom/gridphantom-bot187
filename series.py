# -*- coding: utf-8 -*-
"""Owner's series: "GTA Online Karriere" — one tutorial a day.

series/karriere.json holds the episodes (career × tier, in a sensible
order: businesses first, then heists, contact missions, recreation, series
modes, special interests). The daily series slot (SERIES_HOUR, default 12
local) publishes the next unpublished episode as an owner assignment
(topic brief). Progress is read from the channel itself: every episode
title starts with "GTA Online Karriere #N", so the next N is max(N)+1 of
the recent uploads — no local state to lose on a restart."""
import os
import re
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

SERIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'series', 'karriere.json')
TITLE_RE = re.compile(r'karriere\s*#\s*(\d+)', re.I)


def load_episodes() -> list:
    try:
        with open(SERIES_FILE, encoding='utf-8') as f:
            eps = json.load(f)
        return eps if isinstance(eps, list) else []
    except Exception as e:
        logger.warning(f"Series file unreadable: {e}")
        return []


def is_series_slot(now: datetime = None) -> bool:
    hour = int(os.environ.get('SERIES_HOUR', '12'))
    if hour < 0:
        return False
    return (now or datetime.now()).hour == hour


def next_episode(published_titles: list) -> dict:
    """Next episode after the highest number found in the published titles
    (None when the series is complete)."""
    done = 0
    for t in published_titles or []:
        m = TITLE_RE.search(str(t or ''))
        if m:
            done = max(done, int(m.group(1)))
    for e in load_episodes():
        if int(e.get('n', 0)) == done + 1:
            return e
    return None


def brief_for(e: dict) -> dict:
    tasks = "\n".join(f"- {t}" for t in e.get('tasks', []))
    nxt = e.get('next_hint', '')
    brief = (
        f"SERIE 'GTA Online Karriere', Folge {e['n']}: {e['career']} – Stufe {e['tier']} von 4 "
        f"(Kategorie: {e['category']}). Der Titel MUSS exakt so beginnen: "
        f"'GTA Online Karriere #{e['n']}: {e['career']} Stufe {e['tier']}' – danach darf ein kurzer Zusatz folgen.\n"
        f"Kontext (bestaetigt): Der Karriere-Fortschritt ist ein Feature von GTA Online auf PS5 und Xbox Series X|S "
        f"(eingefuehrt Juni 2023 mit dem Update San Andreas Mercenaries). Es gibt 6 Kategorien, jede Herausforderung hat 4 Stufen; "
        f"jede Stufe schaltet Belohnungen frei (exklusive Kleidung, Lackierungen, GTA$ und RP). Menue: Pause > Online > Karriere-Fortschritt.\n"
        f"AUFGABEN dieser Stufe (Kurzform aus dem GTA-Wiki – jede Aufgabe nennen und verstaendlich erklaeren, "
        f"keine Zahlen erfinden, die hier nicht stehen):\n{tasks}\n"
        f"Ziel des Videos: Der Zuschauer weiss danach genau, was zu tun ist, in welcher Reihenfolge es am schnellsten geht, "
        f"welche Voraussetzung (Immobilie/Kontakt) noetig ist und welchen typischen Fehler er vermeidet. "
        f"Tipps NUR, wenn sie in GTA Online sicher zutreffen; im Zweifel weglassen. Ton: GridPhantom kennt sich aus und teilt sein Wissen "
        f"('Sharing is caring'), souveraen, kein Angeben. "
        f"Schluss: ein Satz mit Hinweis auf die naechste Folge ({nxt}) und die Bitte, die Serie zu abonnieren."
    )
    return {'brief': brief, 'images': [], 'series': f"K{e['n']:03d}"}

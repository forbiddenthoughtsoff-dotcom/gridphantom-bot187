# -*- coding: utf-8 -*-
"""Live GTA news via Google News RSS — real, current headlines from many
sources, used to GROUND the script generator so it reports actual news
instead of inventing it. No API key needed."""
import logging
import datetime as _dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import requests

logger = logging.getLogger(__name__)

# Google News RSS search feeds (German). Each returns real, dated headlines
# aggregated from many outlets — including Rockstar's own announcements.
FEEDS = [
    ("GTA 6", "https://news.google.com/rss/search?"
              "q=%22GTA%206%22%20OR%20%22GTA%20VI%22&hl=de&gl=DE&ceid=DE:de"),
    ("GTA Online", "https://news.google.com/rss/search?"
                   "q=%22GTA%20Online%22%20OR%20%22GTA%205%22&hl=de&gl=DE&ceid=DE:de"),
]

_UA = {"User-Agent": "Mozilla/5.0 (compatible; GridPhantomBot/1.0)"}


def _parse_date(s: str):
    try:
        return parsedate_to_datetime(s)
    except Exception:
        return None


def fetch_recent_news(max_age_days: int = 21, limit: int = 10) -> list:
    """Return recent GTA news items as dicts: {title, source, published, link}.
    Sorted newest first, deduplicated, only items within max_age_days."""
    now = _dt.datetime.now(_dt.timezone.utc)
    seen_titles = set()
    items = []

    for topic, url in FEEDS:
        try:
            r = requests.get(url, timeout=20, headers=_UA)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:
            logger.warning(f"News feed '{topic}' failed: {e}")
            continue

        for it in root.findall(".//item"):
            raw_title = (it.findtext("title") or "").strip()
            if not raw_title:
                continue
            # Google appends " - Source" to titles; split it off
            source = ""
            title = raw_title
            if " - " in raw_title:
                title, source = raw_title.rsplit(" - ", 1)
            key = title.lower().strip()
            if key in seen_titles:
                continue

            pub = _parse_date(it.findtext("pubDate") or "")
            if pub is not None:
                age = (now - pub).days
                if age > max_age_days:
                    continue
            seen_titles.add(key)
            items.append({
                "title": title.strip(),
                "source": source.strip(),
                "published": pub.strftime("%Y-%m-%d") if pub else "",
                "topic": topic,
                "link": (it.findtext("link") or "").strip(),
                "_dt": pub or now,
            })

    items.sort(key=lambda x: x["_dt"], reverse=True)
    for x in items:
        x.pop("_dt", None)
    logger.info(f"📰 Fetched {len(items)} recent GTA news items")
    return items[:limit]

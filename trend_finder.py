import feedparser
import requests
import logging
from datetime import datetime, timedelta
from config import Config

logger = logging.getLogger(__name__)

class TrendFinder:
    def __init__(self):
        self.feeds = Config.RSS_FEEDS

    def get_trending_topics(self):
        """Fetch trending AI & Tech topics from RSS feeds"""
        topics = []
        cutoff = datetime.now() - timedelta(hours=24)

        for feed_url in self.feeds:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:5]:
                    published = entry.get('published_parsed')
                    if published:
                        pub_date = datetime(*published[:6])
                        if pub_date < cutoff:
                            continue

                    topic = {
                        'title': entry.get('title', ''),
                        'summary': entry.get('summary', '')[:500],
                        'link': entry.get('link', ''),
                        'source': feed.feed.get('title', ''),
                        'published': entry.get('published', ''),
                    }

                    # Filter for AI & Tech relevance
                    keywords = ['ai', 'artificial intelligence', 'machine learning',
                                'openai', 'google', 'microsoft', 'meta', 'robot',
                                'chatgpt', 'gpt', 'claude', 'gemini', 'tech',
                                'startup', 'silicon valley', 'chip', 'gpu', 'nvidia',
                                'software', 'app', 'model', 'llm', 'automation']

                    text = (topic['title'] + ' ' + topic['summary']).lower()
                    if any(kw in text for kw in keywords):
                        topics.append(topic)

            except Exception as e:
                logger.error(f"Error fetching feed {feed_url}: {e}")

        # Deduplicate and rank by freshness
        seen = set()
        unique_topics = []
        for t in topics:
            if t['title'] not in seen:
                seen.add(t['title'])
                unique_topics.append(t)

        logger.info(f"Found {len(unique_topics)} trending topics")
        return unique_topics[:10]  # Return top 10

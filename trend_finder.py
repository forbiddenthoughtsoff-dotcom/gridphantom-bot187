import feedparser
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

        # Deduplicate
        seen = set()
        unique_topics = []
        for t in topics:
            if t['title'] not in seen:
                seen.add(t['title'])
                unique_topics.append(t)

        # Rank by viral potential: hot entities + emotional trigger words
        viral_weights = {
            'openai': 5, 'chatgpt': 5, 'gpt': 4, 'apple': 4, 'iphone': 4,
            'elon': 4, 'musk': 4, 'tesla': 4, 'google': 3, 'gemini': 3,
            'nvidia': 3, 'meta': 3, 'microsoft': 3, 'anthropic': 3, 'claude': 3,
            'banned': 5, 'leaked': 5, 'hack': 5, 'hacked': 5, 'lawsuit': 4,
            'breakthrough': 4, 'first ever': 4, 'shocking': 4, 'secret': 4,
            'billion': 3, 'million': 2, 'record': 3, 'fired': 4, 'shut down': 4,
            'robot': 3, 'humanoid': 4, 'agi': 5, 'superintelligence': 5,
            'free': 3, 'replaced': 4, 'jobs': 3, 'warning': 3, 'quantum': 3,
        }

        def viral_score(t):
            text = (t['title'] + ' ' + t['summary']).lower()
            return sum(w for kw, w in viral_weights.items() if kw in text)

        unique_topics.sort(key=viral_score, reverse=True)
        if unique_topics:
            logger.info(f"Found {len(unique_topics)} topics | Top pick (score {viral_score(unique_topics[0])}): {unique_topics[0]['title'][:70]}")
        return unique_topics[:10]  # Return top 10, best first

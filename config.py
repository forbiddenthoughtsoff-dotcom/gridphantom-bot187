import os


class Config:
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
    YOUTUBE_CLIENT_SECRETS = os.environ.get('YOUTUBE_CLIENT_SECRETS')
    RSS_FEEDS = [
        'https://techcrunch.com/feed/',
        'https://www.theverge.com/rss/index.xml',
        'https://feeds.arstechnica.com/arstechnica/index',
        'https://www.wired.com/feed/rss',
    ]

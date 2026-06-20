import os

class Config:
    # API Keys
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
    ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY')
    PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')

    # YouTube OAuth2
    YOUTUBE_CLIENT_SECRETS = os.environ.get('YOUTUBE_CLIENT_SECRETS')  # JSON string

    # ElevenLabs Voice IDs
    VOICE_ID_EN = os.environ.get('VOICE_ID_EN')  # Ray
    VOICE_ID_DE = os.environ.get('VOICE_ID_DE')  # Helmut

    # Channel
    YOUTUBE_CHANNEL_ID = os.environ.get('YOUTUBE_CHANNEL_ID', 'GridPhantom187')

    # Bot settings
    VIDEOS_PER_DAY = int(os.environ.get('VIDEOS_PER_DAY', '2'))
    LANGUAGES = ['en', 'de']
    VIDEO_DURATION_TARGET = 600  # 10 minutes (optimal for mid-roll ads)

    # RSS Feeds - AI & Tech
    RSS_FEEDS = [
        'https://techcrunch.com/feed/',
        'https://www.theverge.com/rss/index.xml',
        'https://feeds.wired.com/wired/index',
        'https://www.artificialintelligence-news.com/feed/',
        'https://venturebeat.com/feed/',
        'https://www.technologyreview.com/feed/',
        'https://openai.com/news/rss.xml',
    ]

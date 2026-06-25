import os


class Config:
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
    FAL_KEY = os.environ.get('FAL_KEY')
    YOUTUBE_CLIENT_SECRETS = os.environ.get('YOUTUBE_CLIENT_SECRETS')
    YOUTUBE_CHANNEL_ID = os.environ.get('YOUTUBE_CHANNEL_ID', 'GridPhantom187')

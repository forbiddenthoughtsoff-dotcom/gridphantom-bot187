import os


class Config:
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
    YOUTUBE_CLIENT_SECRETS = os.environ.get('YOUTUBE_CLIENT_SECRETS')

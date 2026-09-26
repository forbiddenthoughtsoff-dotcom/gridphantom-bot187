# -*- coding: utf-8 -*-
import os


class Config:
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
    YOUTUBE_CLIENT_SECRETS = os.environ.get('YOUTUBE_CLIENT_SECRETS')
    # Channel identity in one place: brand band, footers, prompts, playlists.
    # Switching channels = setting these two variables on the server.
    CHANNEL_NAME = os.environ.get('CHANNEL_NAME', 'GridPhantom')
    CHANNEL_HANDLE = os.environ.get('CHANNEL_HANDLE', '@GridPhantom187')

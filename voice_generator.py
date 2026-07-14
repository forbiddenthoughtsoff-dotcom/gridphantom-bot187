# -*- coding: utf-8 -*-
import os
import asyncio
import edge_tts
import logging

logger = logging.getLogger(__name__)

# Language-aware voices (override via env if desired).
# de-DE-Seraphina is Microsoft's newest multilingual neural voice — noticeably
# warmer and more natural than the older Katja/Conrad voices.
VOICES = {
    'en': os.environ.get('VOICE_EN', 'en-US-AvaMultilingualNeural'),
    'de': os.environ.get('VOICE_DE', 'de-DE-SeraphinaMultilingualNeural'),
}

# Natural pacing: no artificial speed-up (the old +5% made it sound rushed).
# A hair of pitch keeps it lively without the robotic tone.
RATE = os.environ.get('TTS_RATE', '+0%')
PITCH = os.environ.get('TTS_PITCH', '+2Hz')


class VoiceGenerator:
    def generate(self, text: str, language: str = 'en', output_path: str = None) -> str:
        voice = VOICES.get(language, VOICES['en'])
        if not output_path:
            output_path = f'/tmp/narration_{language}.mp3'
        asyncio.run(self._generate(text, voice, output_path))
        logger.info(f"Audio generated [{language}/{voice}]: {output_path} ({os.path.getsize(output_path)} bytes)")
        return output_path

    async def _generate(self, text: str, voice: str, output_path: str):
        communicate = edge_tts.Communicate(text, voice, rate=RATE, pitch=PITCH)
        await communicate.save(output_path)

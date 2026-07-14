# -*- coding: utf-8 -*-
import os
import asyncio
import edge_tts
import logging

logger = logging.getLogger(__name__)

# Language-aware voices (override via env if desired)
VOICES = {
    'en': os.environ.get('VOICE_EN', 'en-US-ChristopherNeural'),
    'de': os.environ.get('VOICE_DE', 'de-DE-KatjaNeural'),
}


class VoiceGenerator:
    def generate(self, text: str, language: str = 'en', output_path: str = None) -> str:
        voice = VOICES.get(language, VOICES['en'])
        if not output_path:
            output_path = f'/tmp/narration_{language}.mp3'
        asyncio.run(self._generate(text, voice, output_path))
        logger.info(f"Audio generated [{language}/{voice}]: {output_path} ({os.path.getsize(output_path)} bytes)")
        return output_path

    async def _generate(self, text: str, voice: str, output_path: str):
        communicate = edge_tts.Communicate(text, voice, rate='+5%')
        await communicate.save(output_path)

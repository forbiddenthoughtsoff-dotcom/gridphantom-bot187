# -*- coding: utf-8 -*-
import os
import json
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
        """Generate narration audio. Also writes word-level timings to
        <output_path>.words.json so the assembler can render pro-style
        word-synced captions."""
        voice = VOICES.get(language, VOICES['en'])
        if not output_path:
            output_path = f'/tmp/narration_{language}.mp3'
        asyncio.run(self._generate(text, voice, output_path))
        logger.info(f"Audio generated [{language}/{voice}]: {output_path} ({os.path.getsize(output_path)} bytes)")
        return output_path

    async def _generate(self, text: str, voice: str, output_path: str):
        communicate = edge_tts.Communicate(text, voice, rate=RATE, pitch=PITCH,
                                           boundary="WordBoundary")
        words = []
        with open(output_path, 'wb') as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append({
                        "text": chunk["text"],
                        "start": chunk["offset"] / 1e7,
                        "end": (chunk["offset"] + chunk["duration"]) / 1e7,
                    })
        words_path = output_path + '.words.json'
        try:
            with open(words_path, 'w', encoding='utf-8') as f:
                json.dump(words, f, ensure_ascii=False)
            logger.info(f"Word timings: {len(words)} words -> {words_path}")
        except Exception as e:
            logger.warning(f"Could not write word timings (captions will "
                           f"fall back to sentence overlays): {e}")

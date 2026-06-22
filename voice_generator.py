import os
import asyncio
import logging
import edge_tts

logger = logging.getLogger(__name__)

class VoiceGenerator:
    """Free text-to-speech using Microsoft Edge TTS (no API key required)."""

    def __init__(self):
        # Natural-sounding male voices for each language
        self.voice_map = {
            'en': 'en-US-AndrewNeural',
            'de': 'de-DE-ConradNeural',
        }

    def generate(self, text: str, language: str, output_path: str = None) -> str:
        """Generate voice audio from text using Edge TTS."""

        voice = self.voice_map.get(language)
        if not voice:
            raise ValueError(f"No voice configured for language: {language}")

        if not output_path:
            output_path = f"/tmp/narration_{language}.mp3"

        try:
            asyncio.run(self._synthesize(text, voice, output_path))

            size = os.path.getsize(output_path)
            if size == 0:
                raise RuntimeError("Edge TTS produced an empty audio file")

            logger.info(f"Audio generated: {output_path} ({size} bytes)")
            return output_path

        except Exception as e:
            logger.error(f"Voice generation error: {e}")
            raise

    async def _synthesize(self, text: str, voice: str, output_path: str):
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)

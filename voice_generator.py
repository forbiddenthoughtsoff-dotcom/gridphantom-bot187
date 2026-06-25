import asyncio
import edge_tts
import logging

logger = logging.getLogger(__name__)


class VoiceGenerator:
    def __init__(self):
        self.voice = 'en-US-AvaNeural'  # Natural female English voice

    def generate(self, text: str, language: str = 'en', output_path: str = None) -> str:
        if not output_path:
            output_path = '/tmp/narration_en.mp3'
        asyncio.run(self._generate(text, output_path))
        import os
        logger.info(f"Audio generated: {output_path} ({os.path.getsize(output_path)} bytes)")
        return output_path

    async def _generate(self, text: str, output_path: str):
        communicate = edge_tts.Communicate(text, self.voice, rate='+5%')
        await communicate.save(output_path)

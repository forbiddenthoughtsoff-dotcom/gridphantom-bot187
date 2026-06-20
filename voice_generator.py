import requests
import os
import logging
from config import Config

logger = logging.getLogger(__name__)

class VoiceGenerator:
    def __init__(self):
        self.api_key = Config.ELEVENLABS_API_KEY
        self.base_url = "https://api.elevenlabs.io/v1"
        self.voice_map = {
            'en': Config.VOICE_ID_EN,   # Ray
            'de': Config.VOICE_ID_DE,   # Helmut
        }

    def generate(self, text: str, language: str, output_path: str = None) -> str:
        """Generate voice audio from text"""

        voice_id = self.voice_map.get(language)
        if not voice_id:
            raise ValueError(f"No voice configured for language: {language}")

        if not output_path:
            output_path = f"/tmp/narration_{language}.mp3"

        url = f"{self.base_url}/text-to-speech/{voice_id}"

        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json"
        }

        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8,
                "style": 0.3,
                "use_speaker_boost": True
            }
        }

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()

            with open(output_path, 'wb') as f:
                f.write(response.content)

            logger.info(f"Audio generated: {output_path} ({os.path.getsize(output_path)} bytes)")
            return output_path

        except Exception as e:
            logger.error(f"Voice generation error: {e}")
            raise

# -*- coding: utf-8 -*-
import os
import json
import base64
import asyncio
import logging
import requests
import edge_tts

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Voice tiers
#   1) ElevenLabs (premium, genuinely human-sounding German) — used when
#      ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID are set
#   2) edge-tts Seraphina (free fallback) — always available
# Both write word timings to <audio>.words.json for the synced captions.
# ---------------------------------------------------------------------------

ELEVEN_KEY = os.environ.get('ELEVENLABS_API_KEY', '').strip()
# VOICE_ID_DE is the variable name from the channel's original June setup
ELEVEN_VOICE = (os.environ.get('ELEVENLABS_VOICE_ID', '').strip()
                or os.environ.get('VOICE_ID_DE', '').strip())
# flash_v2_5: half the credit cost, native German, fast — fits the Starter plan
ELEVEN_MODEL = os.environ.get('ELEVENLABS_MODEL', 'eleven_flash_v2_5')

VOICES = {
    'en': os.environ.get('VOICE_EN', 'en-US-AvaMultilingualNeural'),
    'de': os.environ.get('VOICE_DE', 'de-DE-SeraphinaMultilingualNeural'),
    # second speaker (dialogue format) on the free fallback engine
    'de_m': os.environ.get('VOICE_DE_M', 'de-DE-FlorianMultilingualNeural'),
}
# Second ElevenLabs voice for the two-voice format ("Ben - GridPhantom DE")
ELEVEN_VOICE_2 = os.environ.get('ELEVENLABS_VOICE_ID_2', 'aTTiK3YzK3dXETpuDE2h').strip()
RATE = os.environ.get('TTS_RATE', '+0%')
PITCH = os.environ.get('TTS_PITCH', '+0Hz')

# Which engine produced the last narration ('elevenlabs' | 'edge') — the
# uploader adds the ElevenLabs attribution line required on the free tier.
LAST_ENGINE = 'edge'


def _chars_to_words(chars, starts, ends):
    """Collapse ElevenLabs character-level alignment into word timings."""
    words, cur, w_start, w_end = [], '', None, None
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append({'text': cur, 'start': w_start, 'end': w_end})
                cur, w_start = '', None
            continue
        if not cur:
            w_start = s
        cur += ch
        w_end = e
    if cur:
        words.append({'text': cur, 'start': w_start, 'end': w_end})
    return words


def _write_words(output_path, words):
    try:
        with open(output_path + '.words.json', 'w', encoding='utf-8') as f:
            json.dump(words, f, ensure_ascii=False)
        logger.info(f"Word timings: {len(words)} words")
    except Exception as e:
        logger.warning(f"Could not write word timings: {e}")


class VoiceGenerator:
    def generate(self, text: str, language: str = 'en', output_path: str = None,
                 voice_id: str = None) -> str:
        """voice_id: optional ElevenLabs voice for this call (second speaker);
        on the fallback engine a male German voice is used instead."""
        if not output_path:
            output_path = f'/tmp/narration_{language}.mp3'
        # stale timings from a previous run must never leak into this video
        try:
            os.remove(output_path + '.words.json')
        except FileNotFoundError:
            pass

        global LAST_ENGINE
        if ELEVEN_KEY and (voice_id or ELEVEN_VOICE):
            try:
                self._elevenlabs(text, language, output_path, voice_id=voice_id)
                LAST_ENGINE = 'elevenlabs'
                logger.info(f"Audio generated [{language}/ElevenLabs {ELEVEN_MODEL}]: "
                            f"{output_path} ({os.path.getsize(output_path)} bytes)")
                return output_path
            except Exception as e:
                logger.warning(f"ElevenLabs failed, falling back to edge-tts: {e}")

        LAST_ENGINE = 'edge'
        voice = VOICES.get(language, VOICES['en'])
        if voice_id and voice_id != ELEVEN_VOICE and language == 'de':
            voice = VOICES['de_m']
        asyncio.run(self._edge(text, voice, output_path))
        logger.info(f"Audio generated [{language}/{voice}]: {output_path} "
                    f"({os.path.getsize(output_path)} bytes)")
        return output_path

    # -- premium tier --------------------------------------------------------
    def _elevenlabs(self, text: str, language: str, output_path: str,
                    voice_id: str = None):
        url = (f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id or ELEVEN_VOICE}"
               f"/with-timestamps?output_format=mp3_44100_128")
        body = {
            'text': text,
            'model_id': ELEVEN_MODEL,
            'voice_settings': {
                'stability': 0.45,        # lively, not monotone
                'similarity_boost': 0.8,
                'style': 0.3,
                'use_speaker_boost': True,
            },
        }
        if 'v2_5' in ELEVEN_MODEL or 'v3' in ELEVEN_MODEL:
            body['language_code'] = language
        r = requests.post(url, json=body, timeout=120,
                          headers={'xi-api-key': ELEVEN_KEY,
                                   'Content-Type': 'application/json'})
        r.raise_for_status()
        data = r.json()
        with open(output_path, 'wb') as f:
            f.write(base64.b64decode(data['audio_base64']))
        al = data.get('alignment') or data.get('normalized_alignment') or {}
        words = _chars_to_words(al.get('characters', []),
                                al.get('character_start_times_seconds', []),
                                al.get('character_end_times_seconds', []))
        _write_words(output_path, words)

    # -- free fallback -------------------------------------------------------
    async def _edge(self, text: str, voice: str, output_path: str):
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
        _write_words(output_path, words)

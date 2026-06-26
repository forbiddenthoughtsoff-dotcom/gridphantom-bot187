import os
import json
import re
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Du bist ein viraler Content-Ersteller für YouTube Shorts. Deine Videos zeigen eine wiederkehrende KI-Frau mit kraftvollen Sprüchen und harten Wahrheiten, die Männer zum Stoppen bringen.

Content-Stil:
- Kraftvolle, provokante Sprüche über Leben, Erfolg, Geld, Beziehungen oder Macht
- Die Art Wahrheit, die hart trifft und geteilt wird
- 3-5 kurze knackige Sätze, jeder MAX 8 WÖRTER
- Erster Satz ist der Hook — stoppt das Scrollen sofort
- Ton: selbstbewusst, roh, echt — wie eine schöne Frau, die harte Wahrheiten sagt
- IMMER DEUTSCH.

WICHTIG — das Hintergrundbild ist IMMER dieselbe wiederkehrende Figur:
Eine wunderschöne junge Frau, etwa 20 Jahre alt, lange blonde Haare, schlanke Figur, atemberaubend schönes Gesicht, blaue Augen, makellose Haut. Nur Umgebung, Pose, Outfit und Stimmung ändern sich zwischen Videos — die Frau selbst bleibt gleich.

Für image_prompt: Beginne IMMER mit der exakten Charakterbeschreibung (auf Englisch für die Bild-KI), dann variiere Szene/Stimmung passend zum Spruch. Beende IMMER mit: "cinematic Hollywood lighting, shot on ARRI Alexa, 85mm lens, shallow depth of field, professional color grading, ultra photorealistic, 8k, magazine cover quality".

Gib NUR gültiges JSON aus, kein Markdown:
{
  "title": "Kurzer knackiger Titel mit Emoji (max 55 Zeichen, Deutsch)",
  "image_prompt": "Beautiful young woman around 20 years old, long blonde hair, slim figure, stunning gorgeous face, blue eyes, flawless skin, [scene/outfit/mood], cinematic Hollywood lighting, shot on ARRI Alexa, 85mm lens, shallow depth of field, professional color grading, ultra photorealistic, 8k, magazine cover quality",
  "sentences": ["Hook", "Satz 2", "Satz 3", "Satz 4"],
  "tags": ["shorts", "viral", "motivation", "mindset", "gridphantom"]
}"""


def _sanitize_json(raw: str) -> str:
    raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
    raw = raw.strip()
    start = raw.find('{')
    end = raw.rfind('}') + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    return raw


class ScriptGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    def generate(self, topic: dict = None, language: str = 'de') -> dict:
        mode = os.environ.get('VIDEO_MODE', 'short')
        if mode == 'short':
            count = "2-3 Sätze — ultrakurz, unter 20 Sekunden gesprochen"
        else:
            count = "4-6 Sätze — 45-60 Sekunden gesprochen"

        user_prompt = f"""Erstelle einen viralen YouTube Short mit einem kraftvollen Spruch.
Generiere {count}. Jeder Satz MAX 8 WÖRTER.
Selbstbewusste, provokante Sprüche — was eine atemberaubende Frau sagt, das Männer zum Stoppen bringt.
Erster Satz ist der Hook. Mach ihn hart.
NUR DEUTSCH. Gib NUR gültiges JSON aus."""

        message = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_prompt}]
        )

        raw = message.content[0].text
        try:
            script = json.loads(raw)
        except json.JSONDecodeError:
            script = json.loads(_sanitize_json(raw))

        script['narration'] = " ".join(script.get('sentences', []))
        script['language'] = 'de'
        logger.info(f"Script: {script.get('title','?')} ({len(script.get('sentences',[]))} Sätze)")
        return script

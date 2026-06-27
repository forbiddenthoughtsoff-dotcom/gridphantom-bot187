#!/usr/bin/env python3
"""GridPhantom Bot v2 — German viral Shorts. Runs once, posts, exits."""
import os
import sys
import json
import re
import logging
import random
import urllib.parse
from io import BytesIO

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('GridPhantom')

W, H = 1080, 1920

# ---------------- SCRIPT GENERATION ----------------
SYSTEM_PROMPT = """Du bist ein viraler Content-Ersteller für deutsche YouTube Shorts. Deine Videos zeigen eine wunderschöne junge blonde Frau mit kraftvollen Sprüchen, die Männer zum Stoppen bringen.

Stil:
- Kraftvolle, provokante deutsche Sprüche über Leben, Erfolg, Geld, Beziehungen, Macht
- 2-3 kurze knackige Sätze, jeder MAX 8 WÖRTER
- Erster Satz ist der Hook
- Ton: selbstbewusst, roh, echt
- IMMER DEUTSCH

Gib NUR gültiges JSON aus:
{
  "title": "Kurzer Titel mit Emoji (max 55 Zeichen)",
  "sentences": ["Hook max 8 Wörter", "Satz 2", "Satz 3"],
  "tags": ["shorts", "viral", "motivation", "mindset", "fyp"]
}"""

def generate_script():
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "Erstelle einen viralen deutschen Spruch-Short. 2-3 Sätze, je max 8 Wörter. Nur JSON."}]
    )
    raw = msg.content[0].text
    raw = re.sub(r'^```json\s*|\s*```$', '', raw.strip(), flags=re.MULTILINE)
    start, end = raw.find('{'), raw.rfind('}') + 1
    script = json.loads(raw[start:end])
    script['narration'] = " ".join(script['sentences'])
    logger.info(f"Script: {script['title']}")
    return script

# ---------------- IMAGE (fixed blonde character) ----------------
CHARACTER = ("Beautiful young woman around 20 years old, long blonde hair, slim figure, "
             "stunning gorgeous face, blue eyes, flawless skin")
QUALITY = ("cinematic Hollywood lighting, shot on ARRI Alexa, 85mm lens, shallow depth of field, "
           "professional color grading, ultra photorealistic, 8k, magazine cover quality")

SCENES = [
    "standing by a window at night, city lights bokeh behind her",
    "elegant black dress, dark luxurious interior",
    "soft morning light, minimalist modern room",
    "confident pose, blurred neon background",
    "sitting in a luxury car, evening mood",
]

def get_image():
    from PIL import Image
    scene = random.choice(SCENES)
    prompt = f"{CHARACTER}, {scene}, {QUALITY}"
    encoded = urllib.parse.quote(prompt[:350])
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={W}&height={H}&nologo=true&model=flux&seed=7777"
    import requests
    r = requests.get(url, timeout=90, headers={'User-Agent': 'GridPhantom/2.0'})
    r.raise_for_status()
    img = Image.open(BytesIO(r.content)).convert('RGB')
    if img.size != (W, H):
        resample = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS
        img = img.resize((W, H), resample)
    logger.info(f"Image generated: {img.size}")
    return img

# ---------------- VOICE (German female) ----------------
def generate_voice(text, path='/tmp/voice.mp3'):
    import asyncio, edge_tts
    async def _gen():
        c = edge_tts.Communicate(text, 'de-DE-KatjaNeural', rate='+5%')
        await c.save(path)
    asyncio.run(_gen())
    logger.info(f"Voice: {os.path.getsize(path)} bytes")
    return path

# ---------------- VIDEO ASSEMBLY ----------------
def make_frame(bg, text):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    def font(sz):
        for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
            if os.path.exists(p):
                return ImageFont.truetype(p, sz)
        return ImageFont.load_default()

    frame = bg.copy().convert('RGBA')
    grad = Image.new('RGBA', (W, H), (0,0,0,0))
    gd = ImageDraw.Draw(grad)
    for y in range(int(H*0.45), H):
        a = int(200 * (y - H*0.45)/(H*0.55))
        gd.line([(0,y),(W,y)], fill=(0,0,0,a))
    frame = Image.alpha_composite(frame, grad).convert('RGB')
    draw = ImageDraw.Draw(frame)

    # Readable balanced font
    fs = 80
    maxw = int(W*0.85)
    def wrap(f):
        words, lines, cur = text.split(), [], ""
        for w in words:
            t = (cur+" "+w).strip()
            if draw.textbbox((0,0),t,font=f)[2] <= maxw:
                cur = t
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        return lines
    while fs > 56:
        f = font(fs)
        lines = wrap(f)
        if len(lines) <= 5: break
        fs -= 6
    f = font(fs)
    lines = wrap(f)
    lh = int(fs*1.2)
    total = len(lines)*lh
    sy = int(H*0.72) - total//2  # lower third

    for i, line in enumerate(lines):
        bb = draw.textbbox((0,0), line, font=f)
        x = (W-(bb[2]-bb[0]))//2
        y = sy + i*lh
        for dx in [-3,0,3]:
            for dy in [-3,0,3]:
                if dx or dy:
                    draw.text((x+dx,y+dy), line, font=f, fill=(0,0,0))
        draw.text((x,y), line, font=f, fill=(255,255,255))

    fb = font(44)
    brand = "@GridPhantom187"
    bw = draw.textbbox((0,0), brand, font=fb)[2]
    draw.text(((W-bw)//2, H-120), brand, font=fb, fill=(220,220,220))
    return np.array(frame)

def assemble(script, audio_path):
    from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
    bg = get_image()
    audio = AudioFileClip(audio_path)
    dur = min(audio.duration, 58)
    sentences = script['sentences']
    seg = dur/len(sentences)
    clips = []
    for i, s in enumerate(sentences):
        frame = make_frame(bg, s)
        start, end = i*seg, min((i+1)*seg, dur)
        clips.append(ImageClip(frame).set_duration(end-start).set_audio(audio.subclip(start,end)))
    final = concatenate_videoclips(clips).set_audio(audio.subclip(0,dur))
    out = '/tmp/video.mp4'
    final.write_videofile(out, fps=24, codec='libx264', audio_codec='aac',
                          threads=2, preset='medium', ffmpeg_params=['-crf','23'], logger=None)
    audio.close(); final.close()
    logger.info(f"Video: {os.path.getsize(out)//1024} KB")
    return out

# ---------------- YOUTUBE UPLOAD ----------------
def upload(video_path, script):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.auth.transport.requests import Request

    secrets = json.loads(os.environ['YOUTUBE_CLIENT_SECRETS'])
    creds = Credentials(
        token=secrets.get('token'),
        refresh_token=secrets['refresh_token'],
        token_uri='https://oauth2.googleapis.com/token',
        client_id=secrets['client_id'],
        client_secret=secrets['client_secret'],
        scopes=['https://www.googleapis.com/auth/youtube.upload']
    )
    creds.refresh(Request())
    yt = build('youtube', 'v3', credentials=creds)

    title = script['title'][:90]
    desc = script['narration'] + "\n\n" + " ".join(f"#{t}" for t in script.get('tags', []))
    body = {
        'snippet': {'title': title, 'description': desc[:4900],
                    'tags': script.get('tags', []), 'categoryId': '24'},
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype='video/mp4')
    req = yt.videos().insert(part='snippet,status', body=body, media_body=media)
    resp = req.execute()
    vid = resp['id']
    logger.info(f"✅ UPLOADED: https://youtube.com/shorts/{vid}")
    return vid

# ---------------- MAIN ----------------
def main():
    logger.info("="*50)
    logger.info("  GridPhantom v2 — Single Run")
    logger.info("="*50)
    try:
        script = generate_script()
        audio = generate_voice(script['narration'])
        video = assemble(script, audio)
        vid = upload(video, script)
        logger.info(f"✅ DONE: {vid}")
    except Exception as e:
        logger.error(f"❌ FAILED: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()

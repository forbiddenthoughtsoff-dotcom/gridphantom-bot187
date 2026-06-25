import requests
import urllib.parse
import os
import logging
import random
import time
from io import BytesIO
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
from config import Config

logger = logging.getLogger(__name__)

W, H = 1080, 1920
RESAMPLE = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS


def load_font(size):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def fetch_image(prompt: str) -> Image.Image:
    """
    Fetch background image. Strategy:
    1. Pollinations.ai (AI-generated, free, no key) — short prompt, fast model
    2. Unsplash Source (real photos, free, no key)
    3. Dark gradient fallback
    """
    # Strategy 1: Pollinations with turbo model (faster, less timeout risk)
    try:
        short_prompt = prompt[:200]
        encoded = urllib.parse.quote(short_prompt)
        url = (f"https://image.pollinations.ai/prompt/{encoded}"
               f"?width=1080&height=1920&nologo=true&model=flux&seed={random.randint(1,9999)}")
        r = requests.get(url, timeout=80, headers={'User-Agent': 'GridPhantomBot/1.0'})
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert('RGB')
        if img.size != (W, H):
            img = img.resize((W, H), RESAMPLE)
        logger.info(f"✅ Pollinations image: {img.size}")
        return img
    except Exception as e:
        logger.warning(f"Pollinations failed: {e}, trying Unsplash...")

    # Strategy 2: Unsplash Source (real photos, always fast)
    try:
        keywords = prompt.split(',')[0].strip().replace(' ', '+')[:50]
        url = f"https://source.unsplash.com/1080x1920/?{keywords}"
        r = requests.get(url, timeout=15, headers={'User-Agent': 'GridPhantomBot/1.0'})
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert('RGB')
        img = img.resize((W, H), RESAMPLE)
        logger.info(f"✅ Unsplash fallback: {img.size}")
        return img
    except Exception as e:
        logger.warning(f"Unsplash failed: {e}, using gradient")

    # Strategy 3: Dark gradient
    img = Image.new('RGB', (W, H), (15, 15, 25))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        v = int(15 + 25 * y / H)
        draw.line([(0, y), (W, y)], fill=(v, v, v + 15))
    return img


def make_frame(bg: Image.Image, text: str) -> np.ndarray:
    """Bold white text centered over background, with dark gradient for readability."""
    frame = bg.copy().convert('RGBA')

    # Dark gradient overlay bottom 60%
    grad = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(int(H * 0.35), H):
        alpha = int(195 * (y - H * 0.35) / (H * 0.65))
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    frame = Image.alpha_composite(frame, grad).convert('RGB')
    draw = ImageDraw.Draw(frame)

    font = load_font(92)
    max_w = int(W * 0.88)

    # Word wrap
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textbbox((0,0), test, font=font)[2] <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)

    line_h = 112
    total_h = len(lines) * line_h
    start_y = int(H * 0.58) - total_h // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2
        y = start_y + i * line_h
        # Strong black shadow for readability on any background
        for dx, dy in [(-4,-4),(4,-4),(-4,4),(4,4),(0,-5),(0,5),(-5,0),(5,0)]:
            draw.text((x+dx, y+dy), line, font=font, fill=(0,0,0,255))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

    # Branding
    font_b = load_font(42)
    brand = "@GridPhantom187"
    bw = draw.textbbox((0,0), brand, font=font_b)[2]
    draw.text(((W - bw)//2, H - 120), brand, font=font_b, fill=(210, 210, 210))

    return np.array(frame)


class VideoAssembler:
    def __init__(self):
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def assemble(self, script: dict, audio_path: str, topic: dict) -> str:
        language = script.get('language', 'en')
        output_path = f"{self.output_dir}/video_{language}_{random.randint(1000,9999)}.mp4"

        audio = AudioFileClip(audio_path)
        duration = min(audio.duration, 58)  # max 58s for Shorts compliance

        image_prompt = script.get('image_prompt', 'cinematic dramatic portrait')
        sentences = script.get('sentences', [])
        if not sentences:
            sentences = [script.get('narration', '')]

        logger.info(f"Fetching background image...")
        bg = fetch_image(image_prompt)

        seg_dur = duration / len(sentences)
        clips = []
        for i, sentence in enumerate(sentences):
            frame = make_frame(bg, sentence)
            start = i * seg_dur
            end = min((i + 1) * seg_dur, duration)
            c = ImageClip(frame).set_duration(end - start).set_audio(
                audio.subclip(start, end))
            clips.append(c)

        final = concatenate_videoclips(clips).set_audio(audio.subclip(0, duration))

        logger.info(f"Exporting {duration:.1f}s video ({len(sentences)} sentences)...")
        final.write_videofile(
            output_path, fps=24, codec='libx264',
            audio_codec='aac', threads=1, preset='ultrafast',
            ffmpeg_params=['-crf', '26'], logger=None
        )

        try:
            audio.close(); final.close()
        except Exception:
            pass

        logger.info(f"Video assembled: {output_path}")
        return output_path

import requests
import os
import logging
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy.editor import (
    ImageClip, AudioFileClip, CompositeVideoClip,
    concatenate_videoclips
)
from config import Config

logger = logging.getLogger(__name__)

# YouTube Shorts: 9:16 vertical
W, H = 1080, 1920

HIGHLIGHT_COLOR = (255, 220, 0)    # Yellow for keywords
TEXT_COLOR = (255, 255, 255)        # White main text
SHADOW_COLOR = (0, 0, 0)            # Black shadow
BG_OVERLAY = (0, 0, 0, 160)        # Dark overlay on background


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


def fetch_background_image(keyword: str) -> Image.Image:
    """Fetch a portrait photo from Pexels as background."""
    try:
        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": Config.PEXELS_API_KEY}
        params = {"query": keyword, "per_page": 5,
                  "orientation": "portrait", "size": "large"}
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        photos = r.json().get('photos', [])
        if photos:
            photo = random.choice(photos)
            img_url = photo['src']['large']
            img_data = requests.get(img_url, timeout=20).content
            from io import BytesIO
            img = Image.open(BytesIO(img_data)).convert('RGB')
            # Crop to 9:16
            target_w = int(img.height * 9 / 16)
            if target_w <= img.width:
                x = (img.width - target_w) // 2
                img = img.crop((x, 0, x + target_w, img.height))
            img = img.resize((W, H), Image.LANCZOS)
            logger.info(f"Background image fetched: {keyword}")
            return img
    except Exception as e:
        logger.error(f"Background fetch error: {e}")
    # Fallback: dark gradient
    img = Image.new('RGB', (W, H), (10, 10, 30))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        val = int(10 + 40 * (y / H))
        draw.line([(0, y), (W, y)], fill=(val, val, val + 20))
    return img


def draw_text_frame(bg: Image.Image, text: str,
                    title: str = "", subtitle: str = "") -> np.ndarray:
    """Draw one text frame over background image."""
    frame = bg.copy()

    # Dark overlay for readability
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([(0, H // 3), (W, H)], fill=(0, 0, 0, 180))
    frame = Image.alpha_composite(frame.convert('RGBA'), overlay).convert('RGB')

    draw = ImageDraw.Draw(frame)

    # Title (small, top area)
    if title:
        font_title = load_font(52)
        bbox = draw.textbbox((0, 0), title, font=font_title)
        tw = bbox[2] - bbox[0]
        tx = (W - tw) // 2
        ty = H // 3 + 40
        # Shadow
        draw.text((tx + 2, ty + 2), title, font=font_title, fill=(0, 0, 0))
        draw.text((tx, ty), title, font=font_title, fill=HIGHLIGHT_COLOR)

    # Main text (large, center)
    font_main = load_font(82)
    words = text.split()
    lines = []
    cur = ""
    max_w = int(W * 0.88)
    for w in words:
        test = (cur + " " + w).strip()
        bbox = draw.textbbox((0, 0), test, font=font_main)
        if bbox[2] - bbox[0] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    line_h = 96
    total_h = len(lines) * line_h
    start_y = H // 2 - total_h // 2 + 80

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_main)
        lw = bbox[2] - bbox[0]
        lx = (W - lw) // 2
        ly = start_y + i * line_h
        # Shadow
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3)]:
            draw.text((lx + dx, ly + dy), line, font=font_main, fill=SHADOW_COLOR)
        # Highlight first line yellow, rest white
        color = HIGHLIGHT_COLOR if i == 0 else TEXT_COLOR
        draw.text((lx, ly), line, font=font_main, fill=color)

    # Subtitle (small, bottom)
    if subtitle:
        font_sub = load_font(48)
        bbox = draw.textbbox((0, 0), subtitle, font=font_sub)
        sw = bbox[2] - bbox[0]
        sx = (W - sw) // 2
        sy = H - 220
        draw.text((sx + 2, sy + 2), subtitle, font=font_sub, fill=(0, 0, 0))
        draw.text((sx, sy), subtitle, font=font_sub, fill=(200, 200, 200))

    # GridPhantom branding bottom
    font_brand = load_font(38)
    brand = "@GridPhantom187"
    bbox = draw.textbbox((0, 0), brand, font=font_brand)
    bw = bbox[2] - bbox[0]
    draw.text(((W - bw) // 2, H - 120), brand, font=font_brand,
              fill=(150, 150, 150))

    return np.array(frame)


class VideoAssembler:
    def __init__(self):
        self.pexels_key = Config.PEXELS_API_KEY
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def assemble(self, script: dict, audio_path: str, topic: dict) -> str:
        language = script.get('language', 'en')
        mode = os.environ.get('VIDEO_MODE', 'short')
        output_path = f"{self.output_dir}/video_{language}_{random.randint(1000,9999)}.mp4"

        audio = AudioFileClip(audio_path)
        duration = audio.duration

        keyword = script.get('thumbnail_keyword', 'technology artificial intelligence')
        title = script.get('thumbnail_text', '')
        narration = script.get('narration', '')

        logger.info(f"Fetching background image for: {keyword}")
        bg = fetch_background_image(keyword)

        if mode == 'short':
            # Single frame with full narration text
            frame = draw_text_frame(bg, narration, title=title,
                                    subtitle=script.get('title', ''))
            clip = ImageClip(frame).set_duration(duration).set_audio(audio)

        else:
            # Long form: split narration into sentences, one frame each
            sentences = [s.strip() for s in narration.replace('!', '.').replace('?', '.').split('.') if s.strip()]
            if not sentences:
                sentences = [narration]

            seg_dur = duration / len(sentences)
            clips = []
            for i, sentence in enumerate(sentences):
                frame = draw_text_frame(bg, sentence, title=title if i == 0 else "")
                seg_audio = audio.subclip(i * seg_dur, min((i + 1) * seg_dur, duration))
                c = ImageClip(frame).set_duration(seg_dur).set_audio(seg_audio)
                clips.append(c)
            clip = concatenate_videoclips(clips)

        logger.info(f"Exporting video ({duration:.1f}s)...")
        clip.write_videofile(
            output_path, fps=24, codec='libx264',
            audio_codec='aac', threads=1,
            preset='ultrafast', logger=None
        )

        logger.info(f"Video assembled: {output_path}")
        return output_path

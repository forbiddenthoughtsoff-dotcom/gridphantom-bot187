import requests
import os
import logging
import random
from io import BytesIO
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    ImageClip, AudioFileClip, concatenate_videoclips
)
from config import Config

logger = logging.getLogger(__name__)

# YouTube Shorts: 9:16 vertical
W, H = 1080, 1920

HIGHLIGHT_COLOR = (255, 220, 0)    # Yellow for keywords
TEXT_COLOR = (255, 255, 255)       # White main text
SHADOW_COLOR = (0, 0, 0)           # Black shadow


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
        params = {"query": keyword, "per_page": 8,
                  "orientation": "portrait", "size": "large"}
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        photos = r.json().get('photos', [])
        if photos:
            photo = random.choice(photos)
            img_url = photo['src']['large']
            img_data = requests.get(img_url, timeout=20).content
            img = Image.open(BytesIO(img_data)).convert('RGB')
            target_w = int(img.height * 9 / 16)
            if target_w <= img.width:
                x = (img.width - target_w) // 2
                img = img.crop((x, 0, x + target_w, img.height))
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            img = img.resize((W, H), resample)
            # Darken the whole image so text is always readable
            dark = Image.new('RGB', (W, H), (0, 0, 0))
            img = Image.blend(img, dark, 0.55)
            logger.info(f"Background image fetched: {keyword}")
            return img
    except Exception as e:
        logger.error(f"Background fetch error: {e}")
    # Fallback: dark gradient
    img = Image.new('RGB', (W, H), (12, 12, 28))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        val = int(12 + 32 * (y / H))
        draw.line([(0, y), (W, y)], fill=(val, val, val + 18))
    return img


def wrap_text(draw, text, font, max_w):
    """Wrap text into lines that fit max_w."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_block_frame(bg, block_text, hook="", highlight_first=True):
    """Draw one readable text block, centered, over the background."""
    frame = bg.copy()
    draw = ImageDraw.Draw(frame)

    font_hook = load_font(72)
    font_main = load_font(76)
    max_w = int(W * 0.86)

    # Build wrapped lines for hook (yellow) and body
    hook_lines = wrap_text(draw, hook, font_hook, max_w) if hook else []
    body_lines = wrap_text(draw, block_text, font_main, max_w)

    line_h_hook = 92
    line_h_body = 100
    gap = 50

    total_h = len(hook_lines) * line_h_hook
    if hook_lines and body_lines:
        total_h += gap
    total_h += len(body_lines) * line_h_body

    y = (H - total_h) // 2

    # Draw hook (yellow, bold)
    for line in hook_lines:
        bbox = draw.textbbox((0, 0), line, font=font_hook)
        lw = bbox[2] - bbox[0]
        x = (W - lw) // 2
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, -3), (0, 3)]:
            draw.text((x + dx, y + dy), line, font=font_hook, fill=SHADOW_COLOR)
        draw.text((x, y), line, font=font_hook, fill=HIGHLIGHT_COLOR)
        y += line_h_hook

    if hook_lines and body_lines:
        y += gap

    # Draw body (white)
    for line in body_lines:
        bbox = draw.textbbox((0, 0), line, font=font_main)
        lw = bbox[2] - bbox[0]
        x = (W - lw) // 2
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, -3), (0, 3)]:
            draw.text((x + dx, y + dy), line, font=font_main, fill=SHADOW_COLOR)
        draw.text((x, y), line, font=font_main, fill=TEXT_COLOR)
        y += line_h_body

    # Branding bottom
    font_brand = load_font(40)
    brand = "@GridPhantom187"
    bbox = draw.textbbox((0, 0), brand, font=font_brand)
    bw = bbox[2] - bbox[0]
    draw.text(((W - bw) // 2 + 2, H - 118), brand, font=font_brand, fill=(0, 0, 0))
    draw.text(((W - bw) // 2, H - 120), brand, font=font_brand, fill=(180, 180, 180))

    return np.array(frame)


def split_into_blocks(narration, max_words=14):
    """Split narration into short readable blocks (by sentence, then by length)."""
    import re
    sentences = re.split(r'(?<=[.!?])\s+', narration.strip())
    blocks = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        words = s.split()
        if len(words) <= max_words:
            blocks.append(s)
        else:
            # Split long sentence into chunks
            for i in range(0, len(words), max_words):
                blocks.append(" ".join(words[i:i + max_words]))
    return blocks if blocks else [narration]


class VideoAssembler:
    def __init__(self):
        self.pexels_key = Config.PEXELS_API_KEY
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def assemble(self, script: dict, audio_path: str, topic: dict) -> str:
        language = script.get('language', 'en')
        output_path = f"{self.output_dir}/video_{language}_{random.randint(1000,9999)}.mp4"

        audio = AudioFileClip(audio_path)
        duration = audio.duration

        keyword = script.get('thumbnail_keyword', 'technology artificial intelligence')
        hook = script.get('thumbnail_text', '')
        narration = script.get('narration', '')

        logger.info(f"Fetching background image for: {keyword}")
        bg = fetch_background_image(keyword)

        # Split narration into readable blocks shown one after another
        blocks = split_into_blocks(narration)
        logger.info(f"Narration split into {len(blocks)} readable blocks")

        seg_dur = duration / len(blocks)
        clips = []
        for i, block in enumerate(blocks):
            # First block shows the yellow hook above the text
            frame = draw_block_frame(bg, block, hook=hook if i == 0 else "")
            start = i * seg_dur
            end = min((i + 1) * seg_dur, duration)
            seg_audio = audio.subclip(start, end)
            c = ImageClip(frame).set_duration(end - start).set_audio(seg_audio)
            clips.append(c)

        clip = concatenate_videoclips(clips)

        logger.info(f"Exporting video ({duration:.1f}s, {len(blocks)} blocks)...")
        clip.write_videofile(
            output_path, fps=24, codec='libx264',
            audio_codec='aac', threads=1,
            preset='ultrafast', logger=None
        )

        logger.info(f"Video assembled: {output_path}")
        return output_path

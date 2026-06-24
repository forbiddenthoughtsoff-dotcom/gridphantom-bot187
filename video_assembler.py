import requests
import urllib.parse
import os
import logging
import random
from io import BytesIO
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
from config import Config

logger = logging.getLogger(__name__)

W, H = 1080, 1920


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


def generate_background(image_prompt: str) -> Image.Image:
    """Generate a cinematic background image via Pollinations."""
    try:
        encoded = urllib.parse.quote(image_prompt[:800])
        url = f"https://image.pollinations.ai/prompt/{encoded}?width={W}&height={H}&nologo=true&seed={random.randint(1,99999)}"
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=60)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert('RGB')
        resample = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS
        if img.size != (W, H):
            img = img.resize((W, H), resample)
        logger.info(f"Background generated: {img.size}")
        return img
    except Exception as e:
        logger.error(f"Background error: {e}")
        img = Image.new('RGB', (W, H), (20, 20, 20))
        return img


def draw_text_on_frame(bg: Image.Image, text: str) -> np.ndarray:
    """Draw bold white text centered over the background image."""
    frame = bg.copy()
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    # Dark gradient at bottom half for readability
    for y in range(H // 2, H):
        alpha = int(180 * (y - H // 2) / (H // 2))
        draw_ov.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    frame = Image.alpha_composite(frame.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(frame)

    font = load_font(88)
    max_w = int(W * 0.88)
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

    line_h = 108
    total_h = len(lines) * line_h
    # Position: center of bottom half
    start_y = int(H * 0.55) - total_h // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = (W - lw) // 2
        y = start_y + i * line_h
        # Strong shadow for readability
        for dx, dy in [(-4,-4),(4,-4),(-4,4),(4,4),(0,-4),(0,4),(-4,0),(4,0)]:
            draw.text((x+dx, y+dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))

    # Branding
    font_brand = load_font(44)
    brand = "@GridPhantom187"
    bbox = draw.textbbox((0, 0), brand, font=font_brand)
    bw = bbox[2] - bbox[0]
    draw.text(((W-bw)//2, H-130), brand, font=font_brand, fill=(200, 200, 200))

    return np.array(frame)


class VideoAssembler:
    def __init__(self):
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def assemble(self, script: dict, audio_path: str, topic: dict) -> str:
        language = script.get('language', 'en')
        output_path = f"{self.output_dir}/video_{language}_{random.randint(1000,9999)}.mp4"

        audio = AudioFileClip(audio_path)
        duration = audio.duration

        # Generate ONE cinematic background image for the whole video
        image_prompt = script.get('image_prompt', 'cinematic dramatic portrait, moody lighting')
        logger.info(f"Generating background image...")
        bg = generate_background(image_prompt)

        # Split sentences — each gets its own text frame over the same background
        sentences = script.get('sentences', [script.get('narration', '')])
        if not sentences:
            sentences = [script.get('narration', '')]

        seg_dur = duration / len(sentences)
        clips = []
        for i, sentence in enumerate(sentences):
            frame = draw_text_on_frame(bg, sentence)
            start = i * seg_dur
            end = min((i + 1) * seg_dur, duration)
            seg_audio = audio.subclip(start, end)
            clip = ImageClip(frame).set_duration(end - start).set_audio(seg_audio)
            clips.append(clip)

        final = concatenate_videoclips(clips).set_audio(audio).set_duration(duration)

        logger.info(f"Exporting {duration:.1f}s video ({len(sentences)} sentences)...")
        final.write_videofile(
            output_path, fps=24, codec='libx264',
            audio_codec='aac', threads=1, preset='ultrafast',
            ffmpeg_params=['-crf', '26'], logger=None
        )

        try:
            audio.close()
            final.close()
        except Exception:
            pass

        logger.info(f"Video assembled: {output_path}")
        return output_path

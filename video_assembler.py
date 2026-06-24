import requests
import urllib.parse
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

W, H = 720, 1280
HIGHLIGHT_COLOR = (255, 220, 0)
TEXT_COLOR = (255, 255, 255)


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


def generate_ai_image(prompt: str, seed: int = None) -> Image.Image:
    """Generate a Pixar-style image via Pollinations.ai (free, no key)."""
    try:
        encoded = urllib.parse.quote(prompt[:900])
        url = f"https://image.pollinations.ai/prompt/{encoded}?width={W}&height={H}&nologo=true"
        if seed is not None:
            url += f"&seed={seed}"
        req = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=90)
        req.raise_for_status()
        img = Image.open(BytesIO(req.content)).convert('RGB')
        if img.size != (W, H):
            img = img.resize((W, H), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
        return img
    except Exception as e:
        logger.error(f"AI image error: {e}")
        img = Image.new('RGB', (W, H), (15, 12, 30))
        return img


def wrap_text(draw, text, font, max_w):
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


def add_text_to_image(img: Image.Image, onscreen_text: str, is_hook=False) -> np.ndarray:
    """Burn on-screen text onto the image (bottom third)."""
    frame = img.copy()
    draw = ImageDraw.Draw(frame)

    if not onscreen_text:
        return np.array(frame)

    font = load_font(58 if is_hook else 50)
    max_w = int(W * 0.88)
    lines = wrap_text(draw, onscreen_text, font, max_w)
    line_h = 70
    total_h = len(lines) * line_h

    # Position: hook center, body lower third
    start_y = (H - total_h) // 2 if is_hook else int(H * 0.70) - total_h

    # Dark band behind text
    band = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    pad = 24
    bd.rectangle([(0, start_y - pad), (W, start_y + total_h + pad)],
                 fill=(0, 0, 0, 140))
    frame = Image.alpha_composite(frame.convert('RGBA'), band).convert('RGB')
    draw = ImageDraw.Draw(frame)

    y = start_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, -3), (0, 3)]:
            draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font,
                  fill=HIGHLIGHT_COLOR if is_hook else TEXT_COLOR)
        y += line_h

    # Branding
    font_brand = load_font(28)
    brand = "@GridPhantom187"
    bbox = draw.textbbox((0, 0), brand, font=font_brand)
    draw.text(((W - (bbox[2] - bbox[0])) // 2, H - 70), brand,
              font=font_brand, fill=(190, 190, 190))

    return np.array(frame)


def zoom_clip(frame_array, duration, zoom_start=1.0, zoom_end=1.08):
    """Create an ImageClip with a slow zoom (Ken Burns) effect."""
    clip = ImageClip(frame_array).set_duration(duration)

    def scaler(t):
        return zoom_start + (zoom_end - zoom_start) * (t / duration)

    return clip.resize(scaler).resize((W, H))


class VideoAssembler:
    def __init__(self):
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def assemble(self, script: dict, audio_path: str, topic: dict) -> str:
        language = script.get('language', 'en')
        output_path = f"{self.output_dir}/video_{language}_{random.randint(1000,9999)}.mp4"

        audio = AudioFileClip(audio_path)
        duration = audio.duration

        scenes = script.get('scenes', [])
        if not scenes:
            # Fallback: single scene from narration
            scenes = [{'image_prompt': script.get('thumbnail_keyword', 'technology'),
                       'onscreen_text': script.get('thumbnail_text', ''),
                       'segment': 'hook'}]

        seg_dur = duration / len(scenes)
        seed = random.randint(1, 999999)  # same seed base for character consistency

        clips = []
        for i, scene in enumerate(scenes):
            prompt = scene.get('image_prompt', '')
            onscreen = scene.get('onscreen_text', '')
            is_hook = scene.get('segment', '') == 'hook' or i == 0

            logger.info(f"Scene {i+1}/{len(scenes)}: generating image...")
            img = generate_ai_image(prompt, seed=seed + i)
            frame = add_text_to_image(img, onscreen, is_hook=is_hook)

            start = i * seg_dur
            end = min((i + 1) * seg_dur, duration)
            seg_audio = audio.subclip(start, end)

            clip = zoom_clip(frame, end - start).set_audio(seg_audio)
            clips.append(clip)

        final = concatenate_videoclips(clips)
        final = final.set_audio(audio).set_duration(duration)

        logger.info(f"Exporting video ({duration:.1f}s, {len(scenes)} scenes)...")
        final.write_videofile(
            output_path, fps=24, codec='libx264',
            audio_codec='aac', threads=1, preset='ultrafast',
            ffmpeg_params=['-crf', '28'], logger=None
        )

        try:
            audio.close()
            final.close()
        except Exception:
            pass

        logger.info(f"Video assembled: {output_path}")
        return output_path

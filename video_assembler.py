import os
import logging
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
from image_generator import get_background_image

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


def make_frame(bg: Image.Image, text: str) -> np.ndarray:
    """HUGE bold white text centered. Text takes ~1/3 of frame."""
    frame = bg.copy().convert('RGBA')

    # Dark gradient overlay bottom half — makes text readable on any background
    grad = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(int(H * 0.25), H):
        alpha = int(220 * (y - H * 0.25) / (H * 0.75))
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    frame = Image.alpha_composite(frame, grad).convert('RGB')
    draw = ImageDraw.Draw(frame)

    # MASSIVE font - target ~1/3 of frame height for text block
    # Start big and shrink only if absolutely needed
    font_size = 150
    max_w = int(W * 0.92)

    def wrap_text(font, size):
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

    # Shrink font until text fits in 4 lines max
    while font_size > 80:
        font = load_font(font_size)
        lines = wrap_text(font, font_size)
        if len(lines) <= 4:
            break
        font_size -= 10

    font = load_font(font_size)
    lines = wrap_text(font, font_size)
    line_h = int(font_size * 1.15)
    total_h = len(lines) * line_h
    start_y = (H - total_h) // 2  # Vertically centered

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2
        y = start_y + i * line_h
        # Strong shadow for max readability
        shadow_offset = max(6, font_size // 20)
        for dx in [-shadow_offset, 0, shadow_offset]:
            for dy in [-shadow_offset, 0, shadow_offset]:
                if dx or dy:
                    draw.text((x+dx, y+dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))

    # Branding bottom
    fb = load_font(48)
    brand = "@GridPhantom187"
    bw = draw.textbbox((0, 0), brand, font=fb)[2]
    draw.text(((W - bw)//2, H - 130), brand, font=fb, fill=(220, 220, 220))

    return np.array(frame)


class VideoAssembler:
    def __init__(self):
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def assemble(self, script: dict, audio_path: str, topic: dict) -> str:
        output_path = f"{self.output_dir}/video_en_{random.randint(1000,9999)}.mp4"

        audio = AudioFileClip(audio_path)
        duration = min(audio.duration, 58)

        image_prompt = script.get('image_prompt', 'beautiful attractive woman, cinematic')
        sentences = script.get('sentences', [script.get('narration', '')])
        if not sentences:
            sentences = [script.get('narration', '')]

        logger.info("Fetching background image...")
        bg = get_background_image(image_prompt)

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

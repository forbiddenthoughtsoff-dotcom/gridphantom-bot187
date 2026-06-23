import requests
import os
import logging
import random
from io import BytesIO
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip, ImageClip, AudioFileClip,
    CompositeVideoClip, concatenate_videoclips
)
from config import Config

logger = logging.getLogger(__name__)

# YouTube vertical 9:16 — but process at LOW res to save RAM, no upscaling
W, H = 720, 1280          # processing resolution (RAM-friendly)
HIGHLIGHT_COLOR = (255, 220, 0)
TEXT_COLOR = (255, 255, 255)
SHADOW_COLOR = (0, 0, 0)


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


def fetch_background_video(keyword: str, out_path: str) -> str:
    """Download ONE small SD portrait video from Pexels. RAM-friendly."""
    try:
        url = "https://api.pexels.com/videos/search"
        headers = {"Authorization": Config.PEXELS_API_KEY}
        params = {"query": keyword, "per_page": 10,
                  "orientation": "portrait", "size": "small"}
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        videos = r.json().get('videos', [])
        if not videos:
            return None
        video = random.choice(videos)
        # Pick the smallest file that is at least 600px wide (SD, low RAM)
        files = sorted(video.get('video_files', []),
                       key=lambda f: f.get('width') or 9999)
        chosen = None
        for f in files:
            if (f.get('width') or 0) >= 540:
                chosen = f
                break
        if not chosen and files:
            chosen = files[0]
        if not chosen:
            return None
        link = chosen['link']
        data = requests.get(link, timeout=30).content
        with open(out_path, 'wb') as fh:
            fh.write(data)
        logger.info(f"Background video downloaded: {keyword} ({chosen.get('width')}x{chosen.get('height')})")
        return out_path
    except Exception as e:
        logger.error(f"Video fetch error: {e}")
        return None


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


def make_text_overlay(block_text, hook=""):
    """Create a transparent RGBA text overlay (PNG) at processing resolution."""
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Semi-transparent dark band behind text for readability
    band = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    bd.rectangle([(0, int(H * 0.28)), (W, int(H * 0.78))], fill=(0, 0, 0, 130))
    overlay = Image.alpha_composite(overlay, band)
    draw = ImageDraw.Draw(overlay)

    font_hook = load_font(54)
    font_main = load_font(52)
    max_w = int(W * 0.86)

    hook_lines = wrap_text(draw, hook, font_hook, max_w) if hook else []
    body_lines = wrap_text(draw, block_text, font_main, max_w)

    lh_hook, lh_body, gap = 66, 70, 36
    total_h = len(hook_lines) * lh_hook + (gap if hook_lines and body_lines else 0) + len(body_lines) * lh_body
    y = (H - total_h) // 2

    for line in hook_lines:
        bbox = draw.textbbox((0, 0), line, font=font_hook)
        x = (W - (bbox[2] - bbox[0])) // 2
        for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (0, -2), (0, 2)]:
            draw.text((x + dx, y + dy), line, font=font_hook, fill=(0, 0, 0, 255))
        draw.text((x, y), line, font=font_hook, fill=HIGHLIGHT_COLOR + (255,))
        y += lh_hook
    if hook_lines and body_lines:
        y += gap
    for line in body_lines:
        bbox = draw.textbbox((0, 0), line, font=font_main)
        x = (W - (bbox[2] - bbox[0])) // 2
        for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (0, -2), (0, 2)]:
            draw.text((x + dx, y + dy), line, font=font_main, fill=(0, 0, 0, 255))
        draw.text((x, y), line, font=font_main, fill=TEXT_COLOR + (255,))
        y += lh_body

    # Branding
    font_brand = load_font(30)
    brand = "@GridPhantom187"
    bbox = draw.textbbox((0, 0), brand, font=font_brand)
    bw = bbox[2] - bbox[0]
    draw.text(((W - bw) // 2, H - 90), brand, font=font_brand, fill=(190, 190, 190, 255))

    return np.array(overlay)


def split_into_blocks(narration, max_words=12):
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
            for i in range(0, len(words), max_words):
                blocks.append(" ".join(words[i:i + max_words]))
    return blocks if blocks else [narration]


def prepare_bg_clip(video_path, duration):
    """Load bg video, crop to 9:16, resize to processing res, loop to duration."""
    clip = VideoFileClip(video_path, audio=False, target_resolution=(H, None))
    # Crop center to 9:16
    if clip.w / clip.h > W / H:
        new_w = int(clip.h * W / H)
        x1 = (clip.w - new_w) // 2
        clip = clip.crop(x1=x1, y1=0, x2=x1 + new_w, y2=clip.h)
    else:
        new_h = int(clip.w * H / W)
        y1 = (clip.h - new_h) // 2
        clip = clip.crop(x1=0, y1=y1, x2=clip.w, y2=y1 + new_h)
    clip = clip.resize((W, H))
    # Loop to fill duration
    if clip.duration < duration:
        n = int(duration / clip.duration) + 1
        clip = concatenate_videoclips([clip] * n)
    return clip.subclip(0, duration)


class VideoAssembler:
    def __init__(self):
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def assemble(self, script: dict, audio_path: str, topic: dict) -> str:
        language = script.get('language', 'en')
        output_path = f"{self.output_dir}/video_{language}_{random.randint(1000,9999)}.mp4"

        audio = AudioFileClip(audio_path)
        duration = audio.duration

        keyword = script.get('thumbnail_keyword', 'futuristic technology abstract')
        hook = script.get('thumbnail_text', '')
        narration = script.get('narration', '')

        blocks = split_into_blocks(narration)
        logger.info(f"Narration -> {len(blocks)} blocks")

        # Try to get a moving background video
        bg_path = fetch_background_video(keyword, "/tmp/bg_raw.mp4")

        try:
            if bg_path:
                bg_clip = prepare_bg_clip(bg_path, duration)
            else:
                raise RuntimeError("no bg video")
        except Exception as e:
            logger.error(f"BG video prep failed ({e}), using dark fallback")
            from moviepy.editor import ColorClip
            bg_clip = ColorClip(size=(W, H), color=(12, 12, 28)).set_duration(duration)

        # Build text overlays per block, timed to the narration
        seg_dur = duration / len(blocks)
        overlay_clips = []
        for i, block in enumerate(blocks):
            arr = make_text_overlay(block, hook=hook if i == 0 else "")
            start = i * seg_dur
            end = min((i + 1) * seg_dur, duration)
            oc = (ImageClip(arr)
                  .set_start(start)
                  .set_duration(end - start))
            overlay_clips.append(oc)

        final = CompositeVideoClip([bg_clip] + overlay_clips, size=(W, H))
        final = final.set_audio(audio).set_duration(duration)

        logger.info(f"Exporting video ({duration:.1f}s, {len(blocks)} blocks) at {W}x{H}...")
        final.write_videofile(
            output_path, fps=24, codec='libx264',
            audio_codec='aac', threads=1, preset='ultrafast',
            ffmpeg_params=['-crf', '28'], logger=None
        )

        # Cleanup
        try:
            bg_clip.close()
            audio.close()
            final.close()
            if bg_path and os.path.exists(bg_path):
                os.remove(bg_path)
        except Exception:
            pass

        logger.info(f"Video assembled: {output_path}")
        return output_path

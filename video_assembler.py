# -*- coding: utf-8 -*-
import os
import logging
import random
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (VideoClip, AudioFileClip, ImageClip,
                            VideoFileClip, CompositeVideoClip,
                            concatenate_videoclips, vfx)
from image_generator import get_background_image

logger = logging.getLogger(__name__)

W, H = 1080, 1920
ZOOM = 0.10  # Ken-Burns zoom range per sentence (10%)


def load_font(size):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    # load_default() ignores size unless passed explicitly (Pillow >= 10.1);
    # without it text renders ~10px no matter what size was requested
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_overlay(text: str):
    """Static foreground layer (gradient + text + branding) as RGBA arrays.
    Kept separate from the background so the background can move while
    the text stays rock-steady and readable."""
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(layer)

    # Dark gradient bottom half — makes text readable on any background
    for y in range(int(H * 0.25), H):
        alpha = int(220 * (y - H * 0.25) / (H * 0.75))
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    draw = gd

    # Balanced readable font - clear without dominating the image
    font_size = 80
    max_w = int(W * 0.85)

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

    while font_size > 56:
        font = load_font(font_size)
        lines = wrap_text(font, font_size)
        if len(lines) <= 5:
            break
        font_size -= 6

    font = load_font(font_size)
    lines = wrap_text(font, font_size)
    line_h = int(font_size * 1.15)
    total_h = len(lines) * line_h
    start_y = int(H * 0.68) - total_h // 2  # Lower third

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2
        y = start_y + i * line_h
        # Strong shadow for max readability
        shadow_offset = max(6, font_size // 20)
        for dx in [-shadow_offset, 0, shadow_offset]:
            for dy in [-shadow_offset, 0, shadow_offset]:
                if dx or dy:
                    draw.text((x+dx, y+dy), line, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

    # Branding bottom
    fb = load_font(48)
    brand = "@GridPhantom187"
    bw = draw.textbbox((0, 0), brand, font=fb)[2]
    draw.text(((W - bw)//2, H - 130), brand, font=fb, fill=(220, 220, 220, 255))

    arr = np.asarray(layer, dtype=np.float32)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3:4] / 255.0
    return rgb, alpha


def make_kb_clip(bg_big: np.ndarray, text: str, duration: float,
                 zoom_in: bool) -> VideoClip:
    """Ken-Burns segment: background slowly zooms while the text overlay
    stays static — motion holds attention better than a still frame."""
    H2, W2 = bg_big.shape[:2]
    rgb, alpha = make_overlay(text)
    inv_alpha = 1.0 - alpha
    overlay_pre = rgb * alpha

    def frame(t):
        p = min(t / duration, 1.0) if duration > 0 else 0.0
        s = 1.0 + ZOOM * p if zoom_in else 1.0 + ZOOM * (1.0 - p)
        cw, ch = int(W2 / s), int(H2 / s)
        x0, y0 = (W2 - cw) // 2, (H2 - ch) // 2
        crop = Image.fromarray(bg_big[y0:y0 + ch, x0:x0 + cw])
        base = np.asarray(crop.resize((W, H), Image.BILINEAR),
                          dtype=np.float32)
        return (base * inv_alpha + overlay_pre).astype('uint8')

    return VideoClip(frame, duration=duration)


def fetch_pexels_video(query: str) -> str:
    """Free stock video background from Pexels (needs PEXELS_API_KEY).
    Returns a local mp4 path or None."""
    key = os.environ.get('PEXELS_API_KEY', '')
    if not key:
        return None
    r = requests.get(
        'https://api.pexels.com/videos/search',
        params={'query': query, 'orientation': 'portrait', 'per_page': 15},
        headers={'Authorization': key}, timeout=20)
    r.raise_for_status()
    videos = r.json().get('videos', [])
    random.shuffle(videos)
    for v in videos:
        files = sorted(v.get('video_files', []),
                       key=lambda f: abs((f.get('height') or 0) - H))
        for f in files:
            if (f.get('height') or 0) >= 1080 and f.get('link'):
                path = '/tmp/bg_video.mp4'
                data = requests.get(f['link'], timeout=90).content
                with open(path, 'wb') as fh:
                    fh.write(data)
                logger.info(f"🎥 Pexels footage: '{query}' "
                            f"({f.get('width')}x{f.get('height')})")
                return path
    return None


class VideoAssembler:
    def __init__(self):
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def assemble(self, script: dict, audio_path: str) -> str:
        output_path = f"{self.output_dir}/video_en_{random.randint(1000,9999)}.mp4"

        audio = AudioFileClip(audio_path)
        duration = min(audio.duration, 58)

        image_prompt = script.get('image_prompt', 'abstract futuristic technology visual, circuit boards, glowing data streams, cinematic lighting, ultra detailed')
        sentences = script.get('sentences', [script.get('narration', '')])
        if not sentences:
            sentences = [script.get('narration', '')]

        seg_dur = duration / len(sentences)

        # Preferred background: real stock footage — the script supplies an
        # English search query (Pexels search works poorly in German)
        base = None
        try:
            query = script.get('pexels_query') or "futuristic technology abstract"
            bg_path = fetch_pexels_video(query)
            if bg_path:
                base = VideoFileClip(bg_path).without_audio()
                scale = max(W / base.w, H / base.h)
                base = base.resize(scale).crop(
                    x_center=base.w * scale / 2, y_center=base.h * scale / 2,
                    width=W, height=H)
                if base.duration < duration:
                    base = base.fx(vfx.loop, duration=duration)
                else:
                    base = base.subclip(0, duration)
        except Exception as e:
            logger.warning(f"Stock footage unavailable, falling back: {e}")
            base = None

        if base is not None:
            overlays = []
            for i, sentence in enumerate(sentences):
                start = i * seg_dur
                end = min((i + 1) * seg_dur, duration)
                rgb, alpha = make_overlay(sentence)
                oc = (ImageClip(rgb.astype('uint8'))
                      .set_mask(ImageClip(alpha[:, :, 0], ismask=True))
                      .set_start(start).set_duration(end - start))
                overlays.append(oc)
            final = CompositeVideoClip([base] + overlays).set_audio(
                audio.subclip(0, duration))
        else:
            # Fallback: AI image with Ken-Burns motion
            logger.info("Fetching background image...")
            bg = get_background_image(image_prompt)
            big_w, big_h = int(W * (1 + ZOOM)), int(H * (1 + ZOOM))
            bg_big = np.asarray(bg.resize((big_w, big_h), Image.LANCZOS))

            clips = []
            for i, sentence in enumerate(sentences):
                start = i * seg_dur
                end = min((i + 1) * seg_dur, duration)
                c = make_kb_clip(bg_big, sentence, end - start,
                                 zoom_in=(i % 2 == 0)).set_audio(
                    audio.subclip(start, end))
                clips.append(c)
            final = concatenate_videoclips(clips).set_audio(
                audio.subclip(0, duration))

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

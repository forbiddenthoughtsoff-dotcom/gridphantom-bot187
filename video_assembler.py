import requests
import os
import logging
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeVideoClip,
    ColorClip, ImageClip
)
from config import Config

logger = logging.getLogger(__name__)

# YouTube Shorts: 9:16 vertical format
SHORTS_W = 1080
SHORTS_H = 1920


def _make_text_image(text, size=(SHORTS_W, SHORTS_H), fontsize=90):
    """PIL text rendering — no ImageMagick needed."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = None
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, fontsize)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    max_w = int(size[0] * 0.85)
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

    line_heights = []
    for ln in lines:
        bbox = draw.textbbox((0, 0), ln, font=font)
        line_heights.append(bbox[3] - bbox[1])
    total_h = sum(line_heights) + (len(lines) - 1) * 16
    y = (size[1] - total_h) // 2

    for ln, lh in zip(lines, line_heights):
        bbox = draw.textbbox((0, 0), ln, font=font)
        w = bbox[2] - bbox[0]
        x = (size[0] - w) // 2
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3)]:
            draw.text((x + dx, y + dy), ln, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255))
        y += lh + 16

    return np.array(img)


class VideoAssembler:
    def __init__(self):
        self.pexels_key = Config.PEXELS_API_KEY
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def fetch_stock_videos(self, keyword: str) -> list:
        url = "https://api.pexels.com/videos/search"
        headers = {"Authorization": self.pexels_key}
        params = {"query": keyword, "per_page": 5,
                  "size": "small", "orientation": "portrait"}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            videos = response.json().get('videos', [])
            urls = []
            for v in videos:
                files = v.get('video_files', [])
                sd = [f for f in files if f.get('quality') in ('sd', 'hd')]
                if sd:
                    urls.append(sd[0]['link'])
                elif files:
                    urls.append(files[0]['link'])
            return urls
        except Exception as e:
            logger.error(f"Pexels fetch error: {e}")
            return []

    def download_video(self, url: str, path: str) -> str:
        r = requests.get(url, stream=True, timeout=30)
        with open(path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return path

    def assemble(self, script: dict, audio_path: str, topic: dict) -> str:
        keyword = script.get('thumbnail_keyword', 'technology')
        language = script.get('language', 'en')
        output_path = f"{self.output_dir}/short_{language}_{random.randint(1000,9999)}.mp4"

        audio = AudioFileClip(audio_path)
        mode = os.environ.get('VIDEO_MODE', 'short')
        max_dur = 45 if mode == 'short' else 180  # 45s for shorts, 3min for long
        total_duration = min(audio.duration, max_dur)

        logger.info(f"Fetching portrait stock video for: {keyword}")
        video_urls = self.fetch_stock_videos(keyword)

        if video_urls:
            try:
                dl_path = "/tmp/stock_0.mp4"
                self.download_video(video_urls[0], dl_path)
                clip = VideoFileClip(dl_path)

                # Crop to 9:16 portrait
                target_w = int(clip.h * 9 / 16)
                if target_w <= clip.w:
                    x1 = (clip.w - target_w) // 2
                    clip = clip.crop(x1=x1, y1=0, x2=x1+target_w, y2=clip.h)
                clip = clip.resize((SHORTS_W, SHORTS_H))

                # Loop if needed
                if clip.duration < total_duration:
                    loops = int(total_duration / clip.duration) + 1
                    from moviepy.editor import concatenate_videoclips
                    clip = concatenate_videoclips([clip] * loops)
                clip = clip.subclip(0, total_duration).set_audio(audio.subclip(0, total_duration))

                # Title overlay at top
                title_arr = _make_text_image(script.get('thumbnail_text', ''),
                                             size=(SHORTS_W, 300), fontsize=80)
                title_clip = (ImageClip(title_arr)
                              .set_duration(total_duration)
                              .set_position(('center', 100)))
                video = CompositeVideoClip([clip, title_clip], size=(SHORTS_W, SHORTS_H))

                logger.info(f"Exporting Short ({total_duration:.1f}s)...")
                video.write_videofile(output_path, fps=30, codec='libx264',
                                      audio_codec='aac', threads=1,
                                      preset='ultrafast', logger=None)
                try:
                    os.remove(dl_path)
                except:
                    pass
                logger.info(f"Short assembled: {output_path}")
                return output_path
            except Exception as e:
                logger.error(f"Stock video error: {e}")

        # Fallback: dark background
        return self._create_fallback_short(script, audio, total_duration, output_path)

    def _create_fallback_short(self, script, audio, duration, output_path):
        bg = ColorClip(size=(SHORTS_W, SHORTS_H), color=[10, 10, 30]).set_duration(duration)
        arr = _make_text_image(script.get('thumbnail_text', 'GridPhantom'))
        title = ImageClip(arr).set_duration(duration).set_position('center')
        video = CompositeVideoClip([bg, title], size=(SHORTS_W, SHORTS_H))
        video = video.set_audio(audio.subclip(0, duration))
        video.write_videofile(output_path, fps=30, codec='libx264',
                              audio_codec='aac', threads=1,
                              preset='ultrafast', logger=None)
        logger.info(f"Fallback Short assembled: {output_path}")
        return output_path

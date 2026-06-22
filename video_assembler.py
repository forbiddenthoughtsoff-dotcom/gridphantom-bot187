import requests
import os
import logging
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeVideoClip,
    concatenate_videoclips, ColorClip, ImageClip
)
from config import Config

logger = logging.getLogger(__name__)


def _make_text_image(text, size=(1920, 1080), fontsize=80):
    """Render centered text to a transparent PNG using PIL (no ImageMagick)."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Try to load a bundled truetype font, fall back to default
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

    # Word-wrap to fit width
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

    # Vertical centering
    line_heights = []
    for ln in lines:
        bbox = draw.textbbox((0, 0), ln, font=font)
        line_heights.append(bbox[3] - bbox[1])
    total_h = sum(line_heights) + (len(lines) - 1) * 20
    y = (size[1] - total_h) // 2

    for ln, lh in zip(lines, line_heights):
        bbox = draw.textbbox((0, 0), ln, font=font)
        w = bbox[2] - bbox[0]
        x = (size[0] - w) // 2
        # outline for readability
        for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:
            draw.text((x + dx, y + dy), ln, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255))
        y += lh + 20

    return np.array(img)


class VideoAssembler:
    def __init__(self):
        self.pexels_key = Config.PEXELS_API_KEY
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def fetch_stock_videos(self, keyword: str, count: int = 10) -> list:
        url = "https://api.pexels.com/videos/search"
        headers = {"Authorization": self.pexels_key}
        params = {"query": keyword, "per_page": count,
                  "size": "medium", "orientation": "landscape"}
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            videos = response.json().get('videos', [])
            video_urls = []
            for v in videos:
                files = v.get('video_files', [])
                hd = [f for f in files if f.get('quality') == 'hd']
                if hd:
                    video_urls.append(hd[0]['link'])
                elif files:
                    video_urls.append(files[0]['link'])
            return video_urls
        except Exception as e:
            logger.error(f"Pexels fetch error: {e}")
            return []

    def download_video(self, url: str, path: str) -> str:
        response = requests.get(url, stream=True)
        with open(path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return path

    def _title_overlay(self, text, duration, size=(1920, 1080)):
        """Build a moviepy ImageClip from PIL-rendered text."""
        arr = _make_text_image(text, size=size, fontsize=80)
        return ImageClip(arr).set_duration(duration)

    def assemble(self, script: dict, audio_path: str, topic: dict) -> str:
        keyword = script.get('thumbnail_keyword', 'artificial intelligence technology')
        language = script.get('language', 'en')
        output_path = f"{self.output_dir}/final_{language}_{random.randint(1000,9999)}.mp4"

        logger.info(f"Fetching stock videos for: {keyword}")
        video_urls = self.fetch_stock_videos(keyword, count=15)

        if not video_urls:
            logger.warning("No stock videos found, using fallback")
            return self._create_fallback_video(script, audio_path, output_path)

        audio = AudioFileClip(audio_path)
        total_duration = audio.duration

        clips, downloaded = [], []
        for i, url in enumerate(video_urls[:8]):
            try:
                dl_path = f"/tmp/stock_{i}.mp4"
                self.download_video(url, dl_path)
                downloaded.append(dl_path)
                clip = VideoFileClip(dl_path).resize((1920, 1080))
                seg_duration = min(12, clip.duration)
                clip = clip.subclip(0, seg_duration)
                clips.append(clip)
            except Exception as e:
                logger.error(f"Error processing clip {i}: {e}")

        if not clips:
            return self._create_fallback_video(script, audio_path, output_path)

        final_clips = []
        current_duration = 0
        while current_duration < total_duration:
            for clip in clips:
                if current_duration >= total_duration:
                    break
                final_clips.append(clip)
                current_duration += clip.duration

        video = concatenate_videoclips(final_clips, method="compose")
        video = video.subclip(0, total_duration)
        video = video.set_audio(audio)

        title_text = script.get('thumbnail_text', '')
        if title_text:
            title_clip = (self._title_overlay(title_text, 4)
                          .set_position('center')
                          .fadein(0.5).fadeout(0.5))
            video = CompositeVideoClip([video, title_clip])

        logger.info(f"Exporting video to {output_path}...")
        video.write_videofile(
            output_path, fps=30, codec='libx264', audio_codec='aac',
            temp_audiofile='/tmp/temp_audio.m4a', remove_temp=True,
            verbose=False, logger=None
        )

        for path in downloaded:
            try:
                os.remove(path)
            except:
                pass

        logger.info(f"Video assembled: {output_path}")
        return output_path

    def _create_fallback_video(self, script: dict, audio_path: str, output_path: str) -> str:
        """Fallback: dark background with PIL-rendered text (no ImageMagick)."""
        audio = AudioFileClip(audio_path)
        duration = audio.duration

        bg = ColorClip(size=(1920, 1080), color=[10, 10, 20]).set_duration(duration)
        title_text = script.get('thumbnail_text', 'GridPhantom')
        title = self._title_overlay(title_text, duration).set_position('center')

        video = CompositeVideoClip([bg, title]).set_audio(audio)
        video.write_videofile(output_path, fps=30, codec='libx264',
                              audio_codec='aac', verbose=False, logger=None)
        logger.info(f"Fallback video assembled: {output_path}")
        return output_path

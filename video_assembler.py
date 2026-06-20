import requests
import os
import logging
import random
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeVideoClip,
    TextClip, concatenate_videoclips, ColorClip
)
from config import Config

logger = logging.getLogger(__name__)

class VideoAssembler:
    def __init__(self):
        self.pexels_key = Config.PEXELS_API_KEY
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def fetch_stock_videos(self, keyword: str, count: int = 10) -> list:
        """Fetch relevant stock videos from Pexels"""
        url = "https://api.pexels.com/videos/search"
        headers = {"Authorization": self.pexels_key}
        params = {
            "query": keyword,
            "per_page": count,
            "size": "medium",
            "orientation": "landscape"
        }

        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            videos = response.json().get('videos', [])

            video_urls = []
            for v in videos:
                files = v.get('video_files', [])
                # Prefer HD quality
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
        """Download a video file"""
        response = requests.get(url, stream=True)
        with open(path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return path

    def assemble(self, script: dict, audio_path: str, topic: dict) -> str:
        """Assemble final video from stock footage + audio"""

        keyword = script.get('thumbnail_keyword', 'artificial intelligence technology')
        language = script.get('language', 'en')
        output_path = f"{self.output_dir}/final_{language}_{random.randint(1000,9999)}.mp4"

        logger.info(f"Fetching stock videos for: {keyword}")
        video_urls = self.fetch_stock_videos(keyword, count=15)

        if not video_urls:
            # Fallback: create simple color background video
            logger.warning("No stock videos found, using fallback")
            return self._create_fallback_video(script, audio_path, output_path)

        # Load audio to get duration
        audio = AudioFileClip(audio_path)
        total_duration = audio.duration

        # Download and clip stock videos
        clips = []
        downloaded = []

        for i, url in enumerate(video_urls[:8]):
            try:
                dl_path = f"/tmp/stock_{i}.mp4"
                self.download_video(url, dl_path)
                downloaded.append(dl_path)

                clip = VideoFileClip(dl_path).resize((1920, 1080))
                # Use 10-15 second segments
                seg_duration = min(12, clip.duration)
                clip = clip.subclip(0, seg_duration)
                clips.append(clip)

            except Exception as e:
                logger.error(f"Error processing clip {i}: {e}")

        if not clips:
            return self._create_fallback_video(script, audio_path, output_path)

        # Loop clips to match audio duration
        final_clips = []
        current_duration = 0
        while current_duration < total_duration:
            for clip in clips:
                if current_duration >= total_duration:
                    break
                final_clips.append(clip)
                current_duration += clip.duration

        # Concatenate and add audio
        video = concatenate_videoclips(final_clips, method="compose")
        video = video.subclip(0, total_duration)
        video = video.set_audio(audio)

        # Add subtle title overlay at start
        title_text = script.get('thumbnail_text', '')
        if title_text:
            title_clip = (TextClip(title_text, fontsize=60, color='white',
                                   font='Arial-Bold', stroke_color='black', stroke_width=2)
                          .set_position('center')
                          .set_duration(4)
                          .fadein(0.5).fadeout(0.5))
            video = CompositeVideoClip([video, title_clip])

        # Export
        logger.info(f"Exporting video to {output_path}...")
        video.write_videofile(
            output_path,
            fps=30,
            codec='libx264',
            audio_codec='aac',
            temp_audiofile='/tmp/temp_audio.m4a',
            remove_temp=True,
            verbose=False,
            logger=None
        )

        # Cleanup
        for path in downloaded:
            try:
                os.remove(path)
            except:
                pass

        logger.info(f"Video assembled: {output_path}")
        return output_path

    def _create_fallback_video(self, script: dict, audio_path: str, output_path: str) -> str:
        """Fallback: dark background with text overlay"""
        audio = AudioFileClip(audio_path)
        duration = audio.duration

        bg = ColorClip(size=(1920, 1080), color=[10, 10, 20]).set_duration(duration)
        title = (TextClip(script.get('thumbnail_text', 'GridPhantom'),
                          fontsize=80, color='white', font='Arial-Bold')
                 .set_position('center')
                 .set_duration(duration))

        video = CompositeVideoClip([bg, title]).set_audio(audio)
        video.write_videofile(output_path, fps=30, codec='libx264',
                              audio_codec='aac', verbose=False, logger=None)
        return output_path

import json
import os
import logging
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from config import Config

logger = logging.getLogger(__name__)

class YouTubeUploader:
    def __init__(self):
        self.service = self._authenticate()

    def _authenticate(self):
        """Authenticate with YouTube API using stored credentials"""
        creds_json = Config.YOUTUBE_CLIENT_SECRETS
        if not creds_json:
            raise ValueError("YOUTUBE_CLIENT_SECRETS not set")

        creds_data = json.loads(creds_json)
        creds = Credentials(
            token=creds_data.get('token'),
            refresh_token=creds_data.get('refresh_token'),
            token_uri='https://oauth2.googleapis.com/token',
            client_id=creds_data.get('client_id'),
            client_secret=creds_data.get('client_secret'),
            scopes=['https://www.googleapis.com/auth/youtube.upload',
                    'https://www.googleapis.com/auth/youtube']
        )

        # Always refresh to ensure valid token
        if creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info('YouTube credentials refreshed successfully')
            except Exception as e:
                logger.error(f'Token refresh failed: {e}')
                raise

        return build('youtube', 'v3', credentials=creds)

    def upload(self, video_path: str, script: dict, language: str) -> str:
        """Upload video to YouTube with full metadata"""

        title = script['title']
        description = self._build_description(script, language)
        tags = script.get('tags', [])

        # Add GridPhantom branding tags
        tags.extend(['GridPhantom', 'AI', 'Technology', 'Tech News',
                     'Artificial Intelligence', 'Future Tech'])

        body = {
            'snippet': {
                'title': title[:100],
                'description': description,
                'tags': tags[:30],
                'categoryId': '28',  # Science & Technology
                'defaultLanguage': language,
                'defaultAudioLanguage': language,
            },
            'status': {
                'privacyStatus': 'public',
                'selfDeclaredMadeForKids': False,
            }
        }

        media = MediaFileUpload(
            video_path,
            mimetype='video/mp4',
            resumable=True,
            chunksize=1024*1024*10  # 10MB chunks
        )

        logger.info(f"Uploading: {title}")
        request = self.service.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                logger.info(f"Upload progress: {progress}%")

        video_id = response['id']
        video_url = f"https://youtube.com/watch?v={video_id}"
        logger.info(f"✅ Uploaded: {video_url}")

        # Add chapters to description
        self._update_chapters(video_id, script)

        return video_id

    def _build_description(self, script: dict, language: str) -> str:
        description = script.get('description', '')

        # Add chapters
        chapters = script.get('chapters', [])
        if chapters:
            description += "\n\n⏱️ Chapters:\n"
            for ch in chapters:
                description += f"{ch['time']} {ch['title']}\n"

        # Add footer
        if language == 'en':
            description += "\n\n🤖 GridPhantom — AI & Tech, decoded daily.\n"
            description += "🔔 Subscribe for daily AI news\n"
        else:
            description += "\n\n🤖 GridPhantom — KI & Tech, täglich erklärt.\n"
            description += "🔔 Abonniere für tägliche KI-News\n"

        return description[:5000]

    def _update_chapters(self, video_id: str, script: dict):
        """Add video chapters"""
        try:
            chapters = script.get('chapters', [])
            if not chapters:
                return
            # Chapters are embedded in description already
            pass
        except Exception as e:
            logger.error(f"Chapter update error: {e}")

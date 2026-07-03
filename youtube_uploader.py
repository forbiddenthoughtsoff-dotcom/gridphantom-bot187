import json
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
            # Must match exactly what the refresh token was granted,
            # otherwise Google rejects the refresh with invalid_scope
            scopes=['https://www.googleapis.com/auth/youtube.force-ssl',
                    'https://www.googleapis.com/auth/youtube.upload']
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

    def get_recent_titles(self, limit: int = 15) -> list:
        """Titles of the channel's latest uploads — used so new scripts
        take a fresh angle instead of repeating what was already posted."""
        try:
            ch = self.service.channels().list(
                part='contentDetails', mine=True).execute()
            uploads = ch['items'][0]['contentDetails']['relatedPlaylists']['uploads']
            items = self.service.playlistItems().list(
                part='snippet', playlistId=uploads, maxResults=limit).execute()
            titles = [i['snippet']['title'] for i in items.get('items', [])]
            logger.info(f"Recent uploads for angle-dedup: {len(titles)}")
            return titles
        except Exception as e:
            logger.warning(f"Could not fetch recent titles: {e}")
            return []

    def upload(self, video_path: str, script: dict, language: str) -> str:
        """Upload video to YouTube with full metadata"""

        # "#Shorts" in the title is YouTube's explicit signal to classify
        # the upload as a Short instead of a regular video
        title = script['title']
        if '#shorts' not in title.lower():
            title = f"{title[:91]} #Shorts"
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
        return video_id

    def _build_description(self, script: dict, language: str) -> str:
        # First line: #Shorts (YouTube reads the first hashtags for classification)
        description = "#Shorts\n\n" + script.get('description', '')

        # Footer with brand + CTA
        if language == 'en':
            description += "\n\n🤖 GridPhantom — AI & Tech, decoded daily."
            description += "\n🔔 Subscribe so you never miss what's next: @GridPhantom187"
            base_tags = ['shorts', 'ai', 'tech', 'technews', 'artificialintelligence']
        else:
            description += "\n\n🤖 GridPhantom — KI & Tech, täglich entschlüsselt."
            description += "\n🔔 Abonnieren und nichts mehr verpassen: @GridPhantom187"
            base_tags = ['shorts', 'ki', 'tech', 'technews', 'künstlicheintelligenz']

        # Hashtags: topic-specific first (from script tags), then base — deduped, max 12
        topic_tags = [t.strip().lower().replace(' ', '') for t in script.get('tags', [])
                      if t and t.strip().lower() not in ('shorts', 'viral', 'tech')]
        all_tags, seen = [], set()
        for t in topic_tags + base_tags + ['viral', 'trending', 'gridphantom']:
            if t and t not in seen:
                seen.add(t)
                all_tags.append(t)
        description += "\n\n" + " ".join(f"#{t}" for t in all_tags[:12])

        return description[:5000]

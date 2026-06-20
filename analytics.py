import json
import logging
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config import Config

logger = logging.getLogger(__name__)

class Analytics:
    def __init__(self):
        self.service = self._authenticate()

    def _authenticate(self):
        creds_json = Config.YOUTUBE_CLIENT_SECRETS
        creds_data = json.loads(creds_json)
        creds = Credentials(
            token=creds_data.get('token'),
            refresh_token=creds_data.get('refresh_token'),
            token_uri='https://oauth2.googleapis.com/token',
            client_id=creds_data.get('client_id'),
            client_secret=creds_data.get('client_secret'),
            scopes=['https://www.googleapis.com/auth/yt-analytics.readonly']
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('youtubeAnalytics', 'v2', credentials=creds)

    def get_top_performing_topics(self) -> list:
        """Get best performing video topics for optimization"""
        try:
            response = self.service.reports().query(
                ids=f'channel=={Config.YOUTUBE_CHANNEL_ID}',
                startDate='2024-01-01',
                endDate='today',
                metrics='views,estimatedMinutesWatched,averageViewDuration,likes',
                dimensions='video',
                sort='-views',
                maxResults=10
            ).execute()

            rows = response.get('rows', [])
            logger.info(f"Top {len(rows)} videos analyzed")
            return rows

        except Exception as e:
            logger.error(f"Analytics error: {e}")
            return []

    def get_best_upload_times(self) -> list:
        """Determine best times to upload based on viewer activity"""
        try:
            response = self.service.reports().query(
                ids=f'channel=={Config.YOUTUBE_CHANNEL_ID}',
                startDate='30daysAgo',
                endDate='today',
                metrics='views',
                dimensions='day,hour',
                sort='-views'
            ).execute()

            rows = response.get('rows', [])
            if rows:
                best_times = [(r[1], r[2]) for r in rows[:5]]  # (day, hour)
                logger.info(f"Best upload times: {best_times}")
                return best_times
            return [(1, 9), (4, 17)]  # Default: Mon 9am, Thu 5pm

        except Exception as e:
            logger.error(f"Upload time analysis error: {e}")
            return [(1, 9), (4, 17)]

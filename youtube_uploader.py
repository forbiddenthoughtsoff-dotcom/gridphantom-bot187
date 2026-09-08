# -*- coding: utf-8 -*-
import json
import logging
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from config import Config

logger = logging.getLogger(__name__)

def _clean_tags(tags) -> list:
    """YouTube's tag rules, enforced instead of hoped for: no '<' '>' '"',
    a single tag at most 30 characters, the whole list at most 500
    characters where a tag with spaces costs two extra (it is quoted).
    Episode 2 of the series was rejected twice with invalidTags because the
    German search phrases pushed the list past that budget."""
    import re
    out, seen, total = [], set(), 0
    for t in tags or []:
        t = re.sub(r'[<>"]', '', str(t)).strip()
        if not t or len(t) > 30:
            continue
        k = t.lower()
        if k in seen:
            continue
        cost = len(t) + (2 if ' ' in t else 0)
        if total + cost > 470:
            continue
        seen.add(k)
        out.append(t)
        total += cost
    return out


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
        return [p['title'] for p in self.get_recent_performance(limit)]

    def get_recent_performance(self, limit: int = 25) -> list:
        """Recent uploads with view/like stats and a fairness-normalized
        rate (views per hour since publish) — the channel's own feedback
        loop: the generator learns from what actually performs."""
        try:
            from datetime import datetime, timezone
            ch = self.service.channels().list(
                part='contentDetails', mine=True).execute()
            uploads = ch['items'][0]['contentDetails']['relatedPlaylists']['uploads']
            items = self.service.playlistItems().list(
                part='snippet,contentDetails', playlistId=uploads,
                maxResults=limit).execute().get('items', [])
            ids = [i['contentDetails']['videoId'] for i in items]
            if not ids:
                return []
            stats = self.service.videos().list(
                part='snippet,statistics', id=','.join(ids)).execute()
            now = datetime.now(timezone.utc)
            out = []
            for v in stats.get('items', []):
                pub = datetime.fromisoformat(
                    v['snippet']['publishedAt'].replace('Z', '+00:00'))
                age_h = max((now - pub).total_seconds() / 3600.0, 1.0)
                views = int(v['statistics'].get('viewCount', 0))
                likes = int(v['statistics'].get('likeCount', 0))
                out.append({
                    'title': v['snippet']['title'],
                    'description': v['snippet'].get('description', ''),
                    'video_id': v['id'],
                    'views': views, 'likes': likes,
                    'age_hours': round(age_h, 1),
                    # rate only meaningful once a video had time to spread
                    'rate': views / age_h if age_h >= 6 else 0.0,
                })
            logger.info(f"Recent uploads for angle-dedup + learning: {len(out)}")
            return out
        except Exception as e:
            logger.warning(f"Could not fetch recent performance: {e}")
            return []

    def find_related_video(self, query: str) -> str:
        """Direct link to a topical YouTube video for the description, so
        viewers don't have to search. Prefers the official Rockstar Games
        channel (trailers/announcements), else the top search result."""
        try:
            res = self.service.search().list(
                part='snippet', q=f"{query} GTA", type='video',
                maxResults=5, relevanceLanguage='de').execute()
            items = res.get('items', [])
            if not items:
                return ''
            for it in items:
                if it['snippet'].get('channelTitle', '').strip().lower() \
                        == 'rockstar games':
                    return f"https://youtu.be/{it['id']['videoId']}"
            return f"https://youtu.be/{items[0]['id']['videoId']}"
        except Exception as e:
            logger.warning(f"Related-video search failed (non-fatal): {e}")
            return ''

    def upload(self, video_path: str, script: dict, language: str) -> str:
        """Upload video to YouTube with full metadata"""

        # "#Shorts" in the title is YouTube's explicit signal to classify
        # the upload as a Short instead of a regular video
        title = script['title']
        if '#shorts' not in title.lower():
            title = f"{title[:91]} #Shorts"

        # No outbound "related video" link any more: it sent viewers to
        # other channels and cost 100 quota units per upload
        # YouTube rejects '<' and '>' in title/description (invalidDescription)
        # — an episode that wrote "Pause > Online > Karriere" hit exactly that
        title = title.replace('<', '‹').replace('>', '›')
        description = self._build_description(script, language)
        description = description.replace('<', '‹').replace('>', '›')
        tags = script.get('tags', [])

        # Branding + audience-targeting search tags
        tags.extend(['GridPhantom', 'GTA', 'GTA 5', 'GTA V', 'GTA Online',
                     'GTA 6', 'GTA VI', 'Grand Theft Auto', 'Rockstar Games',
                     'gta tricks', 'gta tipps deutsch', 'gta online deutsch',
                     'gta 5 deutsch', 'gaming shorts'])

        tags = _clean_tags(tags)

        body = {
            'snippet': {
                'title': title[:100],
                'description': description,
                'tags': tags,
                'categoryId': '20',  # Gaming
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

    SERIES_PLAYLIST = "GTA Online Karriere – alle Folgen (Tutorial-Serie)"

    def add_to_series_playlist(self, video_id: str, title: str) -> bool:
        """Every 'GTA Online Karriere #N' episode goes into the series
        playlist (created on first use) — binge path for the tutorial series,
        more watch time per viewer. Costs ~51 quota units per episode."""
        try:
            import re
            if not re.search(r'karriere\s*#\s*\d+', title or '', re.I):
                return False
            pl_id = None
            res = self.service.playlists().list(
                part='snippet', mine=True, maxResults=50).execute()
            for p in res.get('items', []):
                if p['snippet']['title'].strip().lower() == self.SERIES_PLAYLIST.lower():
                    pl_id = p['id']
                    break
            if not pl_id:
                pl_id = self.service.playlists().insert(
                    part='snippet,status',
                    body={'snippet': {
                        'title': self.SERIES_PLAYLIST,
                        'description': ("Jede Aufgabe des Karriere-Fortschritts in GTA Online, "
                                        "Stufe 1 bis 4, Folge fuer Folge erklaert. "
                                        "Taeglich eine neue Folge um 12 Uhr. Sharing is caring."),
                        'defaultLanguage': 'de'},
                        'status': {'privacyStatus': 'public'}}).execute()['id']
                logger.info(f"📚 Series playlist created: {pl_id}")
            self.service.playlistItems().insert(
                part='snippet',
                body={'snippet': {'playlistId': pl_id,
                                  'resourceId': {'kind': 'youtube#video',
                                                 'videoId': video_id}}}).execute()
            logger.info(f"📚 Added to series playlist: {video_id}")
            return True
        except Exception as e:
            logger.warning(f"Series playlist skipped (non-fatal): {e}")
            return False

    def _build_description(self, script: dict, language: str) -> str:
        # First line: #Shorts (YouTube reads the first hashtags for classification)
        description = "#Shorts\n\n" + script.get('description', '')

        # Direct link to a topical video — saves viewers the search
        if script.get('related_video_url'):
            label = ("▶️ Watch the full video here: " if language == 'en'
                     else "▶️ Passendes Video direkt hier: ")
            description += f"\n\n{label}{script['related_video_url']}"

        # Music attribution (CC BY requires credit)
        if script.get('music_credit'):
            label = "🎵 Music: " if language == 'en' else "🎵 Musik: "
            description += f"\n{label}{script['music_credit']}"
        # Voice attribution (required on ElevenLabs' free tier)
        if script.get('voice_credit'):
            label = "🎙️ Voice: " if language == 'en' else "🎙️ Stimme: "
            description += f"\n{label}{script['voice_credit']}"

        # Footer with brand + CTA
        if language == 'en':
            description += ("\n\n🎮 GridPhantom — daily GTA Shorts: tricks, facts, "
                            "help & myths for GTA 5, GTA Online & GTA 6. "
                            "New Shorts every day at 7am, 12pm, 5pm & 10pm (CET).")
            description += "\n🔔 Subscribe for your daily GTA fix: @GridPhantom187"
            description += ("\n💬 Tell us in the comments which GTA topic "
                            "we should cover next!")
            base_tags = ['shorts', 'gta', 'gta5', 'gtav', 'gtaonline',
                         'gta6', 'gtavi', 'grandtheftauto', 'rockstar',
                         'gtatricks', 'gaming', 'gtaclips']
        else:
            description += ("\n\n🎮 GridPhantom — täglich GTA Shorts: Tricks, Fakten, "
                            "Hilfe & Mythen zu GTA 5, GTA Online & GTA 6. "
                            "Jeden Tag um 07, 12, 17 & 22 Uhr.")
            description += "\n🔔 Abonnieren für deine tägliche GTA-Dosis: @GridPhantom187"
            description += ("\n💬 Schreib in die Kommentare, welches GTA-Thema "
                            "wir als Nächstes zeigen sollen!")
            base_tags = ['shorts', 'gta', 'gta5', 'gta5deutsch', 'gtaonline',
                         'gta6', 'gtavi', 'gtatricksdeutsch', 'gtatippsdeutsch',
                         'grandtheftauto', 'rockstargames', 'gamingdeutsch']

        # Hashtags: topic-specific first (from script tags), then base — deduped.
        # YouTube reads the first 3 for display, uses all for search; hard
        # platform limit is 60, we stay well under it
        topic_tags = [t.strip().lower().replace(' ', '') for t in script.get('tags', [])
                      if t and t.strip().lower() not in ('shorts', 'viral')]
        all_tags, seen = [], set()
        for t in topic_tags + base_tags + ['viral', 'trending', 'fyp',
                                           'gridphantom']:
            if t and t not in seen:
                seen.add(t)
                all_tags.append(t)
        description += "\n\n" + " ".join(f"#{t}" for t in all_tags[:25])

        return description[:5000]

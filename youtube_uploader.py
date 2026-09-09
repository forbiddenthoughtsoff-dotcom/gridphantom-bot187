# -*- coding: utf-8 -*-
import os
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


# Must match what the refresh token was granted (a subset is fine, a
# superset is refused with invalid_scope). YOUTUBE_SCOPES overrides for
# tokens without the analytics grants.
SCOPES = [x for x in os.environ.get(
    'YOUTUBE_SCOPES',
    'https://www.googleapis.com/auth/youtube.force-ssl '
    'https://www.googleapis.com/auth/youtube.upload '
    'https://www.googleapis.com/auth/yt-analytics.readonly '
    'https://www.googleapis.com/auth/yt-analytics-monetary.readonly').split() if x]


FOOTER_DE = (
    "\n\n🎮 GridPhantom – täglich GTA auf Hochdeutsch, ohne Clickbait."
    "\n⏰ 07:30 eigener Clip · 12:00 GTA Online Karriere (Serie) · 17:30 Guide in voller Länge"
    " · 19:00 & 21:15 GTA 6 News und Tricks · Di/Fr 21:15 Mythos oder Fakt"
    "\n📚 Karriere-Serie komplett: https://www.youtube.com/playlist?list=PLBEY4q4jZJiQ"
    "\n🔔 Abonnieren, damit du die nächste Folge nicht verpasst: @GridPhantom187"
    "\n💬 Welche Frage sollen wir als Nächstes klären? Schreib es in die Kommentare.")


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
            scopes=SCOPES
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

    def upload(self, video_path: str, script: dict, language: str,
               kind: str = 'short', publish_at=None) -> str:
        """Upload video to YouTube with full metadata. kind='long' uploads a
        regular 16:9 video (no #Shorts marker, chapters in the description)."""

        # "#Shorts" in the title is YouTube's explicit signal to classify
        # the upload as a Short instead of a regular video
        title = script['title']
        if kind == 'short' and '#shorts' not in title.lower():
            title = f"{title[:91]} #Shorts"

        # No outbound "related video" link any more: it sent viewers to
        # other channels and cost 100 quota units per upload
        # YouTube rejects '<' and '>' in title/description (invalidDescription)
        # — an episode that wrote "Pause > Online > Karriere" hit exactly that
        title = title.replace('<', '‹').replace('>', '›')
        description = self._build_description(script, language, shorts=(kind == 'short'))
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
                'selfDeclaredMadeForKids': False,   # adult gaming audience
                'embeddable': True,                 # reach outside YouTube
                'publicStatsViewable': True,
                'license': 'youtube',
            }
        }
        # Scheduled premiere: rendered at night, released at prime time.
        # YouTube requires private + publishAt (RFC 3339, UTC)
        if publish_at is not None:
            from datetime import timezone
            body['status']['privacyStatus'] = 'private'
            body['status']['publishAt'] = publish_at.astimezone(
                timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            logger.info(f"⏰ Scheduled release: {publish_at:%Y-%m-%d %H:%M} local")

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
    # Topic playlists: every upload lands in exactly one — binge paths for
    # browse/suggested, session time for the channel
    TOPIC_PLAYLISTS = [
        ('mythos', "Mythos oder Fakt – GTA Behauptungen im Check"),
        ('clip', "GridPhantom Moments – eigene GTA Online Clips"),
        ('long', "GTA Guides in voller Laenge (10+ Minuten)"),
        ('gta6', "GTA 6 News & Fakten – alles Bestaetigte"),
        ('online', "GTA Online Tricks, Geld & Geheimnisse"),
    ]

    def topic_key(self, script: dict, kind: str = 'short') -> str:
        t = (script.get('title', '') or '').lower()
        if script.get('format') == 'dialogue' or 'mythos oder fakt' in t:
            return 'mythos'
        if script.get('clip_marker'):
            return 'clip'
        if kind == 'long':
            return 'long'
        blob = (t + ' ' + ' '.join(script.get('tags', []))).lower()
        if any(k in blob for k in ('gta 6', 'gta6', 'gta vi', 'vice city', 'leonida', 'lucia', 'jason')):
            return 'gta6'
        return 'online'

    def _playlist_id(self, title: str, description: str) -> str:
        if not hasattr(self, '_pl_cache'):
            self._pl_cache = {}
            try:
                res = self.service.playlists().list(part='snippet', mine=True, maxResults=50).execute()
                for p in res.get('items', []):
                    self._pl_cache[p['snippet']['title'].strip().lower()] = p['id']
            except Exception as e:
                logger.warning(f"Playlist listing failed: {e}")
        key = title.strip().lower()
        if key not in self._pl_cache:
            pl = self.service.playlists().insert(
                part='snippet,status',
                body={'snippet': {'title': title, 'description': description, 'defaultLanguage': 'de'},
                      'status': {'privacyStatus': 'public'}}).execute()
            self._pl_cache[key] = pl['id']
            logger.info(f"📚 Playlist created: {title}")
        return self._pl_cache[key]

    def add_to_topic_playlist(self, video_id: str, script: dict, kind: str = 'short') -> bool:
        """~51 quota units per upload."""
        try:
            key = self.topic_key(script, kind)
            title = dict(self.TOPIC_PLAYLISTS)[key]
            pl_id = self._playlist_id(title, "GridPhantom – taeglich GTA Shorts, Guides und eigene Clips. "
                                             "Abonnieren fuer die naechste Folge.")
            # a freshly created playlist answers 409 SERVICE_UNAVAILABLE for a
            # few seconds — retry briefly instead of losing the item
            import time as _t
            for attempt in range(4):
                try:
                    self.service.playlistItems().insert(
                        part='snippet',
                        body={'snippet': {'playlistId': pl_id,
                                          'resourceId': {'kind': 'youtube#video',
                                                         'videoId': video_id}}}).execute()
                    break
                except Exception as e:
                    if attempt == 3 or 'SERVICE_UNAVAILABLE' not in str(e):
                        raise
                    _t.sleep(3 * (attempt + 1))
            logger.info(f"📚 Added to playlist '{title}': {video_id}")
            return True
        except Exception as e:
            logger.warning(f"Topic playlist skipped (non-fatal): {e}")
            return False

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

    def set_thumbnail(self, video_id: str, path: str) -> bool:
        """Custom thumbnail (long-form only; ~50 quota units). Fails soft —
        channels without phone verification cannot set thumbnails."""
        try:
            self.service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(path, mimetype='image/jpeg')).execute()
            logger.info(f"🖼️ Thumbnail set on {video_id}")
            return True
        except Exception as e:
            logger.warning(f"Thumbnail skipped (non-fatal): {e}")
            return False

    def _build_description(self, script: dict, language: str, shorts: bool = True) -> str:
        # First line: #Shorts (YouTube reads the first hashtags for classification)
        description = ("#Shorts\n\n" if shorts else "") + script.get('description', '')
        # Long-form: chapters (first one must be 0:00) — navigation + retention
        if script.get('chapters'):
            lines = []
            for i, (sec, name) in enumerate(script['chapters']):
                sec = 0 if i == 0 else int(sec)
                lines.append(f"{sec // 60}:{sec % 60:02d} {name}")
            description += "\n\n📑 Kapitel:\n" + "\n".join(lines)

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
            description += FOOTER_DE
            base_tags = ['shorts', 'gta', 'gta5', 'gta5deutsch', 'gtaonline',
                         'gta6', 'gtavi', 'gtatricksdeutsch', 'gtatippsdeutsch',
                         'grandtheftauto', 'rockstargames', 'gamingdeutsch']
        if not shorts:
            base_tags = [t for t in base_tags if t != 'shorts']

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

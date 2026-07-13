import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

REPLY_SYSTEM = """You are the channel voice of GridPhantom (@GridPhantom187), a German YouTube Shorts channel about hidden AI superpowers and prompt tricks (Claude, ChatGPT & Co.).
You reply to viewer comments. Rules:
- ALWAYS answer in the same language as the comment
- Max 25 words, warm, witty, confident insider tone
- No links, no hashtags, max 1 emoji
- If the comment asks something, answer briefly; otherwise react and end with a short follow-up question that keeps the thread alive
- Never be defensive about criticism - stay charming
Output ONLY the reply text, nothing else."""

SEED_SYSTEM = """You write the channel's own first comment under a freshly uploaded YouTube Short to spark discussion.
Rules: same language as the video title, max 20 words, one provocative but friendly question about the topic, max 1 emoji.
Output ONLY the comment text."""


class CommunityManager:
    """Automated engagement: reply to viewer comments, seed discussion."""

    def __init__(self, service):
        self.service = service
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self.channel_id = self._my_channel_id()

    def _my_channel_id(self):
        ch = self.service.channels().list(part='id', mine=True).execute()
        return ch['items'][0]['id']

    def _recent_video_ids(self, limit=10):
        ch = self.service.channels().list(
            part='contentDetails', mine=True).execute()
        uploads = ch['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        items = self.service.playlistItems().list(
            part='contentDetails', playlistId=uploads,
            maxResults=limit).execute()
        return [i['contentDetails']['videoId'] for i in items.get('items', [])]

    def _generate(self, system, prompt):
        msg = self.client.messages.create(
            model="claude-haiku-4-5", max_tokens=120,
            system=system,
            messages=[{"role": "user", "content": prompt}])
        return msg.content[0].text.strip().strip('"')

    def respond_to_comments(self) -> int:
        """Reply to every viewer comment that has no channel reply yet."""
        replied = 0
        try:
            for vid in self._recent_video_ids():
                try:
                    threads = self.service.commentThreads().list(
                        part='snippet,replies', videoId=vid, maxResults=20,
                        order='time', textFormat='plainText').execute()
                except Exception:
                    continue  # comments disabled or video processing

                for th in threads.get('items', []):
                    top = th['snippet']['topLevelComment']['snippet']
                    author_ch = top.get('authorChannelId', {}).get('value')
                    if author_ch == self.channel_id:
                        continue
                    existing = th.get('replies', {}).get('comments', [])
                    if any(r['snippet'].get('authorChannelId', {}).get('value')
                           == self.channel_id for r in existing):
                        continue

                    text = self._generate(
                        REPLY_SYSTEM,
                        f'Comment by {top.get("authorDisplayName", "a viewer")}: '
                        f'"{top.get("textDisplay", "")}"\nWrite the reply.')
                    self.service.comments().insert(
                        part='snippet',
                        body={'snippet': {
                            'parentId': th['id'],
                            'textOriginal': text}}).execute()
                    replied += 1
                    logger.info(f"💬 Replied on {vid}: {text[:70]}")

            logger.info(f"💬 Engagement cycle done: {replied} replies")
        except Exception as e:
            if 'insufficient' in str(e).lower() or 'forbidden' in str(e).lower():
                logger.warning(
                    "Comment write needs the youtube.force-ssl scope - "
                    "re-authorize the YouTube credentials to enable replies")
            else:
                logger.error(f"Engagement cycle error: {e}", exc_info=True)
        return replied

    def seed_comment(self, video_id: str, script: dict):
        """Post the channel's own first comment under a fresh upload."""
        try:
            question = self._generate(
                SEED_SYSTEM,
                f'Video title: "{script.get("title", "")}"\n'
                f'Narration: "{script.get("narration", "")}"\n'
                f'Write the seed comment.')
            self.service.commentThreads().insert(
                part='snippet',
                body={'snippet': {
                    'videoId': video_id,
                    'topLevelComment': {
                        'snippet': {'textOriginal': question}}}}).execute()
            logger.info(f"💬 Seed comment posted on {video_id}: {question}")
        except Exception as e:
            logger.warning(f"Seed comment failed (non-fatal): {e}")

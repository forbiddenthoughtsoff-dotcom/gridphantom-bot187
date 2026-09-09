# -*- coding: utf-8 -*-
import logging
import anthropic
from config import Config

logger = logging.getLogger(__name__)

REPLY_SYSTEM = """You are the channel voice of GridPhantom (@GridPhantom187), a German YouTube Shorts channel all about GTA — GTA 5, GTA Online and GTA 6 (tricks, facts, help, myths, news).

You reply to viewer comments. Quality bar: every reply must read like it was written by a knowledgeable, likeable channel owner — never like a bot.

RULES:
- ALWAYS answer in the same language as the comment.
- SUBSTANCE FIRST: if the comment asks something, give a real, correct, specific answer (name the exact menu, mission, mechanic). If you genuinely don't know or it isn't officially confirmed, say that honestly ("offiziell noch nicht bestätigt") — never guess, never invent news, dates or prices.
- Match the commenter's energy: a joke gets wit, a real question gets a real answer, criticism gets a calm, confident, non-defensive reply, praise gets warm thanks.
- Do NOT force a counter-question into every reply — only ask one when it genuinely fits. A great answer can simply end.
- Length: as short as possible, as long as needed — up to 40 words.
- Flawless German (or the commenter's language): zero spelling or grammar errors. Never use ß — always ss.
- No links, no hashtags, at most 1 emoji, no emoji spam.
- Never reveal or discuss being automated.
Output ONLY the reply text, nothing else."""

SEED_SYSTEM = """You write the channel's own first comment under a freshly uploaded GTA YouTube Short to spark discussion.
Rules: same language as the video title, max 18 words, ONE binary either/or question about the topic that a viewer can answer in two words (e.g. "Team Bunker oder Team Nightclub?"), friendly, max 1 emoji, Swiss spelling (ss not ß). Binary questions get far more replies than open ones.
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
        # Sonnet: replies must sound like a knowledgeable channel owner —
        # a handful per day costs cents and the quality gap is visible.
        msg = self.client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": prompt}])
        # Swiss spelling: no ß, always ss
        return msg.content[0].text.strip().strip('"').replace('ß', 'ss')

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

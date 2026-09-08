# -*- coding: utf-8 -*-
"""Channel hygiene: 313 off-topic six-second clips from June/July 2026 (AI
news, "she said" bait, duplicates) still sit public on the channel. They
blur the channel's topic for the algorithm and are a "repetitive content"
risk in the monetisation review. This job sets them to PRIVATE (reversible),
a few per day, inside the leftover quota of each day (50 units per video)."""
import os
import re
import logging
import datetime

logger = logging.getLogger(__name__)

GTA_RE = re.compile(r'gta|grand theft|rockstar|los santos|vice city|leonida|karriere|lucia|jason|'
                    r'gridphantom moments|mythos oder fakt', re.I)
CUTOFF = '2026-07-26'          # first GTA upload; everything older and non-GTA goes private
PER_RUN = int(os.environ.get('CLEANUP_PER_RUN', '18'))


def run(service) -> int:
    """Privatise up to PER_RUN old off-topic public videos. Returns count."""
    try:
        ch = service.channels().list(part='contentDetails', mine=True).execute()
        uploads = ch['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        ids, token = [], None
        while True:
            r = service.playlistItems().list(part='snippet,contentDetails', playlistId=uploads,
                                             maxResults=50, pageToken=token).execute()
            for it in r.get('items', []):
                sn = it['snippet']
                if sn.get('publishedAt', '') < CUTOFF and not GTA_RE.search(sn.get('title', '')):
                    ids.append(it['contentDetails']['videoId'])
            token = r.get('nextPageToken')
            if not token:
                break
        if not ids:
            logger.info("🧹 Cleanup: nothing left to hide")
            return 0
        # only those still public (videos.list is 1 unit per 50)
        todo = []
        for i in range(0, len(ids), 50):
            r = service.videos().list(part='status,snippet', id=','.join(ids[i:i + 50])).execute()
            todo += [v for v in r.get('items', []) if v['status'].get('privacyStatus') == 'public']
        done = 0
        for v in todo[:PER_RUN]:
            try:
                service.videos().update(part='status', body={
                    'id': v['id'],
                    'status': {'privacyStatus': 'private',
                               'selfDeclaredMadeForKids': False}}).execute()
                done += 1
            except Exception as e:
                logger.warning(f"Cleanup stopped ({e})")
                break
        logger.info(f"🧹 Cleanup: {done} off-topic videos set to private, "
                    f"{max(0, len(todo) - done)} remaining")
        return done
    except Exception as e:
        logger.warning(f"Cleanup skipped: {e}")
        return 0

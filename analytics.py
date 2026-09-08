# -*- coding: utf-8 -*-
"""YouTube Analytics: the numbers Studio shows — watch time, retention,
subscribers per video, traffic sources. Used by the reports and by the
generator's feedback loop. Needs the yt-analytics scopes on the token and
the YouTube Analytics API enabled in the Google Cloud project."""
import logging
import datetime
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


def _svc(credentials):
    return build('youtubeAnalytics', 'v2', credentials=credentials)


def channel_summary(credentials, days: int = 28) -> dict:
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    try:
        r = _svc(credentials).reports().query(
            ids='channel==MINE', startDate=start.isoformat(), endDate=end.isoformat(),
            metrics='views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,'
                    'subscribersGained,subscribersLost,likes,comments,shares').execute()
        cols = [c['name'] for c in r.get('columnHeaders', [])]
        row = (r.get('rows') or [[0] * len(cols)])[0]
        out = dict(zip(cols, row))
        out['watchHours'] = round(out.get('estimatedMinutesWatched', 0) / 60.0, 1)
        return out
    except Exception as e:
        logger.warning(f"Analytics summary unavailable: {e}")
        return {}


def video_metrics(credentials, video_ids: list, days: int = 28) -> dict:
    """Per video: views, minutes watched, avg view %, subs gained."""
    if not video_ids:
        return {}
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    out = {}
    try:
        svc = _svc(credentials)
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i + 50]
            r = svc.reports().query(
                ids='channel==MINE', startDate=start.isoformat(), endDate=end.isoformat(),
                metrics='views,estimatedMinutesWatched,averageViewPercentage,subscribersGained',
                dimensions='video', filters='video==' + ','.join(chunk),
                maxResults=50, sort='-views').execute()
            cols = [c['name'] for c in r.get('columnHeaders', [])]
            for row in r.get('rows', []):
                d = dict(zip(cols, row))
                out[d.pop('video')] = d
    except Exception as e:
        logger.warning(f"Analytics per video unavailable: {e}")
    return out


def traffic_sources(credentials, days: int = 28) -> list:
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    try:
        r = _svc(credentials).reports().query(
            ids='channel==MINE', startDate=start.isoformat(), endDate=end.isoformat(),
            metrics='views,estimatedMinutesWatched', dimensions='insightTrafficSourceType',
            sort='-views').execute()
        return r.get('rows', [])
    except Exception as e:
        logger.warning(f"Traffic sources unavailable: {e}")
        return []

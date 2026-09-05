# -*- coding: utf-8 -*-
"""Owner's PS5 captures straight from the PlayStation cloud media gallery.

This is the private API the PlayStation App itself uses (documented by the
community — Sony offers no official one). The owner logs in once on
playstation.com and hands over the NPSSO session token (PSN_NPSSO). The bot
exchanges it for OAuth tokens exactly like the app does, lists the cloud
gallery (captures live there for 14 days, videos up to 3 min / 1080p),
and gameplay_sync downloads every new GTA video once into /tmp and turns it
into a vertical proxy. Screenshots and non-GTA titles are skipped.

Access tokens last an hour, refresh tokens and the NPSSO about two months —
when both are dead the bot logs one clear error and the owner pastes a fresh
NPSSO (https://ca.account.sony.com/api/v1/ssocookie while logged in).
Everything fails soft; no password is ever stored or used here."""
import os
import re
import time
import logging
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

OAUTH = 'https://ca.account.sony.com/api/authz/v3/oauth'
GALLERY = ('https://m.np.playstation.com/api/gameMediaService/v2/c2s/'
           'category/cloudMediaGallery/ugcType/all')
# Public OAuth client of the PlayStation App (not a user secret)
CLIENT_ID = '09515159-7237-4370-9b40-3806e67c0891'
CLIENT_SECRET = 'ucPjka5tntB2KqsP'
REDIRECT = 'com.scee.psxandroid.scecompcall://redirect'
SCOPES = 'psn:mobile.v2.core psn:clientapp'
UGC_SCREENSHOT, UGC_VIDEO = 1, 2
GTA_TITLE = re.compile(r'grand theft auto|\bgta\b', re.I)
NPSSO_HINT = ('paste a fresh NPSSO from '
              'https://ca.account.sony.com/api/v1/ssocookie into PSN_NPSSO')

_tokens = {'access': None, 'refresh': None, 'exp': 0.0}


def npsso() -> str:
    return os.environ.get('PSN_NPSSO', '').strip()


def enabled() -> bool:
    return bool(npsso() or os.environ.get('PSN_REFRESH_TOKEN', '').strip())


def _token_request(data: dict) -> str:
    r = requests.post(f'{OAUTH}/token', data=data,
                      auth=(CLIENT_ID, CLIENT_SECRET),
                      headers={'Content-Type': 'application/x-www-form-urlencoded'},
                      timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f'PSN token endpoint HTTP {r.status_code}: {r.text[:120]}')
    j = r.json()
    _tokens.update(access=j['access_token'],
                   refresh=j.get('refresh_token') or _tokens['refresh'],
                   exp=time.time() + int(j.get('expires_in', 3600)))
    return _tokens['access']


def _auth_from_npsso() -> str:
    r = requests.get(f'{OAUTH}/authorize',
                     params={'access_type': 'offline', 'client_id': CLIENT_ID,
                             'redirect_uri': REDIRECT, 'response_type': 'code',
                             'scope': SCOPES},
                     headers={'Cookie': f'npsso={npsso()}'},
                     allow_redirects=False, timeout=30)
    loc = r.headers.get('Location', '') or ''
    m = re.search(r'[?&]code=([^&]+)', loc)
    if r.status_code != 302 or not m:
        raise RuntimeError(f'PSN NPSSO rejected (HTTP {r.status_code}) — {NPSSO_HINT}')
    return _token_request({'code': m.group(1), 'grant_type': 'authorization_code',
                           'redirect_uri': REDIRECT})


def access_token() -> str:
    """Valid bearer token: cached → refresh token → fresh login from NPSSO."""
    if _tokens['access'] and time.time() < _tokens['exp'] - 120:
        return _tokens['access']
    refresh = _tokens['refresh'] or os.environ.get('PSN_REFRESH_TOKEN', '').strip()
    if refresh:
        try:
            return _token_request({'token_format': 'jwt', 'refresh_token': refresh,
                                   'grant_type': 'refresh_token', 'scope': SCOPES})
        except Exception as e:
            logger.warning(f'PSN token refresh failed ({e}); re-authenticating from NPSSO')
            _tokens['refresh'] = None
    if not npsso():
        raise RuntimeError(f'PSN: no usable refresh token — {NPSSO_HINT}')
    return _auth_from_npsso()


def _set_cookies(r) -> dict:
    """CloudFront signing values from the raw Set-Cookie headers (they may
    carry a domain the cookie jar rejects, so read the headers directly)."""
    out = {}
    try:
        raw = r.raw.headers.getlist('Set-Cookie')
    except Exception:
        raw = [r.headers.get('Set-Cookie', '')]
    for c in raw:
        m = re.match(r'\s*(CloudFront-(?:Key-Pair-Id|Signature|Policy))=([^;]+)', c or '')
        if m:
            out[m.group(1)] = m.group(2)
    return out


def list_captures(limit: int = 60) -> tuple:
    """(items newest first, cloudfront signing params) from the cloud gallery."""
    items, sign, cursor = [], {}, None
    for _ in range(8):
        params = {'limit': min(limit, 50)}
        if cursor:
            params['cursorMark'] = cursor
        r = requests.get(GALLERY, params=params,
                         headers={'Authorization': f'Bearer {access_token()}'},
                         timeout=30)
        if r.status_code == 401:
            _tokens['access'] = None  # force refresh once
            r = requests.get(GALLERY, params=params,
                             headers={'Authorization': f'Bearer {access_token()}'},
                             timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f'PSN gallery HTTP {r.status_code}: {r.text[:120]}')
        sign.update(_set_cookies(r))
        j = r.json()
        items.extend(j.get('ugcDocument') or [])
        cursor = j.get('nextCursorMark')
        if not cursor or len(items) >= limit:
            break
    return items, sign


def is_gta_video(item: dict, min_seconds: float = 4.0) -> bool:
    if item.get('ugcType') != UGC_VIDEO:
        return False
    name = f"{item.get('sceTitleName', '')} {item.get('title', '')}"
    if not GTA_TITLE.search(name):
        return False
    # A capture that is still being transcoded answers 403 on its media URL
    # (seen live right after recording) — it is simply picked up next sync
    if str(item.get('transcodeStatus') or 'complete').lower() != 'complete':
        return False
    if str(item.get('cloudStatus') or 'active').lower() != 'active':
        return False
    dur = item.get('videoDuration')
    return dur is None or float(dur) >= min_seconds


def media_url(item: dict, sign: dict) -> str:
    url = item.get('downloadUrl') or (
        item.get('videoUrl') if item.get('ugcType') == UGC_VIDEO
        else item.get('screenshotUrl')) or item.get('largePreviewImage') or ''
    if url and sign:
        url += ('&' if '?' in url else '?') + urlencode({
            'Key-Pair-Id': sign.get('CloudFront-Key-Pair-Id', ''),
            'Signature': sign.get('CloudFront-Signature', ''),
            'Policy': sign.get('CloudFront-Policy', '')})
    return url


def download(item: dict, sign: dict, dst: str, timeout=(30, 600)) -> bool:
    url = media_url(item, sign)
    if not url:
        return False
    cookies = {k: v for k, v in sign.items()}
    tmp = dst + '.part'
    try:
        with requests.get(url, stream=True, timeout=timeout, cookies=cookies) as r:
            if r.status_code != 200:
                logger.warning(f'PSN media download HTTP {r.status_code}')
                return False
            with open(tmp, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)
        os.replace(tmp, dst)
        return True
    except Exception as e:
        logger.warning(f'PSN media download failed: {e}')
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def display_name(item: dict) -> str:
    date = str(item.get('uploadDate', ''))[:10]
    game = re.sub(r'[^\w\s-]', '', str(item.get('sceTitleName', 'PS5'))).strip()
    return f"{game} {date}.mp4"

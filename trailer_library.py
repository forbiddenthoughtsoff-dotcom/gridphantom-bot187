# -*- coding: utf-8 -*-
"""Official GTA VI trailer footage as background for GTA 6 topics.

The channel owner explicitly approved using excerpts of Rockstar's official
trailers. Files are fetched at runtime from stable archive.org mirrors into
/tmp (never committed), cut into short vertical segments with ffmpeg and
stitched into a montage. Everything fails soft: if a trailer isn't available
yet, the assembler falls back to topic-matched stock footage."""
import os
import time
import json
import random
import logging
import threading
import subprocess
import requests
from motion import motion_vf, W, H

logger = logging.getLogger(__name__)

TRAILER_DIR = os.environ.get('TRAILER_DIR', '/tmp/trailers')

TRAILERS = [
    {
        'name': 'gta6_trailer2_1080p',
        'url': ('https://archive.org/download/youtube-VQRLujxTm3c/'
                '20250506%20-%20Grand%20Theft%20Auto%20VI%20Trailer%202%20'
                '%5BVQRLujxTm3c%5D.mp4'),
        # the "Rockstar Games presents" card sits in the first ~10 s
        'skip_head': 12.0, 'skip_tail': 14.0,
    },
    {
        'name': 'gta6_trailer1_4k',
        'url': ('https://archive.org/download/'
                'grand-theft-auto-vi-trailer-1-4k-60fps_202405/'
                'Grand%20Theft%20Auto%20VI%20Trailer%201%20%284k%29.mp4'),
        'skip_head': 12.0, 'skip_tail': 14.0,
    },
    {
        # Rockstar's official 26-minute "Extended Look" (08-27-2026): the
        # bulk of the shot library for scene-matched cuts (shots.py). 720p:
        # the box decodes it fast, and the framed 16:9 picture stays sharp.
        'name': 'gta6_extended_look_720p',
        'url': ('https://archive.org/download/'
                'grand-theft-auto-vi-gta-6-an-extended-look-26-minute-gameplay-reveal/'
                'Grand%20Theft%20Auto%20VI%20%28GTA%206%29_%20An%20Extended%20Look%20_'
                '%2026%20Minute%20Gameplay%20Reveal.mp4'),
        'skip_head': 20.0, 'skip_tail': 40.0,
    },
]

# "rockstar" is deliberately NOT a key: it appears in nearly every GTA script
GTA6_KEYS = ('gta 6', 'gta6', 'gta vi', 'vice city', 'leonida', 'lucia',
             'jason', 'trailer 3', 'trailer 2')

_lock = threading.Lock()
_started = False


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _path(t):
    return os.path.join(TRAILER_DIR, t['name'] + '.mp4')


def _download(t):
    dst = _path(t)
    if os.path.exists(dst) and os.path.getsize(dst) > 1_000_000:
        return dst
    os.makedirs(TRAILER_DIR, exist_ok=True)
    tmp = dst + '.part'
    try:
        with requests.get(t['url'], stream=True, timeout=(30, 300),
                          headers={'User-Agent': 'GridPhantomBot/1.0'}) as r:
            r.raise_for_status()
            with open(tmp, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)
        os.replace(tmp, dst)
        logger.info(f"🎞️ Trailer ready: {t['name']} "
                    f"({os.path.getsize(dst) // (1 << 20)} MB)")
        return dst
    except Exception as e:
        logger.warning(f"Trailer download failed ({t['name']}): {e}")
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass
        return None


def ensure_trailers_async():
    """Kick off background downloads once per process (idempotent)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def worker():
        # archive.org answers with read timeouts now and then (09-26: trailer 2
        # failed once at start and stayed missing all day); retry the missing
        # files a few times with a pause instead of giving up after one pass
        for attempt in range(6):
            missing = [t for t in TRAILERS if not os.path.exists(_path(t))
                       or os.path.getsize(_path(t)) <= 1_000_000]
            if not missing:
                return
            if attempt:
                time.sleep(120 * attempt)
            for t in missing:
                _download(t)
    threading.Thread(target=worker, daemon=True, name='trailer-prefetch').start()


def available_trailers():
    return [t for t in TRAILERS if os.path.exists(_path(t))
            and os.path.getsize(_path(t)) > 1_000_000]


def is_gta6_topic(script: dict) -> bool:
    """GTA 6 is the video's subject when the title says so, or when the
    body keeps coming back to it. A GTA Online script that mentions GTA 6
    once in passing keeps its own footage."""
    title = script.get('title', '').lower()
    if any(k in title for k in GTA6_KEYS):
        return True
    body = " ".join([" ".join(script.get('tags', [])),
                     " ".join(script.get('sentences', []))]).lower()
    return sum(body.count(k) for k in GTA6_KEYS) >= 2


def _probe_duration(path):
    ff = _ffmpeg()
    r = subprocess.run([ff, '-i', path], capture_output=True, text=True)
    import re
    m = re.search(r'Duration: (\d+):(\d+):(\d+\.?\d*)', r.stderr)
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def build_trailer_montage(duration: float, n_segments: int = 3,
                          motion: bool = True) -> str:
    """Cut n random, non-overlapping vertical (1080x1920) segments out of the
    available trailers and stitch them into one silent clip of `duration`
    seconds. Returns the mp4 path or None. motion=False gives the plain
    Shorts look (one still window, no camera move)."""
    trailers = available_trailers()
    if not trailers:
        return None
    try:
        ff = _ffmpeg()
        n = max(1, min(n_segments, 5))
        seg_len = duration / n
        parts = []
        used = {}
        # One source per montage, the lightest first (the 1080p trailer is
        # listed before the 4K one): decoding 4K for every second segment
        # ran at 0.5 fps on the small production box
        for i in range(n):
            t = trailers[0]
            src = _path(t)
            total = _probe_duration(src)
            lo, hi = t['skip_head'], max(t['skip_head'] + seg_len,
                                         total - t['skip_tail'] - seg_len)
            # avoid re-using the same window within one video
            for _ in range(12):
                start = random.uniform(lo, hi)
                if all(abs(start - u) > seg_len for u in used.get(src, [])):
                    break
            used.setdefault(src, []).append(start)
            out = os.path.join(TRAILER_DIR, f'seg_{os.getpid()}_{i}.mp4')
            vf = (motion_vf(i, seg_len) if motion
                  else f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}')
            cmd = [ff, '-y', '-ss', f'{start:.2f}', '-i', src, '-t', f'{seg_len:.2f}',
                   '-an', '-vf', 'crop=ih*9/16:ih,' + vf + ',fps=24',
                   '-c:v', 'libx264', '-preset', 'superfast', '-crf', '20',
                   '-pix_fmt', 'yuv420p', out]
            # the box is small: one 20 s segment took >180 s once while a
            # background proxy job was still running — generous timeout
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=420)
            if r.returncode != 0 or not os.path.exists(out):
                logger.warning(f"Trailer segment failed: {r.stderr[-200:]}")
                continue
            parts.append(out)
        if not parts:
            return None
        lst = os.path.join(TRAILER_DIR, f'concat_{os.getpid()}.txt')
        with open(lst, 'w') as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        montage = os.path.join(TRAILER_DIR, f'montage_{os.getpid()}.mp4')
        r = subprocess.run([ff, '-y', '-f', 'concat', '-safe', '0', '-i', lst,
                            '-c', 'copy', montage],
                           capture_output=True, text=True, timeout=120)
        for p in parts:
            try:
                os.remove(p)
            except OSError:
                pass
        if r.returncode != 0 or not os.path.exists(montage):
            logger.warning(f"Trailer concat failed: {r.stderr[-200:]}")
            return None
        logger.info(f"🎞️ GTA VI trailer montage: {len(parts)} segments "
                    f"from {len(set(used))} trailer(s)")
        return montage
    except Exception as e:
        logger.warning(f"Trailer montage skipped: {e}")
        return None

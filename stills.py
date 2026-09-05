# -*- coding: utf-8 -*-
"""Still images as a moving vertical background.

For topics where the only right footage is a set of official product
images (e.g. the two GTA VI DualSense controllers), the owner hands the bot
a list of image URLs. Each image becomes one segment: the image itself is
fitted to the 1080-px width and floats over a blurred, darkened, zoomed
copy of itself (the classic Shorts look for landscape material), with a
slow push-in or pull-out so nothing ever stands still. Segments are
concatenated into one silent 1080x1920 / 24 fps clip. Fails soft."""
import os
import re
import hashlib
import logging
import subprocess

import requests

logger = logging.getLogger(__name__)

STILL_DIR = os.environ.get('STILL_DIR', '/tmp/stills')
W, H, FPS = 1080, 1920, 24


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def fetch_images(urls: list) -> list:
    """Download images once (by URL hash). Returns local paths in order."""
    os.makedirs(STILL_DIR, exist_ok=True)
    out = []
    for u in urls or []:
        u = str(u).strip()
        if not u:
            continue
        ext = os.path.splitext(u.split('?')[0])[1].lower() or '.jpg'
        if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
            ext = '.jpg'
        dst = os.path.join(STILL_DIR, hashlib.sha1(u.encode()).hexdigest()[:16] + ext)
        if os.path.exists(dst) and os.path.getsize(dst) > 5_000:
            out.append(dst)
            continue
        try:
            r = requests.get(u, timeout=(15, 60),
                             headers={'User-Agent': 'Mozilla/5.0 GridPhantomBot'})
            if r.status_code == 200 and len(r.content) > 5_000:
                with open(dst, 'wb') as f:
                    f.write(r.content)
                out.append(dst)
            else:
                logger.warning(f"Still image HTTP {r.status_code}: {u[:80]}")
        except Exception as e:
            logger.warning(f"Still image failed ({u[:60]}): {e}")
    return out


def build_still_montage(paths: list, duration: float, n_segments: int = 4) -> str:
    """One segment per image (cycling if there are fewer images than
    segments), blurred cover background + fitted foreground, alternating
    slow push-in / pull-out. Returns mp4 path or None."""
    paths = [p for p in paths if p and os.path.exists(p)]
    if not paths:
        return None
    try:
        ff = _ffmpeg()
        n = max(1, min(n_segments, 8))
        seg = duration / n
        frames = max(FPS, int(round(seg * FPS)))
        os.makedirs(STILL_DIR, exist_ok=True)
        parts = []
        for i in range(n):
            src = paths[i % len(paths)]
            zoom_in = (i % 2 == 0)
            z = (f"1+0.10*on/{frames}" if zoom_in else f"1.10-0.10*on/{frames}")
            vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H},boxblur=28:4,eq=brightness=-0.18:saturation=1.15[bg];"
                  f"[0:v]scale={W}:-2[fg];"
                  f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
                  f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                  f":d=1:s={W}x{H}:fps={FPS},setsar=1,format=yuv420p")
            out = os.path.join(STILL_DIR, f'seg_{os.getpid()}_{i}.mp4')
            cmd = [ff, '-y', '-threads', '2', '-loop', '1', '-framerate', str(FPS),
                   '-i', src, '-filter_complex', vf, '-t', f'{seg:.2f}', '-an',
                   '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                   '-x264-params', 'threads=2:lookahead-threads=1:rc-lookahead=10', out]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if r.returncode != 0 or not os.path.exists(out):
                logger.warning(f"Still segment failed: {r.stderr[-200:]}")
                continue
            parts.append(out)
        if not parts:
            return None
        lst = os.path.join(STILL_DIR, f'concat_{os.getpid()}.txt')
        with open(lst, 'w') as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        montage = os.path.join(STILL_DIR, f'montage_{os.getpid()}.mp4')
        r = subprocess.run([ff, '-y', '-f', 'concat', '-safe', '0', '-i', lst,
                            '-c', 'copy', montage],
                           capture_output=True, text=True, timeout=120)
        for p in parts:
            try:
                os.remove(p)
            except OSError:
                pass
        if r.returncode != 0 or not os.path.exists(montage):
            logger.warning(f"Still concat failed: {r.stderr[-200:]}")
            return None
        logger.info(f"🖼️ Still-image montage: {len(parts)} segments from "
                    f"{min(len(paths), len(parts))} image(s)")
        return montage
    except Exception as e:
        logger.warning(f"Still montage skipped: {e}")
        return None

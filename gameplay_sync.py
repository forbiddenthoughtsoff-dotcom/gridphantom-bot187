# -*- coding: utf-8 -*-
"""Owner's own PS5 gameplay clips, pulled from a shared Google Drive folder.

The PlayStation ecosystem has no public API for captures, so the owner's
workflow is deliberately phone-only: PS App -> capture -> Share -> "Save to
Drive" into ONE folder that is shared as "anyone with the link" (viewer).
GAMEPLAY_DRIVE_FOLDER holds that folder's URL or id.

Every new video in the folder is downloaded once into /tmp (never into the
repo), turned into a lean vertical proxy (1080x1920, 24 fps, silent, centre
crop) with ffmpeg so the render never has to chew through 4K60 originals,
and registered in a runtime manifest that video_assembler.pick_gameplay_clip
reads next to the repo's gameplay/manifest.json. Tags come from the file
name ("heist_cayo_nacht.mp4" -> heist, cayo, nacht), so the owner can steer
topic matching simply by naming files. Everything fails soft."""
import os
import re
import json
import time
import logging
import threading
import subprocess

logger = logging.getLogger(__name__)

RUNTIME_DIR = os.environ.get('GAMEPLAY_RUNTIME_DIR', '/tmp/gameplay_drive')
MANIFEST = os.path.join(RUNTIME_DIR, 'manifest.json')
VIDEO_EXT = ('.mp4', '.mov', '.m4v', '.webm', '.mkv')
MAX_CLIPS = 60
MIN_RAW_BYTES = 200_000
# PS5 captures are called "Grand Theft Auto V_20260905143055.mp4" — none of
# that carries topic information
STOP_WORDS = {'grand', 'theft', 'auto', 'the', 'und', 'mit', 'der', 'die',
              'das', 'clip', 'video', 'ps5', 'playstation', 'capture',
              'aufnahme', 'gta', 'online', 'mp4', 'mov', 'img', 'vid',
              'screen', 'recording', 'share', 'factory'}

_lock = threading.Lock()


def folder_id() -> str:
    """Drive folder id from GAMEPLAY_DRIVE_FOLDER (URL or bare id)."""
    s = os.environ.get('GAMEPLAY_DRIVE_FOLDER', '').strip()
    if not s:
        return ''
    m = re.search(r'/folders/([A-Za-z0-9_-]{10,})', s)
    if m:
        return m.group(1)
    m = re.search(r'[?&]id=([A-Za-z0-9_-]{10,})', s)
    if m:
        return m.group(1)
    return s if re.fullmatch(r'[A-Za-z0-9_-]{10,}', s) else ''


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _probe(path):
    """(duration_s, width, height) via ffmpeg's stderr banner."""
    r = subprocess.run([_ffmpeg(), '-i', path], capture_output=True, text=True)
    dur, w, h = 0.0, 0, 0
    m = re.search(r'Duration: (\d+):(\d+):(\d+\.?\d*)', r.stderr)
    if m:
        hh, mm, ss = m.groups()
        dur = int(hh) * 3600 + int(mm) * 60 + float(ss)
    m = re.search(r'Video:.*?\b(\d{2,5})x(\d{2,5})\b', r.stderr)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    return dur, w, h


def tags_from_name(name: str) -> list:
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    toks = re.split(r'[^a-z0-9äöüß]+', stem)
    return sorted({t for t in toks
                   if len(t) >= 3 and not t.isdigit() and t not in STOP_WORDS})


def _load_manifest() -> list:
    try:
        with open(MANIFEST, encoding='utf-8') as f:
            entries = json.load(f)
        return entries if isinstance(entries, list) else []
    except Exception:
        return []


def _save_manifest(entries: list):
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    tmp = MANIFEST + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    os.replace(tmp, MANIFEST)


def runtime_entries() -> list:
    """Manifest entries whose proxy file still exists (container restarts
    wipe /tmp; the next sync re-creates them). Each has an absolute 'path'."""
    out = []
    for e in _load_manifest():
        p = e.get('path', '')
        if p and os.path.exists(p) and os.path.getsize(p) > 100_000:
            out.append(e)
    return out


def make_proxy(src: str, dst: str, timeout: int = 900) -> bool:
    """Vertical 1080x1920 / 24 fps / silent proxy: scale to cover, centre
    crop — works for 16:9, 4K, and already-vertical sources alike."""
    cmd = [_ffmpeg(), '-y', '-i', src, '-an',
           '-vf', ('scale=1080:1920:force_original_aspect_ratio=increase'
                   ':flags=lanczos,crop=1080:1920,fps=24'),
           '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
           '-pix_fmt', 'yuv420p', '-movflags', '+faststart', dst]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning(f"Gameplay proxy timed out: {os.path.basename(src)}")
        return False
    if r.returncode != 0 or not os.path.exists(dst) \
            or os.path.getsize(dst) < 100_000:
        logger.warning(f"Gameplay proxy failed: {r.stderr[-200:]}")
        return False
    return True


def _register(entries: list, drive_id: str, name: str, proxy: str) -> dict:
    dur, w, h = _probe(proxy)
    entry = {'path': proxy, 'drive_id': drive_id, 'name': name,
             'tags': tags_from_name(name), 'duration': round(dur, 1),
             'added': int(time.time())}
    entries.append(entry)
    _save_manifest(entries)
    logger.info(f"🎮 New own gameplay clip: {name} ({dur:.0f}s) → vertical proxy")
    return entry


def sync(time_budget: float = 240.0, lock_wait: float = 30.0) -> list:
    """Download + proxy every new video in the shared folder. Returns the
    usable runtime entries. No-op unless GAMEPLAY_DRIVE_FOLDER is set."""
    fid = folder_id()
    if not fid:
        return []
    if not _lock.acquire(timeout=lock_wait):
        return runtime_entries()  # another sync is busy; use what exists
    try:
        try:
            import gdown
        except ImportError:
            logger.warning("gdown not installed — gameplay sync disabled")
            return runtime_entries()
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        entries = runtime_entries()
        known = {e.get('drive_id') for e in entries}
        try:
            files = gdown.download_folder(id=fid, output=RUNTIME_DIR, quiet=True,
                                          use_cookies=False, skip_download=True)
        except Exception as e:
            logger.warning(f"Drive folder listing failed: {e}")
            return entries
        videos = [f for f in (files or [])
                  if str(getattr(f, 'path', '')).lower().endswith(VIDEO_EXT)]
        new = [f for f in videos if f.id not in known]
        if new:
            logger.info(f"🎮 Gameplay folder: {len(videos)} clips, {len(new)} new")
        t0 = time.time()
        for f in new:
            if len(entries) >= MAX_CLIPS:
                break
            if time.time() - t0 > time_budget:
                logger.info("Gameplay sync paused (time budget) — continues next run")
                break
            name = os.path.basename(str(f.path))
            safe = re.sub(r'[^A-Za-z0-9._-]+', '_', name)[:80]
            raw = os.path.join(RUNTIME_DIR, f'raw_{f.id}_{safe}')
            proxy = os.path.join(RUNTIME_DIR, f'clip_{f.id}.mp4')
            try:
                gdown.download(id=f.id, output=raw, quiet=True, use_cookies=False)
            except Exception as e:
                logger.warning(f"Gameplay download failed ({name}): {e}")
                continue
            try:
                if not os.path.exists(raw) or os.path.getsize(raw) < MIN_RAW_BYTES:
                    logger.warning(f"Gameplay download empty ({name})")
                    continue
                if make_proxy(raw, proxy):
                    _register(entries, f.id, name, proxy)
            finally:
                try:
                    os.remove(raw)  # keep only the lean proxy
                except OSError:
                    pass
        return entries
    except Exception as e:
        logger.warning(f"Gameplay sync skipped: {e}")
        return runtime_entries()
    finally:
        _lock.release()


def sync_async():
    """Background sync (startup + periodic); never blocks the caller."""
    if not folder_id():
        return
    threading.Thread(target=sync, kwargs={'time_budget': 1800.0},
                     daemon=True, name='gameplay-sync').start()

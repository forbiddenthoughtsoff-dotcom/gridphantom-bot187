# -*- coding: utf-8 -*-
"""Owner's own PS5 gameplay clips — runtime library with two sources.

1. PlayStation cloud gallery (psn_captures.py, PSN_NPSSO): the captures the
   PS5 auto-uploads to the PS App, fetched directly. Zero effort per clip.
2. Shared Google Drive folder (GAMEPLAY_DRIVE_FOLDER): PS App -> capture ->
   Share -> "Save to Drive" into ONE folder shared as "anyone with the link".

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
import random
import logging
import threading
import subprocess

logger = logging.getLogger(__name__)

RUNTIME_DIR = os.environ.get('GAMEPLAY_RUNTIME_DIR', '/tmp/gameplay_drive')
MANIFEST = os.path.join(RUNTIME_DIR, 'manifest.json')
VIDEO_EXT = ('.mp4', '.mov', '.m4v', '.webm', '.mkv')
MAX_CLIPS = 80          # proxies kept per container (/tmp is fresh per deploy)
PREFETCH_PER_RUN = 24   # background: how many new clips one sync may pull
JIT_PER_RENDER = 1      # right before a render: one fresh clip, keeps it quick
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
    """Vertical 1080x1920 / 24 fps / silent proxy: drop the bottom 10 %
    of the source first (that is where GTA draws its in-game subtitles,
    which would sit right under our captions), then scale to cover and
    centre crop — works for 16:9, 4K, and already-vertical sources alike."""
    cmd = [_ffmpeg(), '-y', '-i', src, '-an',
           '-vf', ('crop=iw:ih*0.9:0:0,'
                   'scale=1080:1920:force_original_aspect_ratio=increase'
                   ':flags=lanczos,crop=1080:1920,fps=24'),
           '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
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


def analyze_highlights(raw: str, duration: float, window: float = 8.0,
                       max_windows: int = 6) -> list:
    """Find the most action-packed windows of a raw clip: game-audio
    loudness (shots, engines, crashes) plus visual motion (per-frame scene
    change score), both per second, min-max normalised and blended
    (0.6 audio / 0.4 motion). Returns non-overlapping windows sorted by
    score: [{'start', 'end', 'score'}] with score 1.0 for the strongest.
    One decode pass at 160px / 4 fps, so a 3-minute 1080p clip takes well
    under a minute. Fails soft to a single window."""
    try:
        if duration < window + 1.0:
            return [{'start': 0.0, 'end': round(duration, 2), 'score': 1.0}]
        ff = _ffmpeg()
        meta = raw + '.stats.txt'
        # signalstats per frame: YDIF = motion, SATAVG = colourfulness (menus,
        # loading screens and map overlays are grey/dark), YAVG = brightness
        vpart = f"[0:v]scale=160:-2,fps=4,signalstats,metadata=print:file={meta}[v]"
        cmd = [ff, '-hide_banner', '-nostats', '-i', raw, '-filter_complex',
               vpart + ";[0:a]ebur128=peak=none[a]", '-map', '[v]', '-map', '[a]',
               '-f', 'null', '-']
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:  # e.g. no audio stream: motion only
            cmd = [ff, '-hide_banner', '-nostats', '-i', raw, '-filter_complex',
                   vpart, '-map', '[v]', '-f', 'null', '-']
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        n = int(duration) + 1
        aud = [None] * n
        for m in re.finditer(r't:\s*([\d.]+)\s+TARGET:[^\n]*?M:\s*(-?[\d.]+|-inf)', r.stderr):
            sec = min(n - 1, int(float(m.group(1))))
            v = -70.0 if m.group(2) == '-inf' else max(-70.0, float(m.group(2)))
            aud[sec] = v if aud[sec] is None else max(aud[sec], v)
        mot, sat, lum, cnt = [0.0] * n, [0.0] * n, [0.0] * n, [0] * n
        try:
            sec = 0
            with open(meta, encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if 'pts_time:' in line:
                        m = re.search(r'pts_time:([\d.]+)', line)
                        if m:
                            sec = min(n - 1, int(float(m.group(1))))
                            cnt[sec] += 1
                    elif 'signalstats.YDIF=' in line:
                        mot[sec] += float(line.rsplit('=', 1)[1])
                    elif 'signalstats.SATAVG=' in line:
                        sat[sec] += float(line.rsplit('=', 1)[1])
                    elif 'signalstats.YAVG=' in line:
                        lum[sec] += float(line.rsplit('=', 1)[1])
        finally:
            try:
                os.remove(meta)
            except OSError:
                pass
        for i in range(n):
            if cnt[i]:
                mot[i] /= cnt[i]
                sat[i] /= cnt[i]
                lum[i] /= cnt[i]

        def norm(vals):
            vals = [v if v is not None else min(x for x in vals if x is not None)
                    if any(x is not None for x in vals) else 0.0 for v in vals]
            lo, hi = min(vals), max(vals)
            return [(v - lo) / (hi - lo) if hi > lo else 0.0 for v in vals]

        a_n = norm(aud) if any(v is not None for v in aud) else [0.0] * n
        m_n, s_n = norm(mot), norm(sat)
        wa = 0.45 if any(a_n) else 0.0
        score = [wa * a_n[i] + (0.90 - wa) * m_n[i] + 0.10 * s_n[i] for i in range(n)]
        # menus, map overlays, loading and black screens: grey and/or dark
        # and nearly static — never a highlight, whatever the radio plays
        sat_ok = sorted(sat)[len(sat) // 2] * 0.6 if any(sat) else 0.0
        for i in range(n):
            if cnt[i] and (sat[i] < sat_ok or lum[i] < 22.0 or m_n[i] < 0.08):
                score[i] *= 0.15
        w = max(2, int(window))
        sums = [sum(score[i:i + w]) for i in range(0, max(1, n - w))]
        taken, out = [False] * len(sums), []
        for _ in range(max_windows):
            best_i, best_v = -1, -1.0
            for i, v in enumerate(sums):
                if not taken[i] and v > best_v:
                    best_i, best_v = i, v
            if best_i < 0 or best_v <= 0:
                break
            out.append({'start': float(best_i), 'end': float(min(duration, best_i + w)),
                        'score': best_v})
            for i in range(max(0, best_i - w + 1), min(len(sums), best_i + w)):
                taken[i] = True
        if not out:
            return [{'start': 0.0, 'end': round(min(duration, w), 2), 'score': 1.0}]
        top = out[0]['score'] or 1.0
        for h in out:
            h['score'] = round(h['score'] / top, 3)
        return out
    except Exception as e:
        logger.warning(f"Highlight analysis skipped: {e}")
        return [{'start': 0.0, 'end': round(min(duration, window), 2), 'score': 1.0}]


def auto_tags(proxy: str, duration: float) -> list:
    """What is actually in the clip: three frames → Claude vision → a
    handful of German keyword tags (car, chase, police, night, plane,
    parachute, heist ...). PS5 capture names carry no topic, so this is what
    makes topic matching work. Costs a fraction of a cent per clip; fails
    soft to no tags."""
    key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not key or duration <= 0:
        return []
    frames = []
    try:
        import base64
        import anthropic
        ff = _ffmpeg()
        for t in (duration * 0.2, duration * 0.5, duration * 0.8):
            out = proxy + f'.tag{int(t)}.jpg'
            subprocess.run([ff, '-y', '-loglevel', 'error', '-ss', f'{t:.1f}',
                            '-i', proxy, '-frames:v', '1', '-vf', 'scale=360:-2',
                            '-q:v', '5', out], capture_output=True, timeout=60)
            if os.path.exists(out):
                with open(out, 'rb') as f:
                    frames.append(base64.b64encode(f.read()).decode())
                os.remove(out)
        if not frames:
            return []
        content = [{'type': 'image', 'source': {'type': 'base64',
                    'media_type': 'image/jpeg', 'data': fr}} for fr in frames]
        content.append({'type': 'text', 'text': (
            'These are three frames from ONE GTA Online (GTA 5) gameplay clip. '
            'Return ONLY a JSON array of 5-10 lowercase German keyword tags for '
            'what happens and where, e.g. "auto", "verfolgungsjagd", "polizei", '
            '"nacht", "flugzeug", "helikopter", "fallschirm", "heist", '
            '"schiesserei", "motorrad", "strand", "stadt", "wueste", "boot", '
            '"explosion", "rennen", "tuning", "casino", "bunker". No sentences.')})
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(model='claude-haiku-4-5-20251001',
                                     max_tokens=120,
                                     messages=[{'role': 'user', 'content': content}])
        txt = msg.content[0].text
        m = re.search(r'\[.*?\]', txt, re.S)
        tags = json.loads(m.group(0)) if m else []
        return sorted({str(t).lower().strip() for t in tags
                       if str(t).strip() and len(str(t)) < 30})[:12]
    except Exception as e:
        logger.warning(f"Auto-tagging skipped: {e}")
        return []


def _register(entries: list, drive_id: str, name: str, proxy: str,
              highlights: list = None) -> dict:
    dur, w, h = _probe(proxy)
    tags = sorted(set(tags_from_name(name)) | set(auto_tags(proxy, dur)))
    entry = {'path': proxy, 'drive_id': drive_id, 'name': name,
             'tags': tags, 'duration': round(dur, 1),
             'highlights': highlights or [], 'added': int(time.time())}
    entries.append(entry)
    _save_manifest(entries)
    logger.info(f"🎮 New own gameplay clip: {name} ({dur:.0f}s, "
                f"{len(entry['highlights'])} highlights, tags {tags[:6]}) → vertical proxy")
    return entry


def sources() -> list:
    """Configured clip sources, for the startup log."""
    out = []
    try:
        import psn_captures
        if psn_captures.enabled():
            out.append('PlayStation cloud gallery')
    except Exception:
        pass
    if folder_id():
        out.append('Google Drive folder')
    return out


def _budget_left(t0: float, time_budget: float) -> bool:
    if time.time() - t0 > time_budget:
        logger.info("Gameplay sync paused (time budget) — continues next run")
        return False
    return True


def _ingest(entries: list, uid: str, name: str, raw: str, proxy: str):
    """raw download -> vertical proxy -> manifest; the raw file is always
    removed, only the lean proxy stays."""
    try:
        if not os.path.exists(raw) or os.path.getsize(raw) < MIN_RAW_BYTES:
            logger.warning(f"Gameplay download empty ({name})")
            return
        # highlights are analysed on the raw file: it still has the game audio
        dur, _, _ = _probe(raw)
        highlights = analyze_highlights(raw, dur) if dur > 0 else []
        if make_proxy(raw, proxy):
            _register(entries, uid, name, proxy, highlights)
    finally:
        try:
            os.remove(raw)
        except OSError:
            pass


def _sync_drive(entries: list, fid: str, t0: float, time_budget: float,
                max_new: int):
    try:
        import gdown
    except ImportError:
        logger.warning("gdown not installed — Drive gameplay sync disabled")
        return
    known = {e.get('drive_id') for e in entries}
    try:
        files = gdown.download_folder(id=fid, output=RUNTIME_DIR, quiet=True,
                                      use_cookies=False, skip_download=True)
    except Exception as e:
        logger.warning(f"Drive folder listing failed: {e}")
        return
    videos = [f for f in (files or [])
              if str(getattr(f, 'path', '')).lower().endswith(VIDEO_EXT)]
    new = [f for f in videos if f.id not in known]
    if new:
        logger.info(f"🎮 Drive folder: {len(videos)} clips, {len(new)} new")
    random.shuffle(new)
    for f in new[:max_new]:
        if len(entries) >= MAX_CLIPS or not _budget_left(t0, time_budget):
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
        _ingest(entries, f.id, name, raw, proxy)


def _sync_psn(entries: list, t0: float, time_budget: float, max_new: int):
    import psn_captures as psn
    known = {e.get('drive_id') for e in entries}
    try:
        items, sign = psn.list_captures(limit=500)
    except Exception as e:
        logger.error(f"PlayStation gallery unavailable: {e}")
        return
    videos = [i for i in items if psn.is_gta_video(i)]
    new = [i for i in videos if f"psn:{i.get('id')}" not in known]
    logger.info(f"🎮 PlayStation gallery: {len(items)} captures, "
                f"{len(videos)} GTA videos, {len(new)} not yet local, "
                f"pulling up to {max_new}")
    # The library can hold hundreds of clips and /tmp is fresh per deploy:
    # pull a random sample per run instead of everything, so every
    # container ends up with a different, varied pool
    random.shuffle(new)
    for i in new[:max_new]:
        if len(entries) >= MAX_CLIPS or not _budget_left(t0, time_budget):
            break
        uid = f"psn:{i.get('id')}"
        safe = re.sub(r'[^A-Za-z0-9_-]+', '_', str(i.get('id')))[:60]
        raw = os.path.join(RUNTIME_DIR, f'raw_psn_{safe}.mp4')
        proxy = os.path.join(RUNTIME_DIR, f'clip_psn_{safe}.mp4')
        if not psn.download(i, sign, raw):
            continue
        _ingest(entries, uid, psn.display_name(i), raw, proxy)


def sync(time_budget: float = 240.0, lock_wait: float = 30.0,
         max_new: int = PREFETCH_PER_RUN) -> list:
    """Pull up to `max_new` new clips from all configured sources into the
    runtime library (download once, highlight analysis, vertical proxy).
    Returns the usable entries. No-op when nothing is configured."""
    fid = folder_id()
    try:
        import psn_captures
        psn_on = psn_captures.enabled()
    except Exception:
        psn_on = False
    if not fid and not psn_on:
        return []
    if not _lock.acquire(timeout=lock_wait):
        return runtime_entries()  # another sync is busy; use what exists
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        entries = runtime_entries()
        t0 = time.time()
        if psn_on:
            _sync_psn(entries, t0, time_budget, max_new)
        if fid:
            _sync_drive(entries, fid, t0, time_budget, max_new)
        return entries
    except Exception as e:
        logger.warning(f"Gameplay sync skipped: {e}")
        return runtime_entries()
    finally:
        _lock.release()


def sync_async():
    """Background sync (startup + periodic); never blocks the caller."""
    if not sources():
        return
    threading.Thread(target=sync, kwargs={'time_budget': 1800.0},
                     daemon=True, name='gameplay-sync').start()

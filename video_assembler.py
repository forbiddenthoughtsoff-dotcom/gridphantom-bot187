# -*- coding: utf-8 -*-
import os
import json
import logging
import random
import subprocess
import requests
import numpy as np
from motion import motion_vf, GRADE
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (VideoClip, AudioFileClip, ImageClip,
                            VideoFileClip, CompositeVideoClip,
                            concatenate_videoclips, vfx)

logger = logging.getLogger(__name__)

W, H = 1080, 1920


_FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


def load_font(size):
    # Bundled fonts FIRST — guaranteed to exist on any container, so German
    # umlauts (ä ö ü ß) always render instead of falling back to PIL's default
    # bitmap font, which draws them as empty boxes (□).
    for path in [
        os.path.join(_FONTS_DIR, "DejaVuSans-Bold.ttf"),
        os.path.join(_FONTS_DIR, "DejaVuSans.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    # Should never happen now that fonts are bundled — but if it does, make it
    # LOUD instead of silently shipping boxes to production.
    logger.error("No TrueType font found — umlauts WILL render as boxes! "
                 "Check that fonts/ is present in the deployment.")
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_overlay(text: str):
    """Static foreground layer (gradient + text + branding) as RGBA arrays.
    Kept separate from the background so the background can move while
    the text stays rock-steady and readable."""
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(layer)

    # Dark gradient bottom half — makes text readable on any background
    for y in range(int(H * 0.25), H):
        alpha = int(220 * (y - H * 0.25) / (H * 0.75))
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    draw = gd

    # Balanced readable font - clear without dominating the image
    font_size = 80
    max_w = int(W * 0.85)

    def wrap_text(font, size):
        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    while font_size > 56:
        font = load_font(font_size)
        lines = wrap_text(font, font_size)
        if len(lines) <= 5:
            break
        font_size -= 6

    font = load_font(font_size)
    lines = wrap_text(font, font_size)
    line_h = int(font_size * 1.15)
    total_h = len(lines) * line_h
    start_y = int(H * 0.68) - total_h // 2  # Lower third

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2
        y = start_y + i * line_h
        # Strong shadow for max readability
        shadow_offset = max(6, font_size // 20)
        for dx in [-shadow_offset, 0, shadow_offset]:
            for dy in [-shadow_offset, 0, shadow_offset]:
                if dx or dy:
                    draw.text((x+dx, y+dy), line, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

    # Branding bottom
    fb = load_font(48)
    brand = "@GridPhantom187"
    bw = draw.textbbox((0, 0), brand, font=fb)[2]
    draw.text(((W - bw)//2, H - 130), brand, font=fb, fill=(220, 220, 220, 255))

    arr = np.asarray(layer, dtype=np.float32)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3:4] / 255.0
    return rgb, alpha


# Captions are rendered as a narrow BAND, not a full frame: with 20+ pop-in
# groups per video, full-frame float layers blew container memory and the
# render got OOM-killed mid-slot (crash-restarts at 22:01 / 07:00). A band is
# ~6x smaller; uint8 rgb + float32 mask keep it lean.
CAPTION_BAND_H = 340
CAPTION_Y = int(H * 0.60)
BRAND_BAND_H = 150
BRAND_Y = H - BRAND_BAND_H


def _fit_lines(d, text: str, max_w: int, start: int, floor: int):
    """Largest font size in [floor, start] (steps of 8) at which every line
    of `text` fits max_w including the stroke. Returns
    (font, size, stroke, lines, fits)."""
    lines = text.split('\n')
    size = start
    while True:
        font = load_font(size)
        stroke = max(6, size // 11)
        widest = 0
        for ln in lines:
            b = d.textbbox((0, 0), ln, font=font, stroke_width=stroke)
            widest = max(widest, b[2] - b[0])
        if widest <= max_w:
            return font, size, stroke, lines, True
        if size - 8 < floor:
            return font, size, stroke, lines, False
        size -= 8


def _split_two_lines(text: str):
    """Break a caption at the word boundary that balances both lines."""
    words = text.split()
    if len(words) < 2:
        return None
    best, best_diff = None, None
    for i in range(1, len(words)):
        a, b = ' '.join(words[:i]), ' '.join(words[i:])
        diff = abs(len(a) - len(b))
        if best_diff is None or diff < best_diff:
            best, best_diff = a + '\n' + b, diff
    return best


SPEAKER_FILL = {'ava': (255, 255, 255, 255), 'ben': (255, 214, 0, 255)}
SIGNAL_FILL = (255, 214, 0, 255)
SIGNAL_WORDS = ('fehler', 'niemand', 'geheim', 'verboten', 'kostenlos', 'gratis',
                'sofort', ' nie ', 'niemals', 'verlierst', 'kostet', 'millionen',
                'million', 'gta$', 'dollar', 'bestätigt', 'offiziell', 'leak',
                'mythos', 'fakt', 'endlich', 'achtung', 'falsch')


def is_signal_text(text: str) -> bool:
    """Caption groups with a number or a trigger word get the signal colour —
    a visual pattern interrupt on exactly the words the ear latches onto."""
    t = ' ' + text.lower() + ' '
    return any(ch.isdigit() for ch in text) or any(w in t for w in SIGNAL_WORDS)


def make_caption_layer(text: str, fill=(255, 255, 255, 255)):
    """Pro-style pop-in caption band: big bold centered text with a hard
    black stroke. Long German compounds ("Minispielen und Beschaeftigungen")
    used to overflow the frame — the text is now fitted: shrink a little,
    then break into two balanced lines, then shrink further. Nothing is ever
    cut off at the frame edge.
    Returns (rgb uint8 [band,W,3], alpha float32 [band,W])."""
    layer = Image.new('RGBA', (W, CAPTION_BAND_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    max_w = int(W * 0.92)
    font, size, stroke, lines, ok = _fit_lines(d, text, max_w, 112, 72)
    if not ok:
        two = _split_two_lines(text)
        if two:
            font, size, stroke, lines, ok = _fit_lines(d, two, max_w, 96, 56)
        if not ok:  # a single very long word: keep shrinking, never clip
            font, size, stroke, lines, ok = _fit_lines(
                d, '\n'.join(lines), max_w, size, 32)

    line_h = int(size * 1.12)
    y0 = (CAPTION_BAND_H - line_h * len(lines)) // 2
    for i, ln in enumerate(lines):
        bbox = d.textbbox((0, 0), ln, font=font, stroke_width=stroke)
        x = (W - (bbox[2] - bbox[0])) // 2 - bbox[0]
        y = y0 + i * line_h + (line_h - (bbox[3] - bbox[1])) // 2 - bbox[1]
        d.text((x, y), ln, font=font, fill=fill,
               stroke_width=stroke, stroke_fill=(0, 0, 0, 255))

    arr = np.asarray(layer, dtype=np.uint8)
    return arr[:, :, :3].copy(), arr[:, :, 3].astype(np.float32) / 255.0


class CaptionTrack:
    """Time-indexed caption bands rendered lazily (see the overlay loop in
    _assemble). frame(t)/mask(t) are moviepy make_frame callables; frames
    outside any span are fully transparent."""

    def __init__(self, groups: list, duration: float):
        self.spans = []
        for i, g in enumerate(groups):
            start = min(float(g['start']), duration)
            if i + 1 < len(groups):
                end = min(float(groups[i + 1]['start']), duration)
            else:
                end = min(float(g['end']) + 0.8, duration)
            if end > start:
                # (start, end, text, speaker) — speaker colours the dialogue format
                self.spans.append((start, end, g['text'], g.get('speaker')))
        self._cache = {}
        self._empty_rgb = np.zeros((CAPTION_BAND_H, W, 3), dtype=np.uint8)
        self._empty_mask = np.zeros((CAPTION_BAND_H, W), dtype=np.float32)
        self._last = 0

    def _index(self, t: float):
        # frames are requested in order: start from the last hit
        n = len(self.spans)
        i = self._last if self._last < n else 0
        if self.spans[i][0] > t:
            i = 0
        while i < n and self.spans[i][1] <= t:
            i += 1
        if i < n and self.spans[i][0] <= t < self.spans[i][1]:
            self._last = i
            return i
        return None

    def _layer(self, i: int):
        if i not in self._cache:
            if len(self._cache) >= 2:
                self._cache.pop(min(self._cache))
            sp = self.spans[i][3]
            fill = SPEAKER_FILL.get(sp, (255, 255, 255, 255))
            if sp is None and is_signal_text(self.spans[i][2]):
                fill = SIGNAL_FILL   # numbers / trigger words pop in yellow
            self._cache[i] = make_caption_layer(self.spans[i][2], fill)
        return self._cache[i]

    def frame(self, t: float):
        i = self._index(t)
        return self._empty_rgb if i is None else self._layer(i)[0]

    def mask(self, t: float):
        i = self._index(t)
        return self._empty_mask if i is None else self._layer(i)[1]


def make_brand_layer():
    """Small static channel handle band for the bottom of the frame."""
    layer = Image.new('RGBA', (W, BRAND_BAND_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fb = load_font(44)
    brand = "@GridPhantom187"
    bw = d.textbbox((0, 0), brand, font=fb, stroke_width=4)[2]
    d.text(((W - bw) // 2, 30), brand, font=fb,
           fill=(235, 235, 235, 255), stroke_width=4, stroke_fill=(0, 0, 0, 255))
    arr = np.asarray(layer, dtype=np.uint8)
    return arr[:, :, :3].copy(), arr[:, :, 3].astype(np.float32) / 255.0


SUB_BAND_H = 150
SUB_Y = CAPTION_Y + CAPTION_BAND_H + 60   # between captions and brand


def make_subscribe_layer():
    """Red 'ABONNIEREN' pill — the on-screen subscribe nudge every Short
    shows for a few seconds in its last third (subs are the bottleneck for
    monetisation, views alone are not). Same band format as the captions."""
    layer = Image.new('RGBA', (W, SUB_BAND_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    font = load_font(58)
    text = "ABONNIEREN"
    tw = d.textbbox((0, 0), text, font=font)[2]
    pw, ph = tw + 150, 108
    x0, y0 = (W - pw) // 2, (SUB_BAND_H - ph) // 2
    d.rounded_rectangle((x0 + 4, y0 + 6, x0 + pw + 4, y0 + ph + 6), radius=54,
                        fill=(0, 0, 0, 140))                      # soft shadow
    d.rounded_rectangle((x0, y0, x0 + pw, y0 + ph), radius=54,
                        fill=(230, 33, 23, 255))
    # bell glyph drawn by hand (the bundled font has no emoji)
    bx, by = x0 + 46, y0 + ph // 2
    d.pieslice((bx - 22, by - 30, bx + 22, by + 14), 180, 360, fill=(255, 255, 255, 255))
    d.rectangle((bx - 22, by - 8, bx + 22, by + 14), fill=(255, 255, 255, 255))
    d.rectangle((bx - 30, by + 12, bx + 30, by + 20), fill=(255, 255, 255, 255))
    d.ellipse((bx - 9, by + 20, bx + 9, by + 34), fill=(255, 255, 255, 255))
    tb = d.textbbox((0, 0), text, font=font)
    d.text((x0 + 96, y0 + (ph - (tb[3] - tb[1])) // 2 - tb[1]), text,
           font=font, fill=(255, 255, 255, 255))
    arr = np.asarray(layer, dtype=np.uint8)
    return arr[:, :, :3].copy(), arr[:, :, 3].astype(np.float32) / 255.0


def save_layer_png(rgb, alpha, path: str) -> str:
    """Write a (rgb uint8, alpha float) band as an RGBA PNG for ffmpeg overlays."""
    a = (np.clip(alpha, 0, 1) * 255).astype(np.uint8)[:, :, None]
    Image.fromarray(np.concatenate([rgb, a], axis=2), 'RGBA').save(path)
    return path


def build_caption_groups(narration: str, tts_words: list,
                         max_words: int = 3, max_chars: int = 22) -> list:
    """Caption chunks built from the ORIGINAL narration text, timed by the
    TTS word boundaries. Never render the TTS tokens themselves: the speech
    engine normalizes text ("GTA 6" can become "GTA sechs", "60fps" gets
    mangled), which showed up on screen as apparent spelling errors.
    Returns [{'text', 'start', 'end'}] with proportional timing mapping."""
    orig = narration.split()
    if not orig or not tts_words:
        return []

    chunks, cur = [], []
    for w in orig:
        # long compounds: flush early so a group stays one readable line
        joined = len(' '.join(cur + [w]))
        if cur and joined > max_chars:
            # ...but don't strand a tiny function word ("eine", "und") on
            # its own beat if the pair still fits on two lines
            orphan = len(cur) == 1 and len(cur[0]) <= 4
            if not (orphan and joined <= max_chars + 6):
                chunks.append(cur)
                cur = []
        cur.append(w)
        if len(cur) >= max_words or w.rstrip('"\'»«')[-1:] in '.!?,:':
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)

    n, m = len(orig), len(tts_words)
    groups, idx = [], 0
    for c in chunks:
        ti = min(m - 1, int(idx * m / n))
        te = min(m - 1, max(ti, int((idx + len(c)) * m / n) - 1))
        groups.append({'text': ' '.join(c),
                       'start': tts_words[ti]['start'],
                       'end': tts_words[te]['end'],
                       'speaker': tts_words[ti].get('speaker')})
        idx += len(c)
    return groups


GAMEPLAY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gameplay")
MUSIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music")
MUSIC_VOLUME = 0.20  # bed level before sidechain ducking under the voice


def add_music_bed(video_path: str, duration: float):
    """Production value: mix a royalty-free music bed under the narration,
    sidechain-ducked so the voice always stays on top (like a produced
    Short, not a TTS readout). Returns (video_path, credit_or_None).
    Fails soft — on any problem the dry mix is kept."""
    manifest = os.path.join(MUSIC_DIR, "manifest.json")
    if not os.path.exists(manifest):
        return video_path, None
    try:
        import subprocess
        import imageio_ffmpeg
        tracks = [t for t in json.load(open(manifest, encoding="utf-8"))
                  if os.path.exists(os.path.join(MUSIC_DIR, t.get("file", "")))]
        if not tracks:
            return video_path, None
        track = random.choice(tracks)
        music = os.path.join(MUSIC_DIR, track["file"])
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        out = video_path[:-4] + "_music.mp4"
        fade_out = max(duration - 1.5, 0.0)
        filt = (f"[1:a]atrim=0:{duration:.2f},afade=t=in:st=0:d=1,"
                f"afade=t=out:st={fade_out:.2f}:d=1.5,volume={MUSIC_VOLUME}[m];"
                f"[0:a]asplit=2[v1][v2];"
                f"[m][v1]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=350[duck];"
                f"[duck][v2]amix=inputs=2:duration=first:dropout_transition=0,volume=1.3[a]")
        cmd = [ff, "-y", "-i", video_path, "-stream_loop", "-1", "-i", music,
               "-filter_complex", filt, "-map", "0:v", "-map", "[a]",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-t", f"{duration:.2f}", out]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        if r.returncode != 0 or not os.path.exists(out):
            logger.warning(f"Music bed failed, keeping dry mix: {r.stderr[-300:]}")
            return video_path, None
        os.replace(out, video_path)
        logger.info(f"🎵 Music bed: {track.get('title')} (ducked under voice)")
        return video_path, track.get("credit")
    except Exception as e:
        logger.warning(f"Music bed skipped: {e}")
        return video_path, None


def _gameplay_entries() -> list:
    """Own clips from the repo manifest (gameplay/manifest.json) plus the
    runtime clips synced from the owner's shared Drive folder
    (gameplay_sync). Each entry gets an absolute 'path'; missing files are
    dropped."""
    entries = []
    manifest_path = os.path.join(GAMEPLAY_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        try:
            for e in json.load(open(manifest_path, encoding="utf-8")):
                e = dict(e)
                e['path'] = os.path.join(GAMEPLAY_DIR, e.get('file', ''))
                entries.append(e)
        except Exception as e:
            logger.warning(f"Gameplay manifest unreadable: {e}")
    try:
        from gameplay_sync import runtime_entries
        entries.extend(runtime_entries())
    except Exception as e:
        logger.warning(f"Runtime gameplay library unavailable: {e}")
    return [e for e in entries if e.get('path') and os.path.exists(e['path'])]


def _script_haystack(script: dict) -> str:
    return " ".join([
        script.get("title", ""),
        " ".join(script.get("tags", [])),
        " ".join(script.get("sentences", []))]).lower()


def _topic_score(entry: dict, haystack: str) -> int:
    return sum(1 for t in entry.get("tags", []) if str(t).lower() in haystack)


def build_gameplay_montage(script: dict, duration: float, n_segments: int = 3,
                           require_match: bool = False) -> str:
    """Highlight cut from the owner's own clips: the strongest action
    windows (game-audio loudness + motion, analysed at sync time) across the
    whole library, one hard cut per sentence, strongest window first as the
    hook. Spreads across different clips before reusing one. Topic-tagged
    clips take precedence; with require_match only tagged clips qualify.
    Returns a silent 1080x1920 mp4 path or None (caller falls back)."""
    entries = [e for e in _gameplay_entries() if e.get('highlights')]
    if not entries:
        return None
    try:
        haystack = _script_haystack(script)
        pool = []
        for e in entries:
            topic = _topic_score(e, haystack)
            if require_match and topic == 0:
                continue
            for h in e['highlights']:
                pool.append({'topic': topic, 'score': float(h.get('score', 0.0)),
                             'path': e['path'], 'start': float(h['start']),
                             'end': float(h['end']),
                             'dur': float(e.get('duration') or 0.0)})
        if not pool:
            return None
        n = max(1, min(n_segments, 6))
        # Coherent cut: one recording at a time, its best windows in
        # chronological order, best-matching/strongest recording first — the
        # footage keeps its own little story instead of jumping between
        # unrelated clips every sentence. A second clip only fills what the
        # first cannot cover.
        by_clip = {}
        for p in pool:
            by_clip.setdefault(p['path'], []).append(p)
        clips = sorted(by_clip.values(),
                       key=lambda ws: (ws[0]['topic'], sum(w['score'] for w in ws)),
                       reverse=True)
        chosen, per_clip = [], {}
        for ws in clips:
            if len(chosen) >= n:
                break
            best = sorted(ws, key=lambda w: w['score'], reverse=True)[:n - len(chosen)]
            take = sorted(best, key=lambda w: w['start'])
            chosen.extend(take)
            per_clip[ws[0]['path']] = len(take)
        seg_len = duration / len(chosen)
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        out_dir = '/tmp/gameplay_montage'
        os.makedirs(out_dir, exist_ok=True)
        parts = []
        for i, p in enumerate(chosen):
            clip_dur = p['dur'] if p['dur'] > 0 else p['end'] + 1.0
            length = min(seg_len, clip_dur)
            center = (p['start'] + p['end']) / 2.0
            start = max(0.0, min(center - length / 2.0, clip_dur - length))
            out = os.path.join(out_dir, f'seg_{os.getpid()}_{i}.mp4')
            cmd = [ff, '-y', '-ss', f'{start:.2f}', '-i', p['path'],
                   '-t', f'{length:.2f}', '-an', '-r', '24',  # noqa
                   '-vf', GRADE + ',' + motion_vf(i, length),  # slow push/pan per cut
                   '-c:v', 'libx264', '-preset', 'superfast', '-crf', '20',
                   '-pix_fmt', 'yuv420p', out]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode == 0 and os.path.exists(out):
                parts.append(out)
            else:
                logger.warning(f"Gameplay segment failed: {r.stderr[-160:]}")
        if not parts:
            return None
        lst = os.path.join(out_dir, f'concat_{os.getpid()}.txt')
        with open(lst, 'w') as f:
            for part in parts:
                f.write(f"file '{part}'\n")
        montage = os.path.join(out_dir, f'montage_{os.getpid()}.mp4')
        r = subprocess.run([ff, '-y', '-f', 'concat', '-safe', '0', '-i', lst,
                            '-c', 'copy', montage],
                           capture_output=True, text=True, timeout=120)
        for part in parts:
            try:
                os.remove(part)
            except OSError:
                pass
        if r.returncode != 0 or not os.path.exists(montage):
            logger.warning(f"Gameplay concat failed: {r.stderr[-160:]}")
            return None
        logger.info(f"🎮 Own gameplay highlight cut: {len(parts)} segments from "
                    f"{len(per_clip)} clip(s), library {len(entries)}")
        return montage
    except Exception as e:
        logger.warning(f"Gameplay highlight cut skipped: {e}")
        return None


def pick_gameplay_clip(script: dict, require_match: bool = False) -> str:
    """Pick the owner's own GTA gameplay clip that best matches the video's
    topic via tag overlap. Returns a local mp4 path or None. Only the
    channel owner's OWN recordings live here — never downloaded third-party
    footage (copyright). With require_match a clip is only returned when at
    least one tag matches (GTA 6 topics: the official trailer beats
    untagged GTA 5 gameplay)."""
    entries = _gameplay_entries()
    if not entries:
        return None

    haystack = _script_haystack(script)
    scored = [(_topic_score(e, haystack), e['path']) for e in entries]
    best = max(s for s, _ in scored)
    if require_match and best == 0:
        return None
    # Topic match wins; with no match, any own-gameplay clip still beats
    # generic stock — pick randomly for variety.
    candidates = [p for s, p in scored if s == best]
    choice = random.choice(candidates)
    logger.info(f"🎮 Own gameplay clip: {os.path.basename(choice)} "
                f"(match score {best}, library {len(entries)})")
    return choice


class VideoAssembler:
    def __init__(self):
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def assemble(self, script: dict, audio_path: str) -> str:
        """Render with the 'render busy' flag raised so the background clip
        sync pauses its ffmpeg jobs (the container has ~1 GB; a proxy job
        next to a render got both OOM-killed)."""
        flag = None
        try:
            from gameplay_sync import RENDER_BUSY as flag
            flag.set()
        except Exception:
            flag = None
        try:
            return self._assemble(script, audio_path)
        finally:
            if flag is not None:
                flag.clear()

    def _assemble(self, script: dict, audio_path: str) -> str:
        output_path = f"{self.output_dir}/video_en_{random.randint(1000,9999)}.mp4"

        audio = AudioFileClip(audio_path)
        # Shorts may run up to 3 minutes; owner assignments speak 60-70 s.
        # The old 58 s cap would have cut the narration mid-sentence.
        duration = min(audio.duration, 120)

        image_prompt = script.get('image_prompt', 'neon-lit night city skyline with a luxury sports car, dramatic cinematic lighting, high contrast, ultra detailed, 8k')
        sentences = script.get('sentences', [script.get('narration', '')])
        if not sentences:
            sentences = [script.get('narration', '')]

        seg_dur = duration / len(sentences)

        # Background priority: 1) own gameplay clip tagged for the topic,
        # 2) official GTA VI trailer montage (GTA 6 topics), 3) any own
        # gameplay clip, 4) topic-matched Pexels stock, 5) AI image + Ken Burns
        base = None
        cuts_n = 0
        # subscribe pill timing (also the cue for its pop sound)
        sub_start = min(duration * 0.58, max(duration - 6.0, 0.0))
        try:
            gta6, build_trailer_montage = False, None
            try:
                from trailer_library import is_gta6_topic, build_trailer_montage
                gta6 = is_gta6_topic(script)
            except Exception as e:
                logger.warning(f"Trailer library unavailable: {e}")
            # GTA 6 topics: an own clip only when it is tagged for the topic
            # (e.g. "gta6" in the file name) — otherwise Rockstar's official
            # trailer beats GTA 5 gameplay
            n_seg = len(sentences) or 3
            bg_path = None
            cuts_n = 0   # hard cuts in the background (for the whoosh sound design)
            # Owner-supplied stills (e.g. official product images for a
            # hardware topic) are the only right footage — they win outright
            if script.get('still_images'):
                try:
                    from stills import fetch_images, build_still_montage
                    bg_path = build_still_montage(
                        fetch_images(script['still_images']), duration, max(n_seg, 4))
                except Exception as e:
                    logger.warning(f"Still images unavailable: {e}")
            if bg_path:
                cuts_n = max(n_seg, 4)
            if not bg_path:
                bg_path = build_gameplay_montage(script, duration, n_seg, require_match=gta6)
                cuts_n = n_seg if bg_path else 0
                if not bg_path:
                    bg_path = pick_gameplay_clip(script, require_match=gta6)
            if not bg_path and build_trailer_montage:
                # official trailer footage is the last resort for every topic:
                # better looking than stock and always on disk
                try:
                    bg_path = build_trailer_montage(duration, n_segments=n_seg)
                    cuts_n = n_seg if bg_path else 0
                except Exception as e:
                    logger.warning(f"Trailer footage unavailable: {e}")
            if not bg_path:
                bg_path = build_gameplay_montage(script, duration, n_seg)
                cuts_n = n_seg if bg_path else 0
                if not bg_path:
                    bg_path = pick_gameplay_clip(script)
            if bg_path:
                base = VideoFileClip(bg_path).without_audio()
                scale = max(W / base.w, H / base.h)
                base = base.resize(scale).crop(
                    x_center=base.w * scale / 2, y_center=base.h * scale / 2,
                    width=W, height=H)
                if base.duration < duration:
                    base = base.fx(vfx.loop, duration=duration)
                else:
                    # random window, not always the first seconds: a long
                    # own clip yields a fresh cut every time it is used
                    start = random.uniform(0, max(base.duration - duration - 0.5, 0))
                    base = base.subclip(start, start + duration)
        except Exception as e:
            logger.warning(f"Stock footage unavailable, falling back: {e}")
            base = None

        # Word-level timings (written by VoiceGenerator) enable pro-style
        # pop-in captions synced to the voice — the professional-Shorts look.
        words = None
        try:
            words_path = audio_path + '.words.json'
            if os.path.exists(words_path):
                words = json.load(open(words_path, encoding='utf-8')) or None
        except Exception as e:
            logger.warning(f"Word timings unreadable, sentence overlays: {e}")

        if base is not None:
            overlays = []
            if words:
                brand_rgb, brand_a = make_brand_layer()
                overlays.append(
                    ImageClip(brand_rgb)
                    .set_mask(ImageClip(brand_a, ismask=True))
                    .set_position((0, BRAND_Y))
                    .set_start(0).set_duration(duration))
                narration = script.get('narration') or " ".join(sentences)
                groups = build_caption_groups(narration, words)
                # ONE dynamic caption track instead of one ImageClip per
                # pop-in: a 120 s tutorial has ~80 groups, and 80 pre-rendered
                # bands (uint8 rgb + float32 mask each) plus the composite
                # bookkeeping pushed the 1 GB container over the edge mid-
                # export (restart at 12:36, first series episode lost). The
                # track renders the active band on demand and keeps two.
                track = CaptionTrack(groups, duration)
                if track.spans:
                    overlays.append(
                        VideoClip(track.frame, duration=duration)
                        .set_mask(VideoClip(track.mask, ismask=True,
                                            duration=duration))
                        .set_position((0, CAPTION_Y)))
                logger.info(f"💬 Word-synced captions: {len(track.spans)} pop-ins")
                # subscribe pill in the last third, gone before the end card
                # moment — long enough to read, short enough not to annoy
                sub_len = min(3.5, max(duration - sub_start, 0.5))
                sub_rgb, sub_a = make_subscribe_layer()
                overlays.append(
                    ImageClip(sub_rgb)
                    .set_mask(ImageClip(sub_a, ismask=True))
                    .set_position((0, SUB_Y))
                    .set_start(sub_start).set_duration(sub_len))
            else:
                for i, sentence in enumerate(sentences):
                    start = i * seg_dur
                    end = min((i + 1) * seg_dur, duration)
                    rgb, alpha = make_overlay(sentence)
                    overlays.append(
                        ImageClip(rgb.astype('uint8'))
                        .set_mask(ImageClip(alpha[:, :, 0], ismask=True))
                        .set_start(start).set_duration(end - start))
            final = CompositeVideoClip([base] + overlays).set_audio(
                audio.subclip(0, duration))
        else:
            raise RuntimeError("no background footage available "
                               "(gameplay library empty and trailers missing)")

        logger.info(f"Exporting {duration:.1f}s video ({len(sentences)} sentences)...")
        # crf 22 / superfast: YouTube re-encodes whatever it gets — a blocky
        # crf-26 source stays blocky. Frame generation dominates render time,
        # the encoder settings add well under a minute per video.
        final.write_videofile(
            output_path, fps=24, codec='libx264',
            audio_codec='aac', threads=2, preset='superfast',
            ffmpeg_params=['-crf', '22', '-pix_fmt', 'yuv420p'], logger=None
        )

        try:
            audio.close(); final.close()
        except Exception:
            pass

        # Production pass: music bed under the voice (credit goes into the
        # description via script['music_credit'])
        output_path, credit = add_music_bed(output_path, duration)
        if credit:
            script['music_credit'] = credit
        # Sound design on top of the mix: whoosh per cut, impact under the
        # hook, pop with the subscribe pill, cash register on money talk
        try:
            from sfx import plan_events, mix_sfx, finalize_loudness
            output_path = mix_sfx(output_path, plan_events(
                duration, cuts_n, words, sub_start))
            output_path = finalize_loudness(output_path)
        except Exception as e:
            logger.warning(f"Sound design skipped: {e}")

        # Production step 6: 0.7s intro sting + subscribe outro card
        try:
            from branding import add_branding
            output_path = add_branding(output_path)
        except Exception as e:
            logger.warning(f"Branding skipped: {e}")

        logger.info(f"Video assembled: {output_path}")
        return output_path

# -*- coding: utf-8 -*-
import os
import json
import logging
import random
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (VideoClip, AudioFileClip, ImageClip,
                            VideoFileClip, CompositeVideoClip,
                            concatenate_videoclips, vfx)
from image_generator import get_background_image

logger = logging.getLogger(__name__)

W, H = 1080, 1920
ZOOM = 0.10  # Ken-Burns zoom range per sentence (10%)


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


def make_caption_layer(text: str):
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
        d.text((x, y), ln, font=font, fill=(255, 255, 255, 255),
               stroke_width=stroke, stroke_fill=(0, 0, 0, 255))

    arr = np.asarray(layer, dtype=np.uint8)
    return arr[:, :, :3].copy(), arr[:, :, 3].astype(np.float32) / 255.0


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
                       'end': tts_words[te]['end']})
        idx += len(c)
    return groups


def make_kb_clip(bg_big: np.ndarray, text: str, duration: float,
                 zoom_in: bool) -> VideoClip:
    """Ken-Burns segment: background slowly zooms while the text overlay
    stays static — motion holds attention better than a still frame."""
    H2, W2 = bg_big.shape[:2]
    rgb, alpha = make_overlay(text)
    inv_alpha = 1.0 - alpha
    overlay_pre = rgb * alpha

    def frame(t):
        p = min(t / duration, 1.0) if duration > 0 else 0.0
        s = 1.0 + ZOOM * p if zoom_in else 1.0 + ZOOM * (1.0 - p)
        cw, ch = int(W2 / s), int(H2 / s)
        x0, y0 = (W2 - cw) // 2, (H2 - ch) // 2
        crop = Image.fromarray(bg_big[y0:y0 + ch, x0:x0 + cw])
        base = np.asarray(crop.resize((W, H), Image.BILINEAR),
                          dtype=np.float32)
        return (base * inv_alpha + overlay_pre).astype('uint8')

    return VideoClip(frame, duration=duration)


GAMEPLAY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "gameplay")
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

    haystack = " ".join([
        script.get("title", ""), script.get("pexels_query", ""),
        " ".join(script.get("tags", [])),
        " ".join(script.get("sentences", []))]).lower()

    scored = [(sum(1 for t in e.get("tags", []) if str(t).lower() in haystack),
               e['path']) for e in entries]
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


def fetch_pexels_video(query: str) -> str:
    """Free stock video background from Pexels (needs PEXELS_API_KEY).
    Returns a local mp4 path or None."""
    key = os.environ.get('PEXELS_API_KEY', '')
    if not key:
        return None
    r = requests.get(
        'https://api.pexels.com/videos/search',
        params={'query': query, 'orientation': 'portrait', 'per_page': 15},
        headers={'Authorization': key}, timeout=20)
    r.raise_for_status()
    videos = r.json().get('videos', [])
    # Pexels returns relevance-sorted results: keep the top hits so the
    # footage actually shows the subject, shuffle only among those for variety
    videos = videos[:6]
    random.shuffle(videos)
    for v in videos:
        files = sorted(v.get('video_files', []),
                       key=lambda f: abs((f.get('height') or 0) - H))
        for f in files:
            if (f.get('height') or 0) >= 1080 and f.get('link'):
                path = '/tmp/bg_video.mp4'
                data = requests.get(f['link'], timeout=90).content
                with open(path, 'wb') as fh:
                    fh.write(data)
                logger.info(f"🎥 Pexels footage: '{query}' "
                            f"({f.get('width')}x{f.get('height')})")
                return path
    return None


class VideoAssembler:
    def __init__(self):
        self.output_dir = "/tmp/videos"
        os.makedirs(self.output_dir, exist_ok=True)

    def assemble(self, script: dict, audio_path: str) -> str:
        output_path = f"{self.output_dir}/video_en_{random.randint(1000,9999)}.mp4"

        audio = AudioFileClip(audio_path)
        duration = min(audio.duration, 58)

        image_prompt = script.get('image_prompt', 'neon-lit night city skyline with a luxury sports car, dramatic cinematic lighting, high contrast, ultra detailed, 8k')
        sentences = script.get('sentences', [script.get('narration', '')])
        if not sentences:
            sentences = [script.get('narration', '')]

        seg_dur = duration / len(sentences)

        # Background priority: 1) own gameplay clip tagged for the topic,
        # 2) official GTA VI trailer montage (GTA 6 topics), 3) any own
        # gameplay clip, 4) topic-matched Pexels stock, 5) AI image + Ken Burns
        base = None
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
            bg_path = pick_gameplay_clip(script, require_match=gta6)
            if not bg_path and gta6 and build_trailer_montage:
                try:
                    bg_path = build_trailer_montage(duration, n_segments=len(sentences) or 3)
                except Exception as e:
                    logger.warning(f"Trailer footage unavailable: {e}")
            if not bg_path and gta6:
                bg_path = pick_gameplay_clip(script)  # own footage still beats stock
            if not bg_path:
                # Topic-matched footage: the script's subject query first,
                # then its broader alternatives, then a neutral fallback
                queries = [script.get('pexels_query')]
                alts = script.get('pexels_alternatives') or []
                if isinstance(alts, list):
                    queries.extend(alts[:3])
                queries.append("night city street driving neon")
                for q in [q for q in queries if q and str(q).strip()]:
                    bg_path = fetch_pexels_video(str(q).strip())
                    if bg_path:
                        break
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
                for i, g in enumerate(groups):
                    start = min(g['start'], duration)
                    if i + 1 < len(groups):
                        end = min(groups[i + 1]['start'], duration)
                    else:
                        end = min(g['end'] + 0.8, duration)
                    if end <= start:
                        continue
                    rgb, alpha = make_caption_layer(g['text'])
                    overlays.append(
                        ImageClip(rgb)
                        .set_mask(ImageClip(alpha, ismask=True))
                        .set_position((0, CAPTION_Y))
                        .set_start(start).set_duration(end - start))
                logger.info(f"💬 Word-synced captions: {len(groups)} pop-ins")
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
            # Fallback: AI image with Ken-Burns motion
            logger.info("Fetching background image...")
            bg = get_background_image(image_prompt)
            big_w, big_h = int(W * (1 + ZOOM)), int(H * (1 + ZOOM))
            bg_big = np.asarray(bg.resize((big_w, big_h), Image.LANCZOS))

            clips = []
            for i, sentence in enumerate(sentences):
                start = i * seg_dur
                end = min((i + 1) * seg_dur, duration)
                c = make_kb_clip(bg_big, sentence, end - start,
                                 zoom_in=(i % 2 == 0)).set_audio(
                    audio.subclip(start, end))
                clips.append(c)
            final = concatenate_videoclips(clips).set_audio(
                audio.subclip(0, duration))

        logger.info(f"Exporting {duration:.1f}s video ({len(sentences)} sentences)...")
        final.write_videofile(
            output_path, fps=24, codec='libx264',
            audio_codec='aac', threads=1, preset='ultrafast',
            ffmpeg_params=['-crf', '26'], logger=None
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

        logger.info(f"Video assembled: {output_path}")
        return output_path

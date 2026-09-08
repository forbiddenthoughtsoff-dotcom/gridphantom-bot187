# -*- coding: utf-8 -*-
"""Long-form 16:9 videos (8-12 min) for watch time — the second road to
monetisation (4 000 public watch hours) that Shorts barely feed.

Two kinds:
  weekly    – "GTA 6 & GTA Online: die Woche kompakt", Sunday night, built
              from the last 7 days of news
  evergreen – guides from series/longform.json (progress via a
              "Langform-ID" marker in the description), Thursday night

Pipeline: sectioned script (Claude) → chunked TTS with merged word
timings → 1920x1080 montage from freshly downloaded PS5 captures
(highlight windows) and official trailer segments for GTA 6 sections →
ASS captions + chapter cards + brand burned in by ffmpeg (no moviepy, low
memory) → music bed + sound design → thumbnail → upload as a regular video
with chapters. Runs at night; the following 07:00 Short is skipped to
stay inside the YouTube quota."""
import os
import re
import json
import time
import random
import logging
import datetime
import subprocess

from motion import motion_vf, GRADE

logger = logging.getLogger(__name__)

WORK_DIR = '/tmp/longform'
DONE_FLAG = '/tmp/longform_done'
LF_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'series', 'longform.json')
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
W, H = 1920, 1080
SEG_LEN = 8.0
SECTION_GAP = 0.6
MARKER_RE = re.compile(r'Langform-ID:\s*(LF-\d+)', re.I)
TARGET_WORDS = {'weekly': (1500, 1800), 'evergreen': (1800, 2100)}
GTA6_KEYS = ('gta 6', 'gta6', 'gta vi', 'vice city', 'leonida', 'lucia', 'jason', 'trailer')

LONGFORM_SYSTEM = """You write long-form YouTube video scripts for the German GTA channel GridPhantom
(GTA 5, GTA Online, GTA 6). Audience: German-speaking GTA players. Standard High German, NEVER the
character ß (always ss). Digits for numbers, years, prices. Spoken language, short sentences, no
lists read aloud, no headings spoken. Confident, warm, knowledgeable ("Sharing is caring"), never
arrogant, no clickbait claims that the video does not deliver.

Facts: only what is confirmed or clearly labelled as rumour/leak. Never invent dates, prices, payouts
or features. When something is unknown, say so — that is content too.

Structure: 8 to 10 sections. Section 1 is the cold open: a concrete promise of what the viewer gets
in the next minutes (max 3 sentences), then straight into content. Every following section has a
short spoken heading (3-6 words, this becomes the YouTube chapter name) and 6-12 sentences that
each add a new fact, step or insight. The last section wraps up in 3-4 sentences, names ONE thing
the viewer should do now, points to the daily Shorts and the career series, and asks to subscribe
with a benefit ("damit du die naechste Folge nicht verpasst").

Output ONLY JSON:
{"title": "max 70 chars, German, curiosity + clarity, no #Shorts",
 "thumb_text": "2-4 punchy words for the thumbnail, uppercase",
 "description": "3-5 German sentences for the description box",
 "sections": [{"heading": "Intro", "sentences": ["...", "..."]}, ...],
 "tags": ["10-15 German + GTA search phrases"],
 "gta6": true_or_false_is_gta6_the_main_subject}
"""


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _probe(path: str) -> float:
    r = subprocess.run([_ffmpeg(), '-i', path], capture_output=True, text=True)
    m = re.search(r'Duration: (\d+):(\d+):(\d+\.?\d*)', r.stderr)
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


# ---------------------------------------------------------------- topics --
def load_topics() -> list:
    try:
        with open(LF_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Long-form topic list unreadable: {e}")
        return []


def used_markers(descriptions) -> set:
    out = set()
    for d in descriptions or []:
        out.update(m.upper() for m in MARKER_RE.findall(str(d or '')))
    return out


def next_evergreen(descriptions) -> dict:
    used = used_markers(descriptions)
    for t in load_topics():
        if t.get('id', '').upper() not in used:
            return t
    return None


def weekly_topic(news_items: list) -> dict:
    now = datetime.datetime.now()
    kw = now.isocalendar()[1]
    lines = "\n".join(f"- {n.get('title', '')} ({n.get('source', '')}, {str(n.get('published', ''))[:10]})"
                      for n in (news_items or [])[:25])
    return {
        'id': f'LF-W{now:%Y%m%d}',
        'kind': 'weekly',
        'brief': (f"WOCHENRUECKBLICK, Kalenderwoche {kw}: 'GTA 6 und GTA Online: die Woche kompakt'. "
                  f"Fasse die wichtigsten GTA-Meldungen der letzten 7 Tage zusammen, ordne sie ein "
                  f"(was ist bestaetigt, was Geruecht, was bedeutet es fuer Spieler), gruppiert nach "
                  f"Themen als Kapitel: GTA 6 News, GTA Online Wochenupdate (Boni, Events, neue Inhalte), "
                  f"Community und Leaks, Ausblick auf naechste Woche. Nur Meldungen aus dieser Liste "
                  f"oder allgemein bekannte Fakten verwenden:\n{lines}\n"
                  f"Der Titel soll 'die Woche kompakt' und die Kalenderwoche {kw} enthalten."),
        'gta6': True,
    }


# ---------------------------------------------------------------- script --
def generate_script(topic: dict, recent_titles: list = None) -> dict:
    import anthropic
    from config import Config
    lo, hi = TARGET_WORDS.get(topic.get('kind', 'evergreen'), (1400, 1700))
    prompt = (f"AUFTRAG:\n{topic['brief']}\n\nZiel-Laenge: {lo} bis {hi} Woerter gesprochener Text "
              f"insgesamt (das ergibt etwa {lo // 140} bis {hi // 140} Minuten). "
              f"Kuerzlich veroeffentlichte Titel (nicht wiederholen): "
              + "; ".join((recent_titles or [])[:15]))
    client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
    for attempt in range(2):
        msg = client.messages.create(model='claude-sonnet-4-6', max_tokens=9000,
                                     system=LONGFORM_SYSTEM,
                                     messages=[{'role': 'user', 'content': prompt}])
        txt = msg.content[0].text
        m = re.search(r'\{.*\}', txt, re.S)
        try:
            data = json.loads(m.group(0)) if m else {}
        except Exception:
            data = {}
        secs = [s for s in data.get('sections', []) if s.get('sentences')]
        words = sum(len(" ".join(s['sentences']).split()) for s in secs)
        if len(secs) >= 4 and words >= lo * 0.75:
            break
        prompt += f"\n\nVORHERIGER VERSUCH ZU KURZ ({words} Woerter). Halte die Ziel-Laenge ein."
    if len(secs) < 4:
        raise RuntimeError("long-form script too short / unparsable")
    for s in secs:
        s['heading'] = str(s.get('heading') or 'Kapitel').replace('ß', 'ss').strip()[:40]
        s['sentences'] = [str(x).replace('ß', 'ss').strip() for x in s['sentences'] if str(x).strip()]
    data['sections'] = secs
    data['title'] = str(data.get('title') or topic.get('title', 'GTA Video')).replace('ß', 'ss').strip()[:95]
    data['description'] = str(data.get('description') or '').replace('ß', 'ss').strip()
    data['thumb_text'] = str(data.get('thumb_text') or data['title'][:20]).replace('ß', 'SS').upper()[:28]
    data['tags'] = [str(t).replace('ß', 'ss') for t in data.get('tags', []) if str(t).strip()][:15]
    data['gta6'] = bool(data.get('gta6', topic.get('gta6', False)))
    data['words'] = words
    return data


# ----------------------------------------------------------------- voice --
def voice_sections(sections: list, work: str) -> tuple:
    """TTS per section, stitched with a short pause. Returns
    (narration_m4a, total_seconds, words_with_absolute_times, section_starts)."""
    from voice_generator import VoiceGenerator
    vg = VoiceGenerator()
    parts, words, starts = [], [], []
    t = 0.0
    for i, s in enumerate(sections):
        text = " ".join(s['sentences'])
        mp3 = os.path.join(work, f'sec_{i}.mp3')
        vg.generate(text, 'de', output_path=mp3)
        dur = _probe(mp3)
        starts.append(t)
        try:
            with open(mp3 + '.words.json', encoding='utf-8') as f:
                for w in json.load(f):
                    words.append({'text': w['text'], 'start': w['start'] + t, 'end': w['end'] + t})
        except Exception:
            pass
        parts.append((mp3, dur))
        t += dur + SECTION_GAP
    total = t - SECTION_GAP
    out = os.path.join(work, 'narration.m4a')
    cmd = [_ffmpeg(), '-y']
    filt = []
    for i, (p, d) in enumerate(parts):
        cmd += ['-i', p]
        pad = SECTION_GAP if i < len(parts) - 1 else 0.0
        filt.append(f"[{i}:a]aresample=44100,apad=pad_dur={pad:.2f}[a{i}]")
    filt.append("".join(f"[a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[a]")
    cmd += ['-filter_complex', ';'.join(filt), '-map', '[a]', '-c:a', 'aac', '-b:a', '192k', out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"narration concat failed: {r.stderr[-300:]}")
    return out, _probe(out) or total, words, starts


# --------------------------------------------------------------- visuals --
def _cut_segment(src: str, start: float, length: float, idx: int, out: str,
                 crop_subs: bool, timeout: int = 420) -> bool:
    pre = ('crop=iw:ih*0.9:0:0,' + GRADE + ',') if crop_subs else ''
    cmd = [_ffmpeg(), '-y', '-ss', f'{start:.2f}', '-i', src, '-t', f'{length:.2f}', '-an',
           '-threads', '2', '-vf', pre + motion_vf(idx, length, W, H) + ',fps=24',
           '-c:v', 'libx264', '-preset', 'superfast', '-crf', '22', '-pix_fmt', 'yuv420p', out]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 20_000


def _gameplay_windows(work: str, n_needed: int, time_budget: float = 1500.0) -> list:
    """Download random PS5 captures just in time and return
    [(raw_path, start)] highlight windows, best first per clip."""
    out = []
    try:
        import psn_captures as psn
        from gameplay_sync import analyze_highlights
        if not psn.enabled():
            return out
        items, sign = psn.list_captures(limit=500)
        vids = [i for i in items if psn.is_gta_video(i, min_seconds=20)]
        random.shuffle(vids)
        t0 = time.time()
        for k, it in enumerate(vids):
            if len(out) >= n_needed or time.time() - t0 > time_budget:
                break
            raw = os.path.join(work, f'raw_{k}.mp4')
            if not psn.download(it, sign, raw):
                continue
            dur = _probe(raw)
            hls = analyze_highlights(raw, dur, window=SEG_LEN, max_windows=6)
            for h in hls:
                if h['start'] + SEG_LEN <= dur + 0.5:
                    out.append((raw, float(h['start'])))
        logger.info(f"🎮 Long-form: {len(out)} gameplay windows from {k + 1 if vids else 0} captures")
    except Exception as e:
        logger.warning(f"Long-form gameplay source failed: {e}")
    return out


def _trailer_windows(n_needed: int) -> list:
    try:
        from trailer_library import available_trailers, _path
        trs = available_trailers()
        if not trs:
            return []
        t = trs[0]  # 1080p only — 4K decoding is too slow on the box
        src = _path(t)
        total = _probe(src)
        lo, hi = t['skip_head'], total - t['skip_tail'] - SEG_LEN
        starts = list(range(int(lo), int(hi), int(SEG_LEN)))
        random.shuffle(starts)
        return [(src, float(s)) for s in starts[:n_needed]]
    except Exception as e:
        logger.warning(f"Long-form trailer source failed: {e}")
        return []


def build_montage(sections: list, starts: list, total: float, gta6_main: bool, work: str) -> str:
    """One 1920x1080 silent montage covering `total` seconds: GTA 6 sections
    alternate trailer and gameplay windows, other sections use gameplay."""
    n_total = int(total / SEG_LEN) + 2
    sec_flags = []
    for s in sections:
        blob = (s['heading'] + " " + " ".join(s['sentences'])).lower()
        sec_flags.append(gta6_main or sum(blob.count(k) for k in GTA6_KEYS) >= 2)
    n_gta6 = sum(1 for f in sec_flags if f)
    trailer = _trailer_windows(min(24, n_total)) if n_gta6 else []
    gameplay = _gameplay_windows(work, n_total)
    if not gameplay and not trailer:
        raise RuntimeError("no footage for long-form montage")
    random.shuffle(gameplay)
    gi = ti = 0
    parts = []
    idx = 0
    t = 0.0
    sec_i = 0
    while t < total:
        while sec_i + 1 < len(starts) and t >= starts[sec_i + 1]:
            sec_i += 1
        use_trailer = sec_flags[sec_i] and trailer and (idx % 2 == 0 or not gameplay)
        if use_trailer:
            src, st = trailer[ti % len(trailer)]
            ti += 1
            crop = False
        else:
            if not gameplay:
                src, st = trailer[ti % len(trailer)]
                ti += 1
                crop = False
            else:
                src, st = gameplay[gi % len(gameplay)]
                gi += 1
                crop = True
        length = min(SEG_LEN, total - t + 0.5)
        out = os.path.join(work, f'seg_{idx:03d}.mp4')
        if _cut_segment(src, st, length, idx, out, crop):
            parts.append(out)
            t += length
        idx += 1
        if idx > n_total * 2:
            break
    lst = os.path.join(work, 'concat.txt')
    with open(lst, 'w') as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    montage = os.path.join(work, 'montage.mp4')
    r = subprocess.run([_ffmpeg(), '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', montage],
                       capture_output=True, text=True, timeout=600)
    for p in parts:
        try:
            os.remove(p)
        except OSError:
            pass
    for f in os.listdir(work):
        if f.startswith('raw_'):
            try:
                os.remove(os.path.join(work, f))
            except OSError:
                pass
    if r.returncode != 0:
        raise RuntimeError(f"montage concat failed: {r.stderr[-300:]}")
    logger.info(f"🎬 Long-form montage: {len(parts)} segments, {gi} gameplay / {ti} trailer")
    return montage


# -------------------------------------------------------------- captions --
def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_escape(s: str) -> str:
    return s.replace('{', '(').replace('}', ')').replace('\n', ' ')


def write_ass(path: str, groups: list, sections: list, starts: list, total: float):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,80,80,72,1
Style: Chapter,DejaVu Sans,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,14,0,7,90,90,110,1
Style: Brand,DejaVu Sans,34,&H00E6E6E6,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,9,60,60,44,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [head]
    lines.append(f"Dialogue: 0,{_ts(0)},{_ts(total)},Brand,,0,0,0,,@GridPhantom187\n")
    for i, s in enumerate(sections):
        if i == 0:
            continue
        st = starts[i]
        lines.append(f"Dialogue: 1,{_ts(st)},{_ts(st + 3.2)},Chapter,,0,0,0,,"
                     f"{{\\fad(250,300)}}{_ass_escape(s['heading'])}\n")
    for i, g in enumerate(groups):
        st = g['start']
        en = groups[i + 1]['start'] if i + 1 < len(groups) else g['end'] + 0.6
        en = min(en, total)
        if en - st < 0.15:
            continue
        lines.append(f"Dialogue: 0,{_ts(st)},{_ts(en)},Cap,,0,0,0,,{_ass_escape(g['text'])}\n")
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    return path


def render(montage: str, narration: str, ass_path: str, total: float, out: str,
           timeout: int = 5400) -> str:
    ass_arg = ass_path.replace('\\', '/').replace(':', '\\:')
    fonts = FONTS_DIR.replace(':', '\\:')
    cmd = [_ffmpeg(), '-y', '-i', montage, '-i', narration, '-threads', '2',
           '-vf', f"ass=filename={ass_arg}:fontsdir={fonts}",
           '-t', f'{total:.2f}', '-c:v', 'libx264', '-preset', 'superfast', '-crf', '23',
           '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"long-form render failed: {r.stderr[-400:]}")
    return out


# ------------------------------------------------------------- thumbnail --
def make_thumbnail(video: str, text: str, out: str, at: float) -> str:
    from PIL import Image, ImageDraw, ImageFilter
    from video_assembler import load_font
    jpg = out + '.frame.jpg'
    subprocess.run([_ffmpeg(), '-y', '-loglevel', 'error', '-ss', f'{at:.2f}', '-i', video,
                    '-frames:v', '1', '-vf', 'scale=1280:720', '-q:v', '3', jpg],
                   capture_output=True, timeout=120)
    im = Image.open(jpg).convert('RGB')
    # dark gradient at the bottom for legibility
    grad = Image.new('L', (1, 720))
    for y in range(720):
        grad.putpixel((0, y), int(max(0, (y - 300) / 420) * 190))
    dark = Image.new('RGB', im.size, (0, 0, 0))
    im = Image.composite(dark, im, grad.resize(im.size))
    d = ImageDraw.Draw(im)
    words = text.split()
    line1 = " ".join(words[:2]) if len(words) > 2 else text
    line2 = " ".join(words[2:]) if len(words) > 2 else ''
    y = 430 if line2 else 520
    for ln, col in ((line1, (255, 214, 0)), (line2, (255, 255, 255))):
        if not ln:
            continue
        size = 118
        font = load_font(size)
        while d.textbbox((0, 0), ln, font=font, stroke_width=8)[2] > 1180 and size > 60:
            size -= 8
            font = load_font(size)
        d.text((60, y), ln, font=font, fill=col, stroke_width=8, stroke_fill=(0, 0, 0))
        y += int(size * 1.15)
    fb = load_font(34)
    d.text((60, 40), "@GridPhantom187", font=fb, fill=(235, 235, 235), stroke_width=3, stroke_fill=(0, 0, 0))
    im.save(out, quality=90)
    try:
        os.remove(jpg)
    except OSError:
        pass
    return out


# ----------------------------------------------------------------- build --
def build(topic: dict, recent_titles: list = None, script: dict = None) -> tuple:
    """Everything up to the finished mp4. Returns (video_path, script)."""
    os.makedirs(WORK_DIR, exist_ok=True)
    for f in os.listdir(WORK_DIR):
        try:
            os.remove(os.path.join(WORK_DIR, f))
        except OSError:
            pass
    script = script or generate_script(topic, recent_titles)
    logger.info(f"📝 Long-form script: {script['title']} ({len(script['sections'])} sections, "
                f"{script.get('words', '?')} words)")
    narration, total, words, starts = voice_sections(script['sections'], WORK_DIR)
    logger.info(f"🎙️ Long-form narration: {total / 60:.1f} min, {len(words)} timed words")
    import voice_generator as _vg
    if _vg.LAST_ENGINE == 'elevenlabs':
        script['voice_credit'] = 'ElevenLabs (elevenlabs.io)'
    montage = build_montage(script['sections'], starts, total, script.get('gta6', False), WORK_DIR)
    from video_assembler import build_caption_groups
    narration_text = " ".join(" ".join(s['sentences']) for s in script['sections'])
    groups = build_caption_groups(narration_text, words, max_words=5, max_chars=34) if words else []
    if not groups:  # no word timings (fallback voice): one caption per sentence, evenly spread
        sents = [x for s in script['sections'] for x in s['sentences']]
        per = total / max(len(sents), 1)
        groups = [{'text': x, 'start': i * per, 'end': (i + 1) * per} for i, x in enumerate(sents)]
    ass_path = write_ass(os.path.join(WORK_DIR, 'captions.ass'), groups, script['sections'], starts, total)
    out = os.path.join('/tmp/videos', f"longform_{int(time.time())}.mp4")
    os.makedirs('/tmp/videos', exist_ok=True)
    t0 = time.time()
    render(montage, narration, ass_path, total, out)
    logger.info(f"🎥 Long-form render done in {(time.time() - t0) / 60:.1f} min: {out}")
    try:
        import video_assembler as va
        prev = va.MUSIC_VOLUME
        va.MUSIC_VOLUME = 0.12
        try:
            out, credit = va.add_music_bed(out, total)
        finally:
            va.MUSIC_VOLUME = prev
        if credit:
            script['music_credit'] = credit
    except Exception as e:
        logger.warning(f"Long-form music skipped: {e}")
    try:
        from sfx import mix_sfx, library
        lib = library()
        ev = [(0.0, 'impact_1', 0.45)] + [(st - 0.1, f'whoosh_{(i % 4) + 1}', 0.4)
                                          for i, st in enumerate(starts) if st > 1]
        mix_sfx(out, [e for e in ev if e[1] in lib])
        from sfx import finalize_loudness
        finalize_loudness(out)
    except Exception as e:
        logger.warning(f"Long-form sound design skipped: {e}")
    thumb = os.path.join(WORK_DIR, 'thumb.jpg')
    try:  # frame from the clean montage (no captions/brand burned in)
        make_thumbnail(montage, script.get('thumb_text', ''), thumb, at=max(3.0, total * 0.25))
        script['thumbnail'] = thumb
    except Exception as e:
        logger.warning(f"Thumbnail skipped: {e}")
    script['chapters'] = [(starts[i], s['heading'] if i else 'Intro')
                          for i, s in enumerate(script['sections'])]
    script['description'] = (script.get('description', '') +
                             f"\n\n🎬 Langform-ID: {topic.get('id', 'LF-00')}")
    script['narration'] = narration_text
    script['sentences'] = [x for s in script['sections'] for x in s['sentences']]
    script['duration'] = total
    return out, script


def run_longform(kind: str = 'evergreen', language: str = 'de'):
    """Slot entry: topic → build → upload. Returns the video id or None."""
    from youtube_uploader import YouTubeUploader
    uploader = YouTubeUploader()
    recent = uploader.get_recent_performance(50)
    titles = [r['title'] for r in recent]
    if kind == 'weekly':
        try:
            from news_fetcher import fetch_recent_news
            news = fetch_recent_news(max_age_days=8, limit=40)
        except Exception as e:
            logger.warning(f"News unavailable for the weekly recap: {e}")
            news = []
        topic = weekly_topic(news)
    else:
        topic = next_evergreen([r.get('description') for r in recent])
        if not topic:
            logger.info("📺 Long-form: every evergreen topic is published")
            return None
        topic = dict(topic, kind='evergreen')
    logger.info(f"📺 Long-form ({kind}): {topic.get('id')}")
    video, script = build(topic, titles)
    # release at prime time (default 18:00 local), never in the night
    publish_at = None
    try:
        hour = int(os.environ.get('LONGFORM_PUBLISH_HOUR', '18'))
        now = datetime.datetime.now()
        publish_at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if publish_at <= now + datetime.timedelta(minutes=20):
            publish_at += datetime.timedelta(days=1)
        publish_at = publish_at.astimezone()
    except Exception as e:
        logger.warning(f"Publish time not set ({e}) — publishing immediately")
    vid = uploader.upload(video, script, language, kind='long', publish_at=publish_at)
    if vid:
        logger.info(f"✅ UPLOADED long-form [{language}]: https://youtube.com/watch?v={vid} "
                    f"({script['duration'] / 60:.1f} min)")
        if script.get('thumbnail'):
            uploader.set_thumbnail(vid, script['thumbnail'])
        try:
            with open(DONE_FLAG, 'w') as f:
                f.write(str(int(time.time())))
        except OSError:
            pass
        if publish_at is None:  # comments on a private (scheduled) video fail
            try:
                from community_manager import CommunityManager
                CommunityManager(uploader.service).seed_comment(vid, script)
            except Exception as e:
                logger.warning(f"Seed comment skipped: {e}")
    try:
        os.remove(video)
    except OSError:
        pass
    return vid


def recently_done(hours: float = 6.0) -> bool:
    try:
        with open(DONE_FLAG) as f:
            return time.time() - int(f.read().strip()) < hours * 3600
    except Exception:
        return False

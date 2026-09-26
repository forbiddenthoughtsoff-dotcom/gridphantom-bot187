# -*- coding: utf-8 -*-
"""Scene-matched footage from the official GTA 6 videos.

Owner's brief (09-26): cut the allowed GTA 6 footage like small films —
the pictures must fit what the narration is talking about at that moment,
and no scene may keep coming back video after video.

How it works
 1. Every official source video (trailers, the 26-minute Extended Look) is
    split into shots with ffmpeg scene detection.
 2. One frame per shot is described by the model with a fixed German tag
    vocabulary (VOCAB) — the same vocabulary the script writer uses for the
    "visuals" it wants under each sentence, so matching is exact.
 3. At render time every sentence gets the best-matching shots that were
    not used in the last USED_MEMORY videos; the cut lands on the sentence
    boundaries, the picture keeps Rockstar's full 16:9 frame (sharp, no
    blurry 9:16 crop of a 720p source) over a soft blurred fill.

The index lives next to the footage (/tmp/trailers/shots.json) and is
rebuilt in the background after a fresh deploy; renders fall back to the
plain trailer window until it exists."""
import os
import re
import json
import time
import base64
import random
import logging
import threading
import subprocess

logger = logging.getLogger(__name__)

W, H = 1080, 1920
FG_Y = 420                 # top edge of the 16:9 picture (1080x608)
MIN_SHOT, MAX_SHOT = 1.6, 6.5
SCENE_THRESH = 0.30
USED_MEMORY = 40           # a shot rests for this many videos
TAG_MODEL = 'claude-haiku-4-5-20251001'

# Fixed vocabulary shared by the indexer and the script writer (German,
# lower case, no ß). Keep it short: exact matches beat clever synonyms.
VOCAB = [
    # people
    'lucia', 'jason', 'paar', 'menschenmenge', 'polizei', 'gangster', 'dialog',
    # places
    'strand', 'stadt', 'nacht', 'tag', 'sonnenuntergang', 'sumpf', 'autobahn',
    'innenraum', 'club', 'gefaengnis', 'tankstelle', 'wohnung', 'hafen',
    'luftaufnahme', 'vorort', 'wueste',
    # action
    'fahren', 'verfolgungsjagd', 'schiessen', 'kampf', 'explosion', 'ueberfall',
    'flucht', 'boot', 'motorrad', 'flugzeug', 'schwimmen', 'party', 'tanzen',
    'laufen', 'verhaftung', 'crash',
    # things
    'auto', 'sportwagen', 'waffe', 'geld', 'handy', 'social-media', 'tiere',
    'wetter', 'regen', 'karte',
    # mood
    'ruhig', 'action', 'dramatisch', 'witzig', 'romantisch',
]
SKIP_TAG = 'titelkarte'    # logos, black frames, text cards — never used


def _dir():
    from trailer_library import TRAILER_DIR
    return TRAILER_DIR


def _index_path():
    return os.path.join(_dir(), 'shots.json')


def _used_path():
    return os.path.join(_dir(), 'used_shots.json')


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


_LOW = {'preexec_fn': lambda: os.nice(19)}


# ----------------------------------------------------------------- shots --
def detect_shots(path: str, skip_head: float = 0.0, skip_tail: float = 0.0) -> list:
    """[(start, end)] shot windows between MIN_SHOT and MAX_SHOT seconds."""
    from trailer_library import _probe_duration
    total = _probe_duration(path)
    if total <= 0:
        return []
    cmd = [_ffmpeg(), '-hide_banner', '-nostats', '-i', path, '-an',
           '-vf', f"select='gt(scene,{SCENE_THRESH})',showinfo", '-f', 'null', '-']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, **_LOW)
    cuts = [float(m) for m in re.findall(r'pts_time:\s*([\d.]+)', r.stderr)]
    lo, hi = skip_head, max(skip_head + MIN_SHOT, total - skip_tail)
    bounds = [lo] + [c for c in cuts if lo < c < hi] + [hi]
    shots = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a < MIN_SHOT:
            # too short: glue onto the previous shot (a flash cut on its own
            # reads as a glitch)
            if shots and b - shots[-1][0] <= MAX_SHOT * 1.5:
                shots[-1] = (shots[-1][0], b)
            continue
        while b - a > MAX_SHOT:
            shots.append((a, a + MAX_SHOT))
            a += MAX_SHOT
        if b - a >= MIN_SHOT:
            shots.append((a, b))
        elif shots:
            shots[-1] = (shots[-1][0], b)
    return [(round(a, 2), round(b, 2)) for a, b in shots]


def _frame(path: str, t: float, out: str) -> bool:
    cmd = [_ffmpeg(), '-y', '-loglevel', 'error', '-ss', f'{t:.2f}', '-i', path,
           '-frames:v', '1', '-vf', 'scale=512:-2', '-q:v', '5', out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, **_LOW)
    return r.returncode == 0 and os.path.exists(out)


def _tag_batch(frames: list) -> list:
    """frames: [(shot_id, jpg_path)] → [{'id', 'tags', 'skip'}] via one
    vision call. Any failure returns [] (the caller keeps the shots untagged
    and retries on the next index run)."""
    import anthropic
    from config import Config
    content = []
    for n, (_, jpg) in enumerate(frames, 1):
        with open(jpg, 'rb') as f:
            data = base64.b64encode(f.read()).decode('ascii')
        content.append({'type': 'text', 'text': f'Bild {n}:'})
        content.append({'type': 'image', 'source': {'type': 'base64',
                                                     'media_type': 'image/jpeg',
                                                     'data': data}})
    content.append({'type': 'text', 'text': (
        "Das sind Einzelbilder aus offiziellem GTA 6 Material (Trailer, Gameplay). "
        "Beschreibe JEDES Bild mit 3 bis 7 Tags AUSSCHLIESSLICH aus dieser Liste "
        "(exakte Schreibweise): " + ", ".join(VOCAB) + ". "
        f"Ist ein Bild ein Logo, eine Titel-/Texttafel, schwarz oder unscharf, gib "
        f"stattdessen genau den einen Tag \"{SKIP_TAG}\". "
        "Lucia = die Frau mit dunklen Haaren (Protagonistin), Jason = der Mann mit "
        "Kappe/Bart (Protagonist). Antworte NUR mit JSON: "
        "[{\"i\": 1, \"tags\": [\"...\"]}, ...] in der Reihenfolge der Bilder.")})
    client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
    msg = client.messages.create(model=TAG_MODEL, max_tokens=1200,
                                 messages=[{'role': 'user', 'content': content}])
    raw = msg.content[0].text
    raw = raw[raw.find('['):raw.rfind(']') + 1]
    parsed = json.loads(raw)
    out = []
    allowed = set(VOCAB) | {SKIP_TAG}
    for item in parsed:
        i = int(item.get('i', 0)) - 1
        if not 0 <= i < len(frames):
            continue
        tags = [str(t).strip().lower() for t in item.get('tags', [])]
        tags = [t for t in tags if t in allowed]
        out.append({'id': frames[i][0], 'tags': tags, 'skip': SKIP_TAG in tags or not tags})
    return out


REPO_INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'footage', 'shots.json')


def load_index() -> list:
    """The live index next to the footage; on a fresh container the copy
    committed to the repo (footage/shots.json) is seeded first, so a
    redeploy costs no re-detection and no re-tagging."""
    if not os.path.exists(_index_path()) and os.path.exists(REPO_INDEX):
        try:
            os.makedirs(_dir(), exist_ok=True)
            with open(REPO_INDEX, 'rb') as src, open(_index_path(), 'wb') as dst:
                dst.write(src.read())
            logger.info("🎞️ Shot index seeded from the repo copy")
        except Exception as e:
            logger.warning(f"Shot index seed failed: {e}")
    try:
        with open(_index_path(), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save_index(index: list):
    tmp = _index_path() + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False)
    os.replace(tmp, _index_path())


def build_index(batch: int = 8) -> int:
    """Index every downloaded official source that is not indexed yet.
    Returns the number of usable (tagged, non-skip) shots."""
    from trailer_library import available_trailers, _path
    index = load_index()
    done_sources = {s['src'] for s in index}
    frames_dir = os.path.join(_dir(), 'frames')
    os.makedirs(frames_dir, exist_ok=True)
    for t in available_trailers():
        name = t['name']
        if name in done_sources:
            continue
        path = _path(t)
        t0 = time.time()
        windows = detect_shots(path, t.get('skip_head', 0.0), t.get('skip_tail', 0.0))
        logger.info(f"🎞️ Shots: {name} → {len(windows)} shots "
                    f"(detection {time.time() - t0:.0f} s)")
        shots = [{'id': f'{name}:{i}', 'src': name, 'start': a, 'end': b,
                  'tags': [], 'skip': False} for i, (a, b) in enumerate(windows)]
        pending = []
        for s in shots:
            jpg = os.path.join(frames_dir, s['id'].replace(':', '_') + '.jpg')
            if _frame(path, (s['start'] + s['end']) / 2.0, jpg):
                pending.append((s['id'], jpg))
        by_id = {s['id']: s for s in shots}
        tagged = 0
        for k in range(0, len(pending), batch):
            chunk = pending[k:k + batch]
            try:
                for res in _tag_batch(chunk):
                    by_id[res['id']]['tags'] = res['tags']
                    by_id[res['id']]['skip'] = res['skip']
                    tagged += 1
            except Exception as e:
                logger.warning(f"Shot tagging batch failed: {e}")
        for _, jpg in pending:
            try:
                os.remove(jpg)
            except OSError:
                pass
        index.extend(shots)
        _save_index(index)
        logger.info(f"🎞️ Shots: {name} indexed — {tagged}/{len(shots)} tagged, "
                    f"{sum(1 for s in shots if s['skip'])} skipped as cards/logos")
    return sum(1 for s in index if s.get('tags') and not s.get('skip'))


_started = False


def ensure_index_async(wait_s: float = 1800.0):
    """After start: wait for the footage downloads, then index in the
    background (nice 19 ffmpeg, a few dozen small vision calls)."""
    global _started
    if _started:
        return
    _started = True

    def worker():
        from trailer_library import TRAILERS, available_trailers
        t0 = time.time()
        while time.time() - t0 < wait_s:
            if len(available_trailers()) >= len(TRAILERS):
                break
            time.sleep(30)
        try:
            n = build_index()
            logger.info(f"🎞️ Shot index ready: {n} usable shots")
        except Exception as e:
            logger.warning(f"Shot index failed: {e}")
    threading.Thread(target=worker, daemon=True, name='shot-index').start()


# --------------------------------------------------------------- matching --
def _load_used() -> list:
    try:
        with open(_used_path(), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def note_used(ids: list):
    used = _load_used()
    used.append(list(ids))
    used = used[-USED_MEMORY:]
    try:
        with open(_used_path(), 'w', encoding='utf-8') as f:
            json.dump(used, f)
    except Exception as e:
        logger.warning(f"Used-shot ledger not written: {e}")


def visuals_from_text(text: str) -> list:
    """Fallback when the script carries no 'visuals': vocabulary words
    that literally occur in the sentence."""
    low = text.lower().replace('ß', 'ss')
    hits = [v for v in VOCAB if v.replace('-', ' ') in low]
    for a, b in (('polizist', 'polizei'), ('cops', 'polizei'), ('fahrzeug', 'auto'),
                 ('wagen', 'auto'), ('pistole', 'waffe'), ('gewehr', 'waffe'),
                 ('dollar', 'geld'), ('raub', 'ueberfall'), ('heist', 'ueberfall'),
                 ('meer', 'strand'), ('vice city', 'stadt'), ('leonida', 'luftaufnahme'),
                 ('freund', 'paar'), ('beziehung', 'paar'), ('alligator', 'tiere'),
                 ('hurrikan', 'wetter'), ('sturm', 'wetter'), ('telefon', 'handy')):
        if a in low and b not in hits:
            hits.append(b)
    return hits


def sentence_spans(sentences: list, words: list, duration: float) -> list:
    """[(start, end)] per sentence: the TTS word timings are mapped onto the
    sentences by word count (the engine's tokens do not match the text
    one to one, so proportional mapping is the robust choice)."""
    if not words:
        per = duration / max(len(sentences), 1)
        return [(i * per, min((i + 1) * per, duration)) for i in range(len(sentences))]
    counts = [max(len(s.split()), 1) for s in sentences]
    total_words = sum(counts)
    spans, pos = [], 0
    for i, c in enumerate(counts):
        a = int(round(pos / total_words * len(words)))
        b = int(round((pos + c) / total_words * len(words)))
        b = max(b, a + 1)
        start = float(words[min(a, len(words) - 1)]['start'])
        end = float(words[min(b, len(words)) - 1]['end']) if b <= len(words) else duration
        if i == 0:
            start = 0.0
        if i == len(counts) - 1:
            end = duration
        spans.append((start, min(end, duration)))
        pos += c
    # cuts sit ON the next sentence start: extend each span to its successor
    out = []
    for i, (a, b) in enumerate(spans):
        nxt = spans[i + 1][0] if i + 1 < len(spans) else duration
        out.append((a, max(nxt, a + 0.5)))
    return out


def plan(script: dict, words: list, duration: float) -> list:
    """[(src_path, start, length, shot_id)] covering `duration`, one or more
    scene-matched shots per sentence, none used in the last USED_MEMORY
    videos, none twice in this video. None when the index is not ready."""
    from trailer_library import TRAILERS, _path
    index = [s for s in load_index() if s.get('tags') and not s.get('skip')]
    if len(index) < 40:
        return None
    src_paths = {t['name']: _path(t) for t in TRAILERS}
    recently = {i for video in _load_used() for i in video}
    pool = [s for s in index if s['id'] not in recently] or index
    sentences = script.get('sentences') or [script.get('narration', '')]
    visuals = script.get('visuals') or []
    spans = sentence_spans(sentences, words, duration)
    plan_out, used_here = [], set()
    last_src = None
    for i, (a, b) in enumerate(spans):
        want = set(visuals[i] if i < len(visuals) and visuals[i] else
                   visuals_from_text(sentences[i]))
        need = b - a
        while need > 0.4:
            cands = [s for s in pool if s['id'] not in used_here]
            if not cands:
                cands = [s for s in index if s['id'] not in used_here] or index
            def score(s):
                sc = len(want & set(s['tags'])) * 10
                sc += min(s['end'] - s['start'], need)      # longer fits better
                if s['src'] != last_src:
                    sc += 1.5                                # vary the source
                return sc + random.random()
            best = max(cands, key=score)
            length = min(best['end'] - best['start'], need)
            if need - length < MIN_SHOT * 0.6:               # avoid a stub at the end
                length = need
            plan_out.append((src_paths.get(best['src']), best['start'], round(length, 2), best['id']))
            used_here.add(best['id'])
            last_src = best['src']
            need -= length
    return plan_out


# --------------------------------------------------------------- render --
def render(plan_items: list, out_dir: str) -> str:
    """Cut and frame every planned shot, concat to one silent 1080x1920 clip.
    Picture: the full 16:9 frame at 1080 px wide (sharp from a 720p source),
    centred high; behind it the same shot blurred and darkened. Static —
    no camera moves, no zoom."""
    ff = _ffmpeg()
    os.makedirs(out_dir, exist_ok=True)
    parts = []
    vf = (f"split=2[a][b];"
          f"[a]scale=108:192:force_original_aspect_ratio=increase,crop=108:192,"
          f"gblur=sigma=2.5,scale={W}:{H},eq=brightness=-0.28:saturation=0.75[bg];"
          f"[b]scale={W}:-2[fg];"
          f"[bg][fg]overlay=0:{FG_Y}:shortest=1,fps=24,format=yuv420p")
    for i, (src, start, length, _) in enumerate(plan_items):
        if not src or not os.path.exists(src):
            continue
        out = os.path.join(out_dir, f'scene_{os.getpid()}_{i:02d}.mp4')
        cmd = [ff, '-y', '-loglevel', 'error', '-ss', f'{start:.2f}', '-i', src,
               '-t', f'{length:.2f}', '-an', '-filter_complex', vf,
               '-c:v', 'libx264', '-preset', 'superfast', '-crf', '20', out]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 10_000:
            parts.append(out)
        else:
            logger.warning(f"Scene segment {i} failed: {r.stderr[-160:]}")
    if not parts:
        return None
    lst = os.path.join(out_dir, f'scenes_{os.getpid()}.txt')
    with open(lst, 'w') as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    montage = os.path.join(out_dir, f'scenes_{os.getpid()}.mp4')
    r = subprocess.run([ff, '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
                        '-i', lst, '-c', 'copy', montage],
                       capture_output=True, text=True, timeout=120)
    for p in parts:
        try:
            os.remove(p)
        except OSError:
            pass
    if r.returncode != 0 or not os.path.exists(montage):
        logger.warning(f"Scene concat failed: {r.stderr[-160:]}")
        return None
    return montage


def build_scene_montage(script: dict, words: list, duration: float) -> str:
    """Entry point for the assembler. Returns the mp4 path or None."""
    items = plan(script, words, duration)
    if not items:
        return None
    out = render(items, os.path.join(_dir(), 'scenes'))
    if out:
        note_used([i[3] for i in items])
        logger.info(f"🎬 Scene cut: {len(items)} shots from "
                    f"{len({i[0] for i in items})} source(s), "
                    f"{sum(i[2] for i in items):.1f}s")
    return out

# -*- coding: utf-8 -*-
"""Raw-highlight Shorts from the owner's own PS5 captures.

The narration videos use the gameplay as wallpaper. This format is the
opposite: ONE moment (crash, explosion, chase, stunt) with the ORIGINAL game
audio, 10-16 seconds, a 3-second text hook, the subscribe pill, brand — and
nothing else. That is the clip format that travels furthest in the GTA
feed, it costs no voice credits, and it renders in one ffmpeg pass.

Repeat protection: every published clip Short carries "Clip-ID: <marker>"
in its description; the picker skips clips whose marker is already on the
channel, so a moment is never posted twice — across restarts and redeploys
(the channel itself is the memory, not /tmp)."""
import os
from config import Config as _C
import re
import json
import base64
import random
import hashlib
import logging
import subprocess

from motion import motion_vf, GRADE

logger = logging.getLogger(__name__)

CLIP_MIN, CLIP_MAX = 10.0, 16.0
HOOK_SECONDS = 3.0
OUT_DIR = '/tmp/videos'
MARKER_RE = re.compile(r'Clip-ID:\s*([a-f0-9]{10})', re.I)
# tags (from the vision auto-tagger) that promise a payoff
ACTION_TAGS = {'explosion', 'feuer', 'crash', 'unfall', 'absturz', 'flucht',
               'verfolgungsjagd', 'polizei', 'schiesserei', 'sprung', 'stunt',
               'fallschirm', 'helikopter', 'flugzeug', 'jet', 'rennen',
               'motorrad', 'panzer', 'rakete', 'kampf', 'wasser', 'boot'}


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def marker(drive_id: str) -> str:
    return hashlib.sha1(str(drive_id).encode('utf-8')).hexdigest()[:10]


def used_markers(descriptions) -> set:
    out = set()
    for d in descriptions or []:
        out.update(m.lower() for m in MARKER_RE.findall(str(d or '')))
    return out


def pick(entries: list, used: set):
    """Best unused highlight: analysis score + a bonus for action tags + a
    little noise so two containers never pick identically."""
    cands = []
    for e in entries:
        if float(e.get('duration', 0)) < CLIP_MIN or not e.get('highlights'):
            continue
        if not e.get('drive_id') or marker(e['drive_id']) in used:
            continue
        bonus = min(0.5, 0.25 * len(ACTION_TAGS & set(e.get('tags') or [])))
        for h in e['highlights']:
            cands.append((float(h.get('score', 0)) + bonus + random.uniform(0, 0.15), e, h))
    if not cands:
        return None, None
    cands.sort(key=lambda c: c[0], reverse=True)
    return cands[0][1], cands[0][2]


def cut(entry: dict, h: dict, out_path: str):
    """Cut the moment out of the proxy: start ~2 s before the highlight so
    the payoff lands inside the window, light push-in, loudness-normalised
    game audio. Returns (path, length) or (None, 0)."""
    dur = float(entry['duration'])
    length = min(CLIP_MAX, dur)
    start = max(0.0, float(h['start']) - 2.0)
    if start + length > dur:
        start = max(0.0, dur - length)
    length = round(min(length, dur - start), 2)
    cmd = [_ffmpeg(), '-y', '-ss', f'{start:.2f}', '-i', entry['path'],
           '-t', f'{length:.2f}', '-threads', '2',
           '-vf', GRADE + ',' + motion_vf(0, length) + ',fps=24',
           '-af', 'loudnorm=I=-15:TP=-1.5:LRA=11',
           '-c:v', 'libx264', '-preset', 'superfast', '-crf', '20',
           '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not os.path.exists(out_path):
        logger.warning(f"Clip cut failed: {r.stderr[-300:]}")
        return None, 0.0
    return out_path, length


def _frames(path: str, length: float) -> list:
    ff = _ffmpeg()
    out = []
    for t in (length * 0.45,):   # one frame is enough to describe the moment
        jpg = f'{path}.f{int(t * 10)}.jpg'
        subprocess.run([ff, '-y', '-loglevel', 'error', '-ss', f'{t:.2f}', '-i', path,
                        '-frames:v', '1', '-vf', 'scale=360:-2', '-q:v', '5', jpg],
                       capture_output=True, timeout=60)
        if os.path.exists(jpg):
            with open(jpg, 'rb') as f:
                out.append(base64.b64encode(f.read()).decode())
            os.remove(jpg)
    return out


FALLBACK = {
    'hook': 'Warte bis zum Ende 👀',
    'title': 'GTA Online: Dieser Moment 😳',
    'description': ('Ein Moment aus meinen eigenen GTA Online Sessions auf der PS5. '
                    'Kein Skript, kein Schnitt-Trick, einfach das, was passiert ist. '
                    'Was haettest du hier gemacht? Schreib es in die Kommentare.'),
    'tags': ['gta online', 'gta 5', 'gta online clips', 'gta online moments',
             'gta 5 deutsch', 'gta online deutsch', 'gaming clips'],
}


def describe(clip_path: str, length: float, tags: list) -> dict:
    """Hook + title + description + tags from what is actually in the clip
    (three frames → Claude). German, no ß, honest: nothing the frames do
    not show. Falls back to a neutral set."""
    key = os.environ.get('ANTHROPIC_API_KEY', '')
    frames = _frames(clip_path, length) if key else []
    if not frames:
        return dict(FALLBACK)
    try:
        import anthropic
        content = [{'type': 'image', 'source': {'type': 'base64',
                    'media_type': 'image/jpeg', 'data': fr}} for fr in frames]
        content.append({'type': 'text', 'text': (
            "A frame from a " + f"{length:.0f}" + "-second GTA Online (GTA 5, PS5) "
            "gameplay clip from the channel owner " + _C.CHANNEL_NAME + ". Keyword tags for the clip: "
            + ", ".join(tags or []) + ".\n"
            "Write the on-screen hook and the metadata for a YouTube Short that shows this clip "
            "raw with its original game audio (no narration). Rules:\n"
            "- hook: max 6 words, German, shown for 3 seconds at the start, creates a reason to "
            "watch to the end (e.g. 'Das Ende hat niemand erwartet', 'Warte auf den Truck'). "
            "Never a question that can be answered with no. One emoji max.\n"
            "- title: max 55 characters, German, must contain 'GTA Online' or 'GTA 5', concrete "
            "to what is visible, curiosity gap, one emoji max, no clickbait about things not shown.\n"
            "- description: 3-4 German sentences: what happens, where in the map/mode if "
            "recognisable, one honest line that this is the owner's own PS5 capture, "
            "then a question that invites comments.\n"
            "- tags: 8-12 German + GTA search phrases (e.g. 'gta online clips', 'gta 5 fail', "
            "'gta online deutsch').\n"
            "- Standard High German, never the character ß (write ss). Do not invent events "
            "the frames do not show; if unsure, stay generic ('dieser Moment').\n"
            "Output ONLY JSON: {\"hook\": \"\", \"title\": \"\", \"description\": \"\", \"tags\": []}")})
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(model='claude-haiku-4-5-20251001', max_tokens=500,
                                     messages=[{'role': 'user', 'content': content}])
        txt = msg.content[0].text
        m = re.search(r'\{.*\}', txt, re.S)
        data = json.loads(m.group(0)) if m else {}
        out = dict(FALLBACK)
        for k in ('hook', 'title', 'description'):
            v = str(data.get(k) or '').replace('ß', 'ss').strip()
            if v:
                out[k] = v
        if isinstance(data.get('tags'), list) and data['tags']:
            out['tags'] = [str(t).replace('ß', 'ss').strip() for t in data['tags']
                           if str(t).strip()][:12]
        out['hook'] = ' '.join(out['hook'].split()[:7])
        out['title'] = out['title'][:60]
        return out
    except Exception as e:
        logger.warning(f"Clip description fell back: {e}")
        return dict(FALLBACK)


def hook_text(hook: str) -> str:
    """On-screen / spoken hook: the bundled font has no emoji, so emoji stay
    in the title only."""
    return ''.join(ch for ch in hook if ord(ch) < 0x2500).strip() or 'Warte bis zum Ende'


def compose(clip_path: str, length: float, hook: str, out_path: str,
            hook_audio: str = None) -> str:
    """One ffmpeg pass: hook band (first 3 s), subscribe pill (last third),
    brand band — all PNG overlays with alpha, video re-encoded once. With
    hook_audio the spoken hook is laid over the game sound (ducked)."""
    from video_assembler import (make_caption_layer, make_brand_layer,
                                 make_subscribe_layer, save_layer_png,
                                 CAPTION_Y, BRAND_Y, SUB_Y)
    base = out_path[:-4]
    hook_png = save_layer_png(*make_caption_layer(hook_text(hook)), base + '_hook.png')
    brand_png = save_layer_png(*make_brand_layer(), base + '_brand.png')
    sub_png = save_layer_png(*make_subscribe_layer(), base + '_sub.png')
    sub_start = max(0.0, min(length * 0.6, length - 4.0))
    sub_end = min(length, sub_start + 3.5)
    filt = (f"[0:v][1:v]overlay=0:{CAPTION_Y}:enable='lt(t,{HOOK_SECONDS})'[v1];"
            f"[v1][2:v]overlay=0:{BRAND_Y}[v2];"
            f"[v2][3:v]overlay=0:{SUB_Y}:enable='between(t,{sub_start:.2f},{sub_end:.2f})'[v]")
    cmd = [_ffmpeg(), '-y', '-i', clip_path, '-i', hook_png, '-i', brand_png, '-i', sub_png]
    if hook_audio and os.path.exists(hook_audio):
        cmd += ['-i', hook_audio]
        filt += (f";[4:a]adelay=250:all=1,apad=whole_dur={length:.2f},asplit=2[h1][h2];"
                 f"[0:a][h1]sidechaincompress=threshold=0.04:ratio=5:attack=15:release=350[g];"
                 f"[g][h2]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
        audio = ['-map', '[a]', '-c:a', 'aac', '-b:a', '160k']
    else:
        audio = ['-map', '0:a', '-c:a', 'copy']
    cmd += ['-filter_complex', filt, '-map', '[v]', '-threads', '2',
            '-c:v', 'libx264', '-preset', 'superfast', '-crf', '21', '-pix_fmt', 'yuv420p',
            *audio, '-movflags', '+faststart', out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    for p in (hook_png, brand_png, sub_png):
        try:
            os.remove(p)
        except OSError:
            pass
    if r.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"Clip compose failed: {r.stderr[-300:]}")
    return out_path


def build(entries: list, used: set, out_dir: str = OUT_DIR):
    """Pick → cut → describe → compose. Returns (video_path, script) or
    (None, None) when no unused clip is available."""
    entry, h = pick(entries, used)
    if not entry:
        return None, None
    os.makedirs(out_dir, exist_ok=True)
    tag = marker(entry['drive_id'])
    raw_cut = os.path.join(out_dir, f'clip_{tag}_cut.mp4')
    cut_path, length = cut(entry, h, raw_cut)
    if not cut_path:
        return None, None
    meta = describe(cut_path, length, entry.get('tags') or [])
    final = os.path.join(out_dir, f'clip_{tag}.mp4')
    # spoken hook (one short line — a few dozen voice characters)
    hook_audio = None
    try:
        from voice_generator import VoiceGenerator
        hook_audio = VoiceGenerator().generate(
            hook_text(meta['hook']), 'de', output_path=os.path.join(out_dir, f'hook_{tag}.mp3'))
    except Exception as e:
        logger.warning(f"Spoken hook skipped: {e}")
    compose(cut_path, length, meta['hook'], final, hook_audio=hook_audio)
    for p in (cut_path, hook_audio, (hook_audio or '') + '.words.json'):
        try:
            if p:
                os.remove(p)
        except OSError:
            pass
    # sound design: impact under the hook, pop with the subscribe pill
    try:
        from sfx import plan_events, mix_sfx
        sub_start = max(0.0, min(length * 0.6, length - 4.0))
        mix_sfx(final, plan_events(length, 0, None, sub_start, hook_impact=True))
    except Exception as e:
        logger.warning(f"Sound design skipped: {e}")
    script = {
        'title': meta['title'],
        'description': meta['description'] + f"\n\n🎮 Eigene PS5-Aufnahme · Clip-ID: {tag}",
        'tags': list(meta['tags']),
        'narration': meta['hook'],
        'sentences': [meta['hook']],
        'hook': meta['hook'],
        'clip_marker': tag,
    }
    logger.info(f"🎞️ Clip Short: {entry.get('name')} @ {h.get('start')}s "
                f"({length:.1f}s, score {h.get('score')}) — hook '{meta['hook']}'")
    return final, script


def run_clip_short(language: str = 'de'):
    """Full slot: library → unused highlight → Short → upload. Returns the
    video id or None."""
    from youtube_uploader import YouTubeUploader
    from video_assembler import _gameplay_entries, add_music_bed
    uploader = YouTubeUploader()
    recent = uploader.get_recent_performance(50)
    if not recent:
        # An empty list means the API call failed (quota, token) — without
        # the published Clip-IDs the repeat protection is blind, and a blind
        # pick can put the same moment on the channel twice. Skip the slot.
        logger.warning("🎞️ Clip slot skipped: no channel data (API failure?)")
        return None
    used = used_markers([r.get('description') for r in recent])
    entries = _gameplay_entries()
    if len(entries) < 3:
        try:
            from gameplay_sync import ensure_library
            ensure_library(min_clips=4, max_new=5, time_budget=600.0)
            entries = _gameplay_entries()
        except Exception as e:
            logger.warning(f"Clip library fill skipped: {e}")
    video, script = build(entries, used)
    if not video:
        logger.warning("🎞️ No unused own clip available — slot skipped")
        return None
    # music low under the game audio (ducked by the game sound itself)
    try:
        import video_assembler as va
        prev = va.MUSIC_VOLUME
        va.MUSIC_VOLUME = 0.08
        try:
            length = _probe(video)
            video, credit = add_music_bed(video, length)
        finally:
            va.MUSIC_VOLUME = prev
        if credit:
            script['music_credit'] = credit
        from sfx import finalize_loudness
        video = finalize_loudness(video)
    except Exception as e:
        logger.warning(f"Music bed skipped for clip short: {e}")
    vid = uploader.upload(video, script, language)
    if vid:
        logger.info(f"✅ UPLOADED clip short [{language}]: https://youtube.com/watch?v={vid}")
        uploader.add_to_topic_playlist(vid, script)
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


def _probe(path: str) -> float:
    r = subprocess.run([_ffmpeg(), '-i', path], capture_output=True, text=True)
    m = re.search(r'Duration: (\d+):(\d+):(\d+\.?\d*)', r.stderr)
    if not m:
        return CLIP_MAX
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)

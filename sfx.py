# -*- coding: utf-8 -*-
"""Sound design: a small library of generated effects (sfx/manifest.json,
made once with ElevenLabs sound generation) mixed under the finished audio
— a whoosh on every hard cut, an impact under the hook, a soft pop when the
subscribe pill appears, a cash register when the narration talks money.
Subtle by design (all well under the voice); fails soft to the dry mix."""
import os
import json
import re
import random
import logging
import subprocess

logger = logging.getLogger(__name__)

SFX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sfx')
MONEY_WORDS = {'gta$', 'dollar', 'dollars', 'million', 'millionen', 'geld',
               'cash', 'kohle', 'kostet', 'kosten', 'preis', 'gratis',
               'kostenlos', 'belohnung', 'belohnungen', 'verdienen', 'verdienst',
               'auszahlung', 'bonus', 'rabatt'}


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def library() -> dict:
    """name -> absolute path of every effect that exists on disk."""
    try:
        with open(os.path.join(SFX_DIR, 'manifest.json'), encoding='utf-8') as f:
            man = json.load(f)
        out = {}
        for e in man.get('effects', []):
            p = os.path.join(SFX_DIR, e.get('file', ''))
            if os.path.exists(p) and os.path.getsize(p) > 1000:
                out[e['name']] = p
        return out
    except Exception as e:
        logger.warning(f"SFX library unavailable: {e}")
        return {}


def plan_events(duration: float, cuts_n: int = 0, words: list = None,
                sub_start: float = None, hook_impact: bool = True) -> list:
    """[(time_s, effect_name, gain)] for one video."""
    lib = library()
    if not lib or duration <= 0:
        return []
    ev = []
    if hook_impact:
        ev.append((0.0, random.choice(['impact_1', 'impact_2']), 0.5))
    if cuts_n and cuts_n > 1:
        seg = duration / cuts_n
        for k in range(1, cuts_n):
            t = k * seg - 0.12          # whoosh leads the cut a little
            if 1.0 < t < duration - 1.0:
                ev.append((t, f'whoosh_{(k % 4) + 1}', 0.4))
    if sub_start is not None and 0.5 < sub_start < duration - 0.5:
        ev.append((sub_start, 'ding_1', 0.4))
    if words:
        last = -10.0
        n_cash = 0
        for w in words:
            txt = str(w.get('text', '')).lower().strip('.,!?:;"\'()»«')
            t = float(w.get('start', 0) or 0)
            if txt in MONEY_WORDS and t - last >= 4.0 and 1.0 < t < duration - 1.0:
                ev.append((t, random.choice(['cash_1', 'cash_2']), 0.4))
                last = t
                n_cash += 1
                if n_cash >= 2:
                    break
    ev = [e for e in ev if e[1] in lib]
    ev.sort(key=lambda e: e[0])
    return ev[:16]


def mix_sfx(video_path: str, events: list, timeout: int = 300) -> str:
    """Mix the planned effects into the video's audio track (video stream
    copied). Returns the (same) path; on any failure the input is kept."""
    if not events:
        return video_path
    lib = library()
    files = [(t, lib[n], g) for t, n, g in events if n in lib]
    if not files:
        return video_path
    out = video_path[:-4] + '_sfx.mp4'
    cmd = [_ffmpeg(), '-y', '-i', video_path]
    filt = []
    labels = []
    for i, (t, p, g) in enumerate(files):
        cmd += ['-i', p]
        ms = int(max(0.0, t) * 1000)
        filt.append(f"[{i + 1}:a]adelay={ms}:all=1,volume={g:.2f}[s{i}]")
        labels.append(f"[s{i}]")
    filt.append(f"[0:a]{''.join(labels)}amix=inputs={len(files) + 1}:duration=first"
                f":dropout_transition=0:normalize=0[a]")
    cmd += ['-filter_complex', ';'.join(filt), '-map', '0:v', '-map', '[a]',
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', out]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0 or not os.path.exists(out):
            logger.warning(f"SFX mix failed, keeping dry mix: {r.stderr[-300:]}")
            return video_path
        os.replace(out, video_path)
        logger.info(f"🔊 Sound design: {len(files)} effects "
                    f"({', '.join(sorted({os.path.basename(p)[:-4] for _, p, _ in files}))})")
        return video_path
    except Exception as e:
        logger.warning(f"SFX mix skipped: {e}")
        return video_path


def finalize_loudness(video_path: str, target_lufs: float = -14.0, timeout: int = 900) -> str:
    """Last audio pass: two-pass EBU R128 normalisation to YouTube's playback
    level (-14 LUFS, -1.5 dBTP, linear gain — no pumping, no clipping). Quiet
    uploads are NOT turned up by YouTube, so a -23 LUFS mix simply sounds
    weaker than every neighbouring Short."""
    ff = _ffmpeg()
    spec = f'I={target_lufs}:TP=-1.5:LRA=11'
    try:
        r = subprocess.run([ff, '-hide_banner', '-nostats', '-i', video_path, '-af',
                            f'loudnorm={spec}:print_format=json', '-f', 'null', '-'],
                           capture_output=True, text=True, timeout=timeout)
        m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
        meas = json.loads(m.group(0)) if m else {}
        af = f'loudnorm={spec}'
        if meas and meas.get('input_i') not in (None, '-inf'):
            af += (f":measured_I={meas['input_i']}:measured_TP={meas['input_tp']}"
                   f":measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}"
                   f":offset={meas.get('target_offset', 0)}:linear=true")
        out = video_path[:-4] + '_ln.mp4'
        r = subprocess.run([ff, '-y', '-i', video_path, '-af', af, '-map', '0:v', '-map', '0:a',
                            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', out],
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0 or not os.path.exists(out):
            logger.warning(f"Loudness pass failed, keeping mix: {r.stderr[-200:]}")
            return video_path
        os.replace(out, video_path)
        logger.info(f"🔉 Loudness: {meas.get('input_i', '?')} → {target_lufs} LUFS")
        return video_path
    except Exception as e:
        logger.warning(f"Loudness pass skipped: {e}")
        return video_path

# -*- coding: utf-8 -*-
"""Branding — production step 6: a 0.7s intro sting and a short subscribe
outro card bookending every Short. Built once per video as tiny static-image
mp4s and concatenated onto the main render — cheap on the small production
box, no extra frames in the main composite. Fails soft throughout: any
problem returns the unbranded video untouched, never breaks the upload."""
import os
import subprocess
import logging
import numpy as np
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

W, H = 1080, 1920
INTRO_LEN = 0.7
OUTRO_LEN = 1.8
BRAND_RED = (230, 33, 23)


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _intro_card_png(path: str):
    from video_assembler import load_font
    img = Image.new('RGB', (W, H), (10, 10, 14))
    d = ImageDraw.Draw(img)
    font = load_font(96)
    text = "GridPhantom"
    tb = d.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    d.text(((W - tw) // 2, (H - th) // 2 - 30), text, font=font, fill=BRAND_RED)
    sub_font = load_font(42)
    sub = "GTA 5 · GTA Online · GTA 6"
    sb = d.textbbox((0, 0), sub, font=sub_font)
    sw = sb[2] - sb[0]
    d.text(((W - sw) // 2, (H + th) // 2 + 10), sub, font=sub_font, fill=(210, 210, 210))
    img.save(path)


def _outro_card_png(path: str):
    from video_assembler import load_font, make_subscribe_layer
    img = Image.new('RGB', (W, H), (10, 10, 14))
    base = np.asarray(img).astype(np.float32)
    sub_rgb, sub_a = make_subscribe_layer()
    sub_h = sub_rgb.shape[0]
    y = H // 2 - sub_h // 2 - 60
    a = sub_a[:, :, None]
    base[y:y + sub_h] = base[y:y + sub_h] * (1 - a) + sub_rgb.astype(np.float32) * a
    img = Image.fromarray(np.clip(base, 0, 255).astype('uint8'))
    d = ImageDraw.Draw(img)
    handle_font = load_font(56)
    handle = "@GridPhantom187"
    hb = d.textbbox((0, 0), handle, font=handle_font)
    hw = hb[2] - hb[0]
    d.text(((W - hw) // 2, y + sub_h + 55), handle, font=handle_font, fill=(235, 235, 235))
    line_font = load_font(38)
    line = "Jeden Tag neuer GTA Content"
    lb = d.textbbox((0, 0), line, font=line_font)
    lw = lb[2] - lb[0]
    d.text(((W - lw) // 2, y + sub_h + 130), line, font=line_font, fill=(190, 190, 190))
    img.save(path)


def _still_to_mp4(png: str, out: str, length: float, ff: str,
                  sound: str = None, fade: str = None) -> bool:
    vf = 'format=yuv420p'
    if fade == 'in':
        vf = f'fade=t=in:st=0:d=0.2,{vf}'
    elif fade == 'out':
        vf = f'fade=t=out:st={max(length - 0.15, 0):.2f}:d=0.15,{vf}'
    cmd = [ff, '-y', '-loop', '1', '-t', f'{length}', '-i', png]
    if sound:
        cmd += ['-i', sound, '-filter_complex',
                f"[0:v]{vf}[v];[1:a]atrim=0:{length},volume=0.7[a]",
                '-map', '[v]', '-map', '[a]']
    else:
        cmd += ['-f', 'lavfi', '-t', f'{length}', '-i', 'anullsrc=r=48000:cl=stereo',
                '-vf', vf, '-map', '0:v', '-map', '1:a']
    cmd += ['-shortest', '-r', '24', '-c:v', 'libx264', '-preset', 'superfast',
            '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        logger.warning(f"Branding clip render failed: {r.stderr[-300:]}")
    return r.returncode == 0 and os.path.exists(out)


def add_branding(video_path: str) -> str:
    """Prepend a 0.7s intro sting and append a subscribe outro card."""
    try:
        ff = _ffmpeg()
        work = os.path.dirname(video_path) or '.'
        intro_png, outro_png = os.path.join(work, '_intro.png'), os.path.join(work, '_outro.png')
        intro_mp4, outro_mp4 = os.path.join(work, '_intro.mp4'), os.path.join(work, '_outro.mp4')
        _intro_card_png(intro_png)
        _outro_card_png(outro_png)

        from sfx import library
        sting = (library() or {}).get('whoosh_1')

        if not _still_to_mp4(intro_png, intro_mp4, INTRO_LEN, ff, sound=sting, fade='out'):
            return video_path
        if not _still_to_mp4(outro_png, outro_mp4, OUTRO_LEN, ff, fade='in'):
            return video_path

        concat_list = os.path.join(work, '_concat.txt')
        with open(concat_list, 'w') as f:
            for p in (intro_mp4, video_path, outro_mp4):
                f.write(f"file '{os.path.abspath(p)}'\n")
        out = video_path[:-4] + '_branded.mp4'
        r = subprocess.run([ff, '-y', '-f', 'concat', '-safe', '0', '-i', concat_list,
                            '-c', 'copy', out], capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not os.path.exists(out):
            # stream-copy needs identical codecs/params; re-encode as fallback
            r = subprocess.run([ff, '-y', '-f', 'concat', '-safe', '0', '-i', concat_list,
                                '-c:v', 'libx264', '-preset', 'superfast', '-crf', '22',
                                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', out],
                               capture_output=True, text=True, timeout=180)
        if r.returncode != 0 or not os.path.exists(out):
            logger.warning(f"Branding concat failed, keeping unbranded: {r.stderr[-300:]}")
            return video_path
        os.replace(out, video_path)
        for p in (intro_png, outro_png, intro_mp4, outro_mp4, concat_list):
            try:
                os.remove(p)
            except Exception:
                pass
        logger.info("🎬 Branding: intro sting + subscribe outro card added")
        return video_path
    except Exception as e:
        logger.warning(f"Branding skipped: {e}")
        return video_path

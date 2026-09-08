# -*- coding: utf-8 -*-
"""Camera motion for background segments — production step 3.

Nothing in the frame stands still any more: every segment gets a slow
push-in, pull-out or pan. Implemented as a cheap ffmpeg filter (scale to
~110 % + a crop whose position moves with time), which costs almost nothing
on the small production box, unlike zoompan. Directions alternate per
segment so consecutive cuts feel different."""

W, H = 1080, 1920
OVERSCAN = 1.10  # 10 % headroom for the move


def motion_vf(index: int, seg_len: float, w: int = W, h: int = H) -> str:
    """ffmpeg -vf chain producing a w x h output with a slow camera move
    over seg_len seconds. index picks the move: 0 push-in (top-left →
    centre), 1 pan right, 2 pull-out (centre → left), 3 pan up, ..."""
    bw, bh = int(w * OVERSCAN) // 2 * 2, int(h * OVERSCAN) // 2 * 2
    d = max(seg_len, 0.5)
    dx, dy = bw - w, bh - h
    moves = [
        (f"(iw-ow)*t/{d:.2f}", f"(ih-oh)*t/{d:.2f}"),          # diagonal push
        (f"(iw-ow)*t/{d:.2f}", f"(ih-oh)/2"),                  # pan right
        (f"(iw-ow)*(1-t/{d:.2f})", f"(ih-oh)*(1-t/{d:.2f})"),  # diagonal back
        (f"(iw-ow)/2", f"(ih-oh)*(1-t/{d:.2f})"),              # pan up
        (f"(iw-ow)*(1-t/{d:.2f})", f"(ih-oh)/2"),              # pan left
        (f"(iw-ow)/2", f"(ih-oh)*t/{d:.2f}"),                  # pan down
    ]
    x, y = moves[index % len(moves)]
    return (f"scale={bw}:{bh}:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop={bw}:{bh},crop={w}:{h}:x='{x}':y='{y}'")


# Light "punch" grade for the owner's raw captures (contrast, colour, a touch
# of sharpness): consoles record flat, the feed rewards vivid frames. Not
# applied to official trailer footage, which is already graded.
GRADE = 'eq=contrast=1.06:saturation=1.22:brightness=0.01,unsharp=5:5:0.45:5:5:0.0'

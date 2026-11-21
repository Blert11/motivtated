"""Quran recitation clips: Arabic ayah + English (Saheeh International) over dark mosque B-roll.
Renders one sequence in 4 formats: full 9:16, 9:16 with 3:4 window, 9:16 with square window, 16:9.
"""
import json, re, subprocess, sys, os, math
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts/')
FPS = 60
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- text
_cache = {}
def is_ar(s): return any('؀' <= c <= 'ۿ' or 'ﭐ' <= c <= '﷿' or 'ﹰ' <= c <= '﻿' for c in s)

def wrap(txt, font, size, maxw):
    f = ImageFont.truetype(FD + font, size); words = txt.split(); lines = []; cur = ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if f.getlength(t) <= maxw or not cur: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    # balance two-line splits
    return lines

def text_img(txt, font, size, color=(255, 255, 255), spacing=0.0, line=1.3, shadow=0.0, maxw=None):
    k = (txt, font, size, color, spacing, line, shadow, maxw)
    if k in _cache: return _cache[k]
    f = ImageFont.truetype(FD + font, size); ar = is_ar(txt)
    lines = wrap(txt, font, size, maxw) if maxw else txt.split('\n')
    def lw(s):
        if spacing and not ar: return sum(f.getlength(c) for c in s) + spacing * size * (len(s) - 1)
        return f.getlength(s)
    tw = int(max(lw(s) for s in lines)) + 80
    asc, desc = f.getmetrics(); lh = int(size * (1.75 if ar else line))
    th = lh * (len(lines) - 1) + asc + desc + 80
    im = Image.new('RGBA', (tw, th), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for i, s in enumerate(lines):
        y = 40 + i * lh + asc; x = (tw - lw(s)) / 2
        if spacing and not ar:
            for c in s: d.text((x, y), c, font=f, fill=color + (255,), anchor='ls'); x += f.getlength(c) + spacing * size
        else:
            d.text((x, y), s, font=f, fill=color + (255,), anchor='ls', direction='rtl' if ar else None)
    a = np.asarray(im).astype(np.float32) / 255.
    rgb = a[..., 2::-1].copy(); al = a[..., 3:4].copy()
    if shadow:
        sa = cv2.GaussianBlur(al[..., 0], (0, 0), max(3, size * 0.18)) * shadow
        A = al[..., 0] + sa * (1 - al[..., 0])
        C = (rgb * al) / np.maximum(A, 1e-4)[..., None]
        rgb, al = C, A[..., None]
    _cache[k] = (rgb, al)
    return rgb, al

def blit(cv, img, cx, cy, op=1.0, anchor='center'):
    rgb, al = img; h, w = rgb.shape[:2]; H, W = cv.shape[:2]
    x = int(cx - w / 2) if anchor == 'center' else (int(cx - w) if anchor == 'right' else int(cx)); y = int(cy - h / 2)
    xs, ys, xe, ye = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if xe <= xs or ye <= ys or op <= 0.004: return
    a = al[ys - y:ye - y, xs - x:xe - x] * op
    cv[ys:ye, xs:xe] = cv[ys:ye, xs:xe] * (1 - a) + rgb[ys - y:ye - y, xs - x:xe - x] * 255 * a

def ease(x): x = min(1, max(0, x)); return x * x * (3 - 2 * x)

# ---------------------------------------------------------------- data
QJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'qj/')
AR = json.load(open(QJ + 'tanzil/uthmani.json', encoding='utf-8'))
EN = json.load(open(QJ + 'quranenc/english_saheeh.json', encoding='utf-8'))
CH = {c['id']: c for c in json.load(open(QJ + 'tanzil/chapters.json', encoding='utf-8'))['chapters']}
AD = '٠١٢٣٤٥٦٧٨٩'
def ar_num(n): return ''.join(AD[int(c)] for c in str(n))
def en_clean(t):
    t = re.sub(r'^\(\d+\)\s*', '', t); t = re.sub(r'\[\d+\]', '', t)
    return re.sub(r'\s+', ' ', t).strip()
def ayah(s, v):
    if v == 'T': return 'أَعُوذُ بِٱللَّهِ مِنَ ٱلشَّيْطَٰنِ ٱلرَّجِيمِ', 'I seek refuge in Allah from Satan, the accursed.'
    if v == 'B': return AR['1'][0]['text'], en_clean(EN['1'][0]['text'])
    a = AR[str(s)][v - 1]['text']
    if s != 1 and v == 1 and a.startswith('بِسْمِ'): a = a.split(' ', 4)[-1]
    return a + ' \u06dd' + ar_num(v), en_clean(EN[str(s)][v - 1]['text'])

# ---------------------------------------------------------------- footage
LIB = json.load(open('/home/claude/w/broll_lib.json')) if os.path.exists('/home/claude/w/broll_lib.json') else {}
SRC = {'adhan': '/mnt/user-data/uploads/imanivated/B-Roll videos/2-hours-adhan-ezan-beautiful-muslim-call-to-prayer-with-mosques-around-the-world-ytmp4.savetube.vip.mp4',
       'mosq': '/mnt/user-data/uploads/imanivated/B-Roll videos/10-most-beautiful-mosques-in-the-world-ytmp4.savetube.vip.mp4'}
SLOW = 1.6

def prep_shot(i, dur):
    """slowed, frame-interpolated to 60 fps, upscaled, sharpened, then graded darker in python."""
    p = f'/home/claude/w/quran/shots/{i}_{dur:.2f}.mp4'
    if not os.path.exists(p):
        b = LIB[i]
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(b['t'] + 0.2), '-t', str(dur / SLOW + 0.3), '-i', SRC[b['src']],
                        '-vf', f'setpts={SLOW}*PTS,minterpolate=fps={FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,'
                               'scale=1920:1080:flags=lanczos,cas=0.7,hqdn3d=1.5:1.5:3:3',
                        '-an', '-c:v', 'libx264', '-crf', '14', '-preset', 'veryfast', p], check=True)
    return p

class Shot:
    def __init__(self, path):
        self.cap = cv2.VideoCapture(path); self.last = None
    def next(self):
        ok, f = self.cap.read()
        if ok: self.last = f
        return self.last

_vig = {}
def grade(f, W, H):
    """dark, rich, filmic: lower exposure, gentle S-curve, a bit more colour, vignette."""
    x = f.astype(np.float32) / 255.
    x = x ** 1.25 * 0.72
    g = x.mean(2, keepdims=True); x = g + (x - g) * 1.18
    x = np.clip(x, 0, 1)
    if (W, H) not in _vig:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = ((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2
        _vig[(W, H)] = np.clip(1 - 0.55 * r, 0.25, 1)[..., None]
    return x * 255 * _vig[(W, H)]

def cover(img, W, H, zoom=1.0):
    h, w = img.shape[:2]; s = max(W / w, H / h) * zoom
    nw, nh = int(w * s + 0.5), int(h * s + 0.5)
    r = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    x0, y0 = (nw - W) // 2, (nh - H) // 2
    return r[y0:y0 + H, x0:x0 + W]

def round_mask(w, h, r):
    m = np.zeros((h, w), np.float32); cv2.rectangle(m, (r, 0), (w - r, h), 1, -1); cv2.rectangle(m, (0, r), (w, h - r), 1, -1)
    for cx, cy in [(r, r), (w - r, r), (r, h - r), (w - r, h - r)]: cv2.circle(m, (cx, cy), r, 1, -1, cv2.LINE_AA)
    return cv2.GaussianBlur(m, (0, 0), 0.8)[..., None]

# ---------------------------------------------------------------- formats
FORMATS = {
    'full': dict(W=1080, H=1920, win=None),
    'rect': dict(W=1080, H=1920, win=(960, 1280)),
    'square': dict(W=1080, H=1920, win=(960, 960)),
    'wide': dict(W=1920, H=1080, win=None),
}

def render(job):
    s = job['surah']; ch = CH[s]
    a0, a1 = job['start'], job['end']; dur = a1 - a0
    segs = [x for x in job['segs'] if x[1] - a0 < dur - 0.5]
    # display windows: from just before each segment's audio to the next one
    disp = []
    for k, (v, s0, s1) in enumerate(segs):
        st = max(0.0, s0 - a0 - 0.35)
        en = (segs[k + 1][1] - a0 - 0.35) if k + 1 < len(segs) else dur
        disp.append((v, st, en))
    shots = []
    for (v, st, en), sid in zip(disp, job['shots']):
        shots.append((st, en, prep_shot(sid, en - st + 0.8)))
    # audio: trimmed recitation only, no music
    wav = f"{OUT}/{job['name']}.wav"
    fi, fo = 0.3, 1.5
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(a0), '-t', str(dur), '-i', job['audio'], '-ac', '2', '-ar', '48000',
                    '-af', f'afade=t=in:d={fi},afade=t=out:st={dur - fo}:d={fo},loudnorm=I=-14:TP=-1.5:LRA=11', wav], check=True)
    surah_ar = 'سُورَةُ ' + ch['name']
    surah_en = f"SURAH {job['surah_en'].upper()}  ·  {ch['translation'].upper()}"
    encs = {}
    for fmt, F in FORMATS.items():
        if job.get('formats') and fmt not in job['formats']: continue
        W, H = F['W'], F['H']
        encs[fmt] = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                                      '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'medium', '-crf', '17',
                                      '-maxrate', '18M', '-bufsize', '36M', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest',
                                      '-movflags', '+faststart', f"{OUT}/{job['name']}_{fmt}.mp4"], stdin=subprocess.PIPE)
    caps = [Shot(p) for _, _, p in shots]
    rng = np.random.default_rng(1)
    grain = [rng.normal(0, 1, (540, 960)).astype(np.float32) for _ in range(6)]
    masks = {}
    n = int(dur * FPS)
    XF = 0.5
    for fi_ in range(n):
        t = fi_ / FPS
        # current + crossfading shot (each shot frame advances only while visible)
        frames = []
        for k, (st, en, _) in enumerate(shots):
            if st - 0.001 <= t < en + XF:
                fr = caps[k].next()
                if fr is not None:
                    a = 1.0 if k == 0 else ease((t - st) / XF)
                    frames.append((a, fr, (t - st) / max(1, en - st + XF)))
        base = None
        for a, fr, u in frames:
            img = fr if base is None else fr
            if base is None: base = (img.astype(np.float32), u)
            else: base = (base[0] * (1 - a) + img.astype(np.float32) * a, u)
        src, u = base
        g = grain[(fi_ // 2) % 6]
        # which ayah is showing
        cur = None
        for v, st, en in disp:
            if st <= t < en: cur = (v, st, en)
        for fmt, enc in encs.items():
            F = FORMATS[fmt]; W, H = F['W'], F['H']
            z = 1.04 + 0.05 * u   # slow push-in within each shot
            if F['win'] is None:
                cv = grade(cover(src, W, H, z), W, H)
                if fmt == 'full': cv = cv * 0.92
            else:
                ww, wh = F['win']
                bg = cv2.GaussianBlur(cover(src, W // 4, H // 4, 1.1), (0, 0), 6)
                cv = grade(cv2.resize(bg, (W, H)), W, H) * 0.45
                win = grade(cover(src, ww, wh, z), ww, wh)
                if (ww, wh) not in masks: masks[(ww, wh)] = round_mask(ww, wh, 28)
                m = masks[(ww, wh)]; x0, y0 = (W - ww) // 2, (H - wh) // 2
                cv[y0:y0 + wh, x0:x0 + ww] = cv[y0:y0 + wh, x0:x0 + ww] * (1 - m) + win * m
            # text darkening band behind the ayah for legibility
            gg = cv2.resize(g, (W, H)) if (W, H) != (960, 540) else g
            cv += gg[..., None] * 5.0
            wide = W > H
            cy = H // 2
            # reciter, top right (small)
            mx = 54 if wide else 50
            blit(cv, text_img('القارئ أنس لهبوبي', 'Amiri-Bold.ttf', 30 if wide else 30, (255, 255, 255), shadow=0.6), W - mx + 40, (62 if wide else 120), 0.85, 'right')
            blit(cv, text_img('ANAS LAHBOUBI', 'Montserrat-SemiBold.ttf', 17, (225, 225, 225), spacing=0.25, shadow=0.6), W - mx + 40, (104 if wide else 162), 0.75, 'right')
            # surah name
            if wide:
                blit(cv, text_img(surah_ar, 'Amiri-Bold.ttf', 40, (255, 255, 255), shadow=0.6), 70 - 40, 62, 0.9, 'left')
                blit(cv, text_img(surah_en, 'Montserrat-SemiBold.ttf', 17, (225, 225, 225), spacing=0.22, shadow=0.6), 70 - 40, 104, 0.75, 'left')
            else:
                top = (H - F['win'][1]) // 2 if F['win'] else 330
                ys = top - 120 if F['win'] else 330
                blit(cv, text_img(surah_ar, 'Amiri-Bold.ttf', 58, (255, 255, 255), shadow=0.6), W / 2, ys, 0.95)
                blit(cv, text_img(surah_en, 'Montserrat-SemiBold.ttf', 20, (230, 230, 230), spacing=0.25, shadow=0.6), W / 2, ys + 66, 0.8)
            # ayah
            if cur:
                v, st, en = cur
                ar, en_t = ayah(s, v)
                fin = ease((t - st) / 0.5); fout = 1 - ease((t - (en - 0.3)) / 0.3) if v != disp[-1][0] else 1.0
                op = fin * fout
                maxw = 1500 if wide else (860 if F['win'] else 920)
                ai = text_img(ar, 'Amiri-Bold.ttf', 66 if wide else 64, (255, 255, 255), shadow=0.75, maxw=maxw)
                ei = text_img(en_t, 'MonaSans-Medium.otf', 32 if wide else 31, (232, 228, 218), line=1.35, shadow=0.75, maxw=maxw - 60)
                ha, he = ai[0].shape[0], ei[0].shape[0]; gap = -34
                tot = ha + he + gap; y0 = cy - tot / 2
                lift = 14 * (1 - fin)
                blit(cv, ai, W / 2, y0 + ha / 2 + lift, op)
                blit(cv, ei, W / 2, y0 + ha + gap + he / 2 + lift, op * 0.95)
            # watermark
            blit(cv, text_img('@IMANIVATED', 'Montserrat-SemiBold.ttf', 20, (255, 255, 255), spacing=0.3), W / 2, H - (60 if wide else 150), 0.5)
            # fade from/to black
            fb = ease(t / 0.6) * (1 - ease((t - (dur - 1.0)) / 1.0))
            cv *= fb
            enc.stdin.write(np.clip(cv, 0, 255).astype(np.uint8).tobytes())
        if fi_ % 600 == 0: print(f'{t:.0f}s', flush=True)
    for enc in encs.values():
        enc.stdin.close(); enc.wait()

if __name__ == '__main__':
    job = json.load(open(sys.argv[1]))
    if len(sys.argv) > 2: job['formats'] = sys.argv[2].split(',')
    if len(sys.argv) > 3: job['end'] = job['start'] + float(sys.argv[3])
    render(job)
    print('done')

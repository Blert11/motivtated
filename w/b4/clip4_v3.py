"""Batch 4 clips (Nov 14 references): 1080x1920, head stabilization on every speaker clip.
styles:
  bright : @dayofreturn  - full 9:16, head locked (fixed spot + size), bright hazy bloom grade,
           small bold white UPPERCASE 1-3 words, one red keyword, centred
  cinema : @islami1cwhispers - 16:9 band between black bars, head locked inside the band,
           warm teal/orange grade, thin white serif caps (Cinzel) 1-2 words, centred
  text   : @deen9.2 - no speaker, calm mosque B-roll, soft serif lines appearing one by one,
           italic speaker credit underneath
usage: python3 clip4.py CID [CID...]
"""
import sys, os, json, re, subprocess, math, random
import numpy as np, cv2, soundfile as sf
sys.path.insert(0, '/home/claude/w'); sys.path.insert(0, '/home/claude/w/long1')
import caps, render2, fx3
import longvid as L
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
OFPS = 60   # output frame rate (in-between frames by optical flow)
FD = '/home/claude/fonts/'
B4 = '/home/claude/w/b4'
OUT = '/home/claude/w/out'
CL = json.load(open(f'{B4}/clips.json'))
MUSIC = '/home/claude/w/mus/m_new.wav'; MUS_ENTRY = 2.9
AR = re.compile(r'[؀-ۿﷰ-﷿]')
STOP = set('the a an and or but to of in on at for with is are was were be been am i you he she it we they my your his her our their this that these those me him us them so if as by from not no do does did have has had just like gonna will would can could all any some what when where why how then than there here now very really bro akhi yeah okay'.split())

def sh(*a): subprocess.run(a, check=True)

# ------------------------------------------------------------------ text helpers
def rgba(im):
    a = np.asarray(im).astype(np.float32) / 255.
    return a[..., 2::-1].copy(), a[..., 3:4].copy()

def over(canvas, rgb, al, x, y, op=1.0):
    h, w = rgb.shape[:2]; CH, CW = canvas.shape[:2]
    xs, ys, xe, ye = max(0, x), max(0, y), min(CW, x + w), min(CH, y + h)
    if xe <= xs or ye <= ys or op <= 0.003: return
    r = rgb[ys - y:ye - y, xs - x:xe - x]; a = al[ys - y:ye - y, xs - x:xe - x] * op
    canvas[ys:ye, xs:xe] = canvas[ys:ye, xs:xe] * (1 - a) + r * 255 * a

def run_img(runs, pad=40, shadow=0.55, glow=None, spacing=0.0):
    """runs: list of (text, font_path, size, rgb) drawn on one line -> (rgb, alpha) with soft shadow."""
    fonts = [ImageFont.truetype(f, s) for _, f, s, _ in runs]
    widths = []
    for (t, _, s, _), f in zip(runs, fonts):
        if spacing and not AR.search(t): widths.append(sum(f.getlength(c) for c in t) + spacing * s * (len(t) - 1))
        else: widths.append(f.getlength(t))
    gap = [runs[i][2] * 0.28 for i in range(len(runs))]
    tw = int(sum(widths) + sum(gap[:-1])) + 2 * pad
    asc = max(f.getmetrics()[0] for f in fonts); desc = max(f.getmetrics()[1] for f in fonts)
    th = asc + desc + 2 * pad
    txt = Image.new('RGBA', (tw, th), (0, 0, 0, 0)); d = ImageDraw.Draw(txt)
    x = pad
    for (t, _, s, col), f, wdt, g in zip(runs, fonts, widths, gap):
        base = pad + asc
        if spacing and not AR.search(t):
            for c in t: d.text((x, base), c, font=f, fill=col + (255,), anchor='ls'); x += f.getlength(c) + spacing * s
            x += g - spacing * s
        else:
            d.text((x, base), t, font=f, fill=col + (255,), anchor='ls', direction='rtl' if AR.search(t) else None); x += wdt + g
    a = np.asarray(txt).astype(np.float32) / 255.
    rgb = a[..., 2::-1].copy(); al = a[..., 3]
    out_rgb = np.zeros_like(rgb); out_a = np.zeros_like(al)
    if shadow:
        sa = cv2.GaussianBlur(al, (0, 0), max(2, runs[0][2] * 0.12)) * shadow
        sa = np.roll(sa, int(runs[0][2] * 0.05), axis=0)
        out_a = sa
    if glow is not None:
        ga = cv2.GaussianBlur(al, (0, 0), runs[0][2] * 0.22) * glow[1]
        out_rgb = out_rgb * (1 - ga[..., None]) + np.array(glow[0][::-1], np.float32)[None, None] / 255 * ga[..., None]
        out_a = np.maximum(out_a, ga)
    # composite text over shadow/glow (premultiplied-style)
    A = al + out_a * (1 - al)
    C = (rgb * al[..., None] + out_rgb * (out_a * (1 - al))[..., None]) / np.maximum(A, 1e-4)[..., None]
    return C, A[..., None]

def keyword(words):
    """index of the most meaningful word (longest non-stopword), or None."""
    best, bi = 0, None
    for i, w in enumerate(words):
        if w['sacred']: continue
        n = re.sub(r"[^a-z']", '', w['text'].lower())
        if n in STOP or len(n) < 4: continue
        if len(n) > best: best, bi = len(n), i
    return bi

# ------------------------------------------------------------------ caption styles
class BrightCaps:
    def __init__(self, units, cy):
        self.cy = cy; self.items = []
        rng = random.Random(4)
        for u in units:
            ws = u['words']; k = keyword(ws) if rng.random() < 0.6 else None
            runs = []
            for i, w in enumerate(ws):
                col = (255, 40, 40) if i == k else (255, 255, 255)
                runs.append((w['text'].upper(), FD + 'Montserrat-ExtraBold.ttf', 50, col))
                if w['ar']: runs.append((w['ar'], FD + 'NotoNaskhArabic.ttf', 54, (255, 255, 255)))
            self.items.append((u['t0'], u['t1'], run_img(runs, shadow=0.75, glow=((255, 255, 255), 0.18))))
    def draw(self, cv, t):
        for t0, t1, (rgb, al) in self.items:
            if t0 <= t < t1:
                age = t - t0; s = 0.88 + 0.12 * fx3.ease(np.array(age / 0.09)).item()
                if s < 0.999:
                    h, w = rgb.shape[:2]; nw, nh = int(w * s), int(h * s)
                    rgb2 = cv2.resize(rgb, (nw, nh)); al2 = cv2.resize(al, (nw, nh))[..., None]
                else: rgb2, al2 = rgb, al
                h, w = rgb2.shape[:2]
                over(cv, rgb2, al2, W // 2 - w // 2, int(self.cy - h / 2), min(1, age / 0.05)); return

class CinemaCaps:
    def __init__(self, units, cy):
        self.cy = cy; self.items = []
        for u in units:
            runs = []
            for w in u['words']:
                runs.append((w['text'].upper(), FD + 'Cinzel-Medium.ttf', 46, (255, 255, 255)))
                if w['ar']: runs.append((w['ar'], FD + 'Amiri-Regular.ttf', 50, (255, 255, 255)))
            self.items.append((u['t0'], u['t1'], run_img(runs, shadow=0.85, spacing=0.06)))
    def draw(self, cv, t):
        for t0, t1, (rgb, al) in self.items:
            if t0 <= t < t1:
                op = min(1, (t - t0) / 0.12) * min(1, (t1 - t) / 0.08 + 0.3)
                h, w = rgb.shape[:2]; over(cv, rgb, al, W // 2 - w // 2, int(self.cy - h / 2), min(1, op)); return

class TextLines:
    """soft serif lines appear one by one (max 3 on screen), cleared at sentence ends; credit underneath."""
    def __init__(self, words, credit, cy):
        self.cy = cy
        F = FD + 'Cormorant-Medium.ttf'; SZ = 66; MAXC = 24
        lines = []; cur = [];
        for w in words:
            txt = w['text']
            cur.append(w)
            ln = ' '.join(x['text'] for x in cur)
            end = bool(re.search(r'[.!?]$', txt)); comma = txt.endswith(',')
            if len(ln) >= MAXC or end or (comma and len(ln) > 12):
                lines.append((cur, end)); cur = []
        if cur: lines.append((cur, True))
        # pages: up to 3 lines, break after a sentence end
        self.pages = []; pg = []
        for ln, end in lines:
            pg.append(ln)
            if len(pg) == 3 or (end and len(pg) >= 2):
                self.pages.append(pg); pg = []
        if pg: self.pages.append(pg)
        self.render = []
        for pg in self.pages:
            imgs = []
            for ln in pg:
                runs = []
                for w in ln:
                    runs.append((w['text'], F, SZ, (255, 255, 255)))
                    if w['ar']: runs.append((w['ar'], FD + 'Amiri-Regular.ttf', SZ - 6, (255, 255, 255)))
                imgs.append((ln[0]['t0'], run_img(runs, shadow=0.8, pad=30)))
            t_end = pg[-1][-1]['t1']
            self.render.append((pg[0][0]['t0'], t_end, imgs))
        # page end = next page start
        for i in range(len(self.render) - 1):
            s, e, im = self.render[i]; self.render[i] = (s, self.render[i + 1][0], im)
        self.credit = run_img([(credit, FD + 'Cormorant-MediumItalic.ttf', 40, (235, 235, 235))], shadow=0.7, pad=20)
        self.lh = int(SZ * 1.25)
    def draw(self, cv, t):
        for s, e, imgs in self.render:
            if s <= t < e + 0.0:
                n = len(imgs); top = self.cy - (n - 1) * self.lh / 2
                fade_out = min(1, max(0, (e - t) / 0.25))
                for i, (t0, (rgb, al)) in enumerate(imgs):
                    if t < t0: continue
                    op = min(1, (t - t0) / 0.35) * fade_out
                    h, w = rgb.shape[:2]
                    over(cv, rgb, al, W // 2 - w // 2, int(top + i * self.lh - h / 2 - (1 - min(1, (t - t0) / 0.35)) * 10), op)
                break
        rgb, al = self.credit; h, w = rgb.shape[:2]
        over(cv, rgb, al, W // 2 - w // 2, int(self.cy + 2.2 * self.lh), 0.75)

# ------------------------------------------------------------------ grades
GRADE = {
 'bright': "eq=brightness=0.015:contrast=1.07:saturation=0.92:gamma=1.02,colorbalance=rs=-0.02:bs=0.03:rh=0.03:bh=-0.02,curves=all='0/0.02 0.5/0.50 1/0.97'",
 'cinema': "eq=contrast=1.08:saturation=0.92:brightness=-0.02,colorbalance=rs=-0.06:gs=0.0:bs=0.07:rh=0.07:gh=0.02:bh=-0.06,curves=all='0/0.02 0.5/0.47 1/0.95'",
 'text':   "eq=brightness=-0.03:contrast=0.95:saturation=0.70:gamma=1.02,colorbalance=bs=0.04:rh=0.02,curves=all='0/0.04 0.5/0.45 1/0.88',gblur=sigma=1.2",
}

def bloom(cv, amt, white_edge=0.0):
    sm = cv2.resize(cv, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    sm = cv2.GaussianBlur(sm, (0, 0), 9)
    b = cv2.resize(sm, (W, H), interpolation=cv2.INTER_LINEAR)
    out = 255 - (255 - cv) * (255 - b * amt) / 255.
    if white_edge:
        out = out * (1 - EDGE * white_edge) + 255 * EDGE * white_edge
    return out

yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
_r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
EDGE = np.clip((_r - 0.75) / 0.6, 0, 1)[..., None] ** 1.6
VIG = (1 - 0.35 * np.clip((_r - 0.55) / 0.8, 0, 1) ** 1.5)[..., None]

# ------------------------------------------------------------------ head lock
def track(src, a, d, crop=None, pre=''):
    vf = pre + 'scale=640:360'
    if crop: cw, chh, cx, cy = crop; vf = pre + f'crop={cw}:{chh}:{cx}:{cy},scale=640:360'
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f'{a:.3f}', '-t', f'{d:.3f}', '-i', src, '-vf', vf + f',fps={FPS}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE)
    n = int(round(d * FPS))
    def it():
        while True:
            b = p.stdout.read(640 * 360 * 3)
            if len(b) < 640 * 360 * 3: return
            yield np.frombuffer(b, np.uint8).reshape(360, 640, 3)
    global CUTS
    CUTS = []; prev = [None]; idx = [0]
    def it2():
        for f in it():
            g = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (160, 90)).astype(np.float32)
            if prev[0] is not None and np.mean(np.abs(g - prev[0])) > 28: CUTS.append(idx[0])
            prev[0] = g; idx[0] += 1
            yield f
    xs, ys, ss = fx3.face_track(it2(), n, 640, 360)
    p.stdout.close(); p.wait()
    return xs, ys, ss, n

def lock_path(xs, ys, ss, n, SW, SH, OW, OH, head_frac, head_y, min_s):
    """per-frame (cx, cy) in source px + constant scale s: head held at a fixed point and size."""
    k = SW / 640.
    xs, ys, ss = xs * k, ys * k, ss * k
    fs = float(np.median(ss))
    s = max(min_s, OH * head_frac / max(fs, 20))
    from scipy.ndimage import gaussian_filter1d, median_filter
    cx = np.empty_like(xs); cy = np.empty_like(ys)
    bounds = [0] + [c for c in CUTS if 0 < c < len(xs)] + [len(xs)]
    for a_, b_ in zip(bounds[:-1], bounds[1:]):
        if b_ - a_ < 3: cx[a_:b_] = xs[a_:b_]; cy[a_:b_] = ys[a_:b_]; continue
        cx[a_:b_] = gaussian_filter1d(median_filter(xs[a_:b_], min(9, b_ - a_), mode='nearest'), 10, mode='nearest')
        cy[a_:b_] = gaussian_filter1d(median_filter(ys[a_:b_], min(9, b_ - a_), mode='nearest'), 10, mode='nearest')
    # put the head at (0.5, head_y) of the output
    cy = cy + (0.5 - head_y) * OH / s
    hw, hh = OW / s / 2, OH / s / 2
    P = PADF * SW
    cx = np.clip(cx, hw - P, SW - hw + P); cy = np.clip(cy, hh - P, SH - hh + P)
    return cx, cy, s

_DIS = None; _GRID = {}
def midframe(a, b):
    """optical-flow in-between frame of a and b (same size)."""
    global _DIS
    if _DIS is None: _DIS = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
    Hh, Ww = a.shape[:2]; lw = 480; lh = max(2, int(round(Hh * lw / Ww)))
    sa = cv2.cvtColor(cv2.resize(a, (lw, lh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    sb = cv2.cvtColor(cv2.resize(b, (lw, lh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    f01 = _DIS.calc(sa, sb, None); f10 = _DIS.calc(sb, sa, None)
    k = Ww / lw
    f01 = cv2.resize(f01, (Ww, Hh)) * (0.5 * k); f10 = cv2.resize(f10, (Ww, Hh)) * (0.5 * k)
    if (Ww, Hh) not in _GRID:
        gx, gy = np.meshgrid(np.arange(Ww, dtype=np.float32), np.arange(Hh, dtype=np.float32)); _GRID[(Ww, Hh)] = (gx, gy)
    gx, gy = _GRID[(Ww, Hh)]
    wa = cv2.remap(a, gx + f10[..., 0], gy + f10[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    wb = cv2.remap(b, gx + f01[..., 0], gy + f01[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return cv2.addWeighted(wa, 0.5, wb, 0.5, 0)

CUTS = []
PADF = 0.0

# ---- AI portrait mode: human segmentation (U2-Net human seg) + optical-flow mask propagation
class Portrait:
    KEY = 6  # run the network on every 6th source frame; flow carries the mask in between
    def __init__(self):
        import onnxruntime as ort
        o = ort.SessionOptions(); o.intra_op_num_threads = 2
        self.s = ort.InferenceSession('/home/claude/models/u2net_human_seg.onnx', o, providers=['CPUExecutionProvider'])
        self.inp = self.s.get_inputs()[0].name
        self.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
        self.prev_g = None; self.prev_m = None; self.j = 0
    def net(self, fr):
        x = cv2.resize(fr, (320, 320), interpolation=cv2.INTER_AREA)[..., ::-1].astype(np.float32) / 255.
        x = ((x - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)).transpose(2, 0, 1)[None].astype(np.float32)
        o = self.s.run(None, {self.inp: x})[0][0, 0]
        o = (o - o.min()) / (o.max() - o.min() + 1e-6)
        return o
    def next(self, fr):
        """mask (low res, 0..1) for the next source frame in order."""
        h, w = fr.shape[:2]; lw, lh = 480, int(round(480 * h / w))
        g = cv2.cvtColor(cv2.resize(fr, (lw, lh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        cut = self.prev_g is not None and np.mean(np.abs(g.astype(np.float32) - self.prev_g.astype(np.float32))) > 28
        if self.prev_m is None or self.j % self.KEY == 0 or cut:
            m = cv2.resize(self.net(fr), (lw, lh))
            if self.prev_m is not None and not cut:
                fl = self.dis.calc(g, self.prev_g, None)
                gx, gy = np.meshgrid(np.arange(lw, dtype=np.float32), np.arange(lh, dtype=np.float32))
                wm_ = cv2.remap(self.prev_m, gx + fl[..., 0], gy + fl[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                m = 0.75 * m + 0.25 * wm_
        else:
            fl = self.dis.calc(g, self.prev_g, None)
            gx, gy = np.meshgrid(np.arange(lw, dtype=np.float32), np.arange(lh, dtype=np.float32))
            m = cv2.remap(self.prev_m, gx + fl[..., 0], gy + fl[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        self.prev_g = g; self.prev_m = m; self.j += 1
        return m

def portrait_fx(fr, m):
    """background: soft depth blur, darker and a little desaturated; subject untouched and slightly lifted."""
    h, w = fr.shape[:2]
    sm = cv2.resize(fr, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    bl = cv2.GaussianBlur(sm, (0, 0), 3.2)
    bl = cv2.resize(bl, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    gray = bl.mean(axis=2, keepdims=True)
    bg = (bl * 0.8 + gray * 0.2) * 0.72
    mm = cv2.GaussianBlur(np.clip((m - 0.15) / 0.7, 0, 1), (0, 0), 2.0)
    mm = cv2.resize(mm, (w, h), interpolation=cv2.INTER_LINEAR)[..., None]
    fg = fr.astype(np.float32) * 1.04
    return np.clip(fg * mm + bg * (1 - mm), 0, 255).astype(np.uint8)
def padded(fr):
    """source frame with a blurred mirrored border so a head lock can move past the edges."""
    SH, SW = fr.shape[:2]; P = int(PADF * SW)
    big = cv2.copyMakeBorder(fr, P, P, P, P, cv2.BORDER_REFLECT)
    sm = cv2.resize(big, (big.shape[1] // 8, big.shape[0] // 8), interpolation=cv2.INTER_AREA)
    sm = cv2.GaussianBlur(sm, (0, 0), 3)
    out = cv2.resize(sm, (big.shape[1], big.shape[0]), interpolation=cv2.INTER_LINEAR)
    out = (out.astype(np.float32) * 0.8).astype(np.uint8)
    out[P:P + SH, P:P + SW] = fr
    return out, P

# ------------------------------------------------------------------ main render
def words_for(cid, c, a2, b2):
    ws = [w for w in L.asr_words(c['src']) if w[0] >= c['a'] - 0.05 and w[1] <= c['b'] + 0.3]
    al = L.mono(caps.align(ws, c['text']))
    return [[max(0.0, x[0] - a2), min(b2 - a2, max(0.05, x[1] - a2)), x[2]] for x in al]

def render(cid):
    c = CL[cid]; od = f'{OUT}/{cid}'; os.makedirs(od, exist_ok=True)
    src = L.SRC[c['src']]
    a2, b2 = L.snap(c['src'], c['a'] - 0.1, 'start'), L.snap(c['src'], c['b'] + 0.15, 'end')
    d = b2 - a2
    # ---- voice
    va = L.piece_audio(od, 'v', c['src'], a2, b2)
    sh('cp', va, f'{od}/voice.wav')
    words = words_for(cid, c, a2, b2)
    json.dump(words, open(f'{od}/words.json', 'w'))
    st = c['style']; n = int(round(d * FPS))
    wm = render2.AnimWM(W, H, 96)
    nat = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', src], capture_output=True, text=True).stdout.split(',')
    SW, SH = int(nat[0]), int(nat[1]); pre = ''
    if SH > 1080: pre = 'scale=1920:1080:flags=lanczos,'; SW, SH = 1920, 1080
    crop = L.CROP.get(c['src'])
    if crop:
        crop = (crop[0] // 2 * 2, crop[1] // 2 * 2, crop[2] // 2 * 2, crop[3] // 2 * 2); SW, SH = crop[0], crop[1]
    # ---- frames source
    if st in ('bright', 'cinema'):
        xs, ys, ss, n_t = track(src, a2, d, crop, pre)
        if st == 'bright':
            cx, cy, s = lock_path(xs, ys, ss, n_t, SW, SH, W, H, 0.17, 0.36, H / SH * 1.22)
            band = None
        else:
            BH = 608; band = ((H - BH) // 2, BH)
            cx, cy, s = lock_path(xs, ys, ss, n_t, SW, SH, W, BH, 0.36, 0.40, W / SW * 1.45)
        vf = pre + (f'crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]},' if crop else '') + render2.CLARITY + ',' + GRADE[st] + f',fps={FPS}'
        dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f'{a2:.3f}', '-t', f'{d:.3f}', '-i', src, '-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE)
        fsz = SW * SH * 3
    else:
        # calm B-roll sequence, 9:16, slow push
        lib = [b for b in json.load(open('/home/claude/w/broll_lib.json')) if 50 < b['bright'] < 175 and b['motion'] < 5]
        rng = random.Random(hash(cid) & 0xffff); rng.shuffle(lib)
        shots = []; t = 0; i = 0
        while t < d + 0.5:
            L_ = min(9.0, d + 0.5 - t + 1.0); shots.append((lib[i % len(lib)], L_)); t += L_ - 1.0; i += 1
        parts = []
        for j, (bl, L_) in enumerate(shots):
            o = f'{od}/br{j}.mp4'; parts.append((o, L_))
            sh('ffmpeg', '-v', 'error', '-y', '-ss', f"{bl['t']:.2f}", '-t', f'{L_:.2f}', '-i', render2.BR[bl['src']],
               '-vf', f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{GRADE['text']},"
                      f"fps={FPS},setpts=PTS-STARTPTS",
               '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '14', o)
        # crossfade chain
        args = []; [args.extend(['-i', p]) for p, _ in parts]
        fc = []; last = '[0:v]'; acc = parts[0][1]
        for j in range(1, len(parts)):
            lab = '[o]' if j == len(parts) - 1 else f'[x{j}]'
            fc.append(f'{last}[{j}:v]xfade=transition=fade:duration=1.0:offset={acc - 1.0:.3f}{lab}'); last = lab; acc += parts[j][1] - 1.0
        if fc:
            sh('ffmpeg', '-v', 'error', '-y', *args, '-filter_complex', ';'.join(fc), '-map', '[o]', '-t', f'{d:.3f}', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '14', f'{od}/bg.mp4')
        else:
            sh('cp', parts[0][0], f'{od}/bg.mp4')
        dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', f'{od}/bg.mp4', '-t', f'{d:.3f}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE)
        fsz = W * H * 3
    # ---- captions
    U = caps.units(words, maxw=3 if st == 'bright' else 2)
    if st == 'bright': cap = BrightCaps(U, H * 0.50)
    elif st == 'cinema': cap = CinemaCaps(U, H * 0.50)
    else:
        flat = [w for u in U for w in u['words']]
        cap = TextLines(flat, c['credit'], H * 0.46)
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(OFPS), '-i', '-',
                            '-vf', 'unsharp=5:5:0.45:5:5:0,noise=c0s=13:c0f=t+u', '-c:v', 'libx264', '-profile:v', 'high', '-preset', 'veryfast', '-crf', '20',
                            '-maxrate', '12M', '-bufsize', '24M', '-pix_fmt', 'yuv420p', '-r', str(OFPS), '-video_track_timescale', '15360', f'{od}/{cid}.mp4'], stdin=subprocess.PIPE)
    shp = (SH, SW, 3) if st != 'text' else (H, W, 3)
    def readf():
        b = dec.stdout.read(fsz)
        return np.frombuffer(b, np.uint8).reshape(shp) if len(b) == fsz else None
    cur = readf()
    if cur is None: raise RuntimeError('no frames')
    nxt = readf()
    PT = Portrait() if st != 'text' else None
    if PT:
        m_cur = PT.next(cur); m_nxt = PT.next(nxt) if nxt is not None else m_cur
    if st != 'text':
        tt = np.arange(len(cx)) / FPS
    n_out = int(round(d * OFPS)); src_i = 0
    for k in range(n_out):
        t = k / OFPS
        while (src_i + 1) / FPS <= t + 1e-6 and nxt is not None:
            cur, nxt, src_i = nxt, readf(), src_i + 1
            if PT:
                m_cur = m_nxt; m_nxt = PT.next(nxt) if nxt is not None else m_cur
        frac = t * FPS - src_i
        if nxt is not None and frac > 0.25:
            if frac < 0.75: fr = midframe(cur, nxt); mk = (m_cur + m_nxt) / 2 if PT else None
            else: fr = nxt; mk = m_nxt if PT else None
        else:
            fr = cur; mk = m_cur if PT else None
        if PT: fr = portrait_fx(fr, mk)
        if st == 'bright':
            X = np.interp(t, tt, cx); Y = np.interp(t, tt, cy)
            fp, P = padded(fr)
            M = np.array([[s, 0, W / 2 - (X + P) * s], [0, s, H / 2 - (Y + P) * s]], np.float32)
            cv = cv2.warpAffine(fp, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
            cv = bloom(cv, 0.12) * VIG
        elif st == 'cinema':
            X = np.interp(t, tt, cx); Y = np.interp(t, tt, cy); y0, BH = band
            fp, P = padded(fr)
            M = np.array([[s, 0, W / 2 - (X + P) * s], [0, s, BH / 2 - (Y + P) * s]], np.float32)
            bandimg = cv2.warpAffine(fp, M, (W, BH), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
            byy = np.linspace(-1, 1, BH)[:, None, None]; bxx = np.linspace(-1, 1, W)[None, :, None]
            cv = np.zeros((H, W, 3), np.float32)
            cv[y0:y0 + BH] = bandimg * (1 - 0.28 * np.clip(np.sqrt(bxx ** 2 + byy ** 2) - 0.6, 0, 1))
        else:
            z = 1.02 + 0.06 * t / max(d, 1)
            Mz = np.array([[z, 0, W / 2 * (1 - z)], [0, z, H / 2 * (1 - z)]], np.float32)
            cv = cv2.warpAffine(fr, Mz, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT).astype(np.float32) * 0.62
            cv = bloom(cv, 0.25)
            cv = cv * VIG
        cap.draw(cv, t)
        wm.draw(cv, t, 0.85)
        enc.stdin.write(np.clip(cv, 0, 255).astype(np.uint8).tobytes())
    enc.stdin.close(); enc.wait(); dec.stdout.close(); dec.wait()
    print(cid, 'video', round(d, 1), 's', flush=True)
    return d

# ------------------------------------------------------------------ outro + audio
def finish(cid, d):
    sys.argv = ['outro.py']
    import outro, render as R
    R.MUS['m6'] = MUSIC; R.MUS_ENTRY['m6'] = [MUS_ENTRY]
    od = f'{OUT}/{cid}'; src = f'{od}/{cid}.mp4'
    cwd = os.getcwd(); os.chdir('/home/claude/w')
    try:
        frames = outro.build_outro(cid, src, W, H)
        enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', '30', '-i', '-',
                                '-vf', 'minterpolate=fps=60:mi_mode=blend',
                                '-c:v', 'libx264', '-profile:v', 'high', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', '60',
                                '-video_track_timescale', '15360', f'{od}/outro.mp4'], stdin=subprocess.PIPE)
        for f in frames: enc.stdin.write(f.tobytes())
        enc.stdin.close(); enc.wait()
        open(f'{od}/cat.txt', 'w').write(f"file '{cid}.mp4'\nfile 'outro.mp4'\n")
        nfr = int(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-count_packets', '-show_entries', 'stream=nb_read_packets', '-of', 'csv=p=0', src], capture_output=True, text=True).stdout)
        outro.remix(cid, {'music': 'm6', 'entry': MUS_ENTRY}, nfr / OFPS)
        sh('ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', f'{od}/cat.txt', '-i', f'{od}/final2.wav',
           '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest', '-movflags', '+faststart', f'{od}/{cid}_o.mp4')
    finally:
        os.chdir(cwd)
    print(cid, 'done', flush=True)

if __name__ == '__main__':
    for cid in sys.argv[1:]:
        if os.path.exists(f'{OUT}/{cid}/{cid}_o.mp4'): continue
        d = render(cid); finish(cid, d)

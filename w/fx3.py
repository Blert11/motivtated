"""Three new looks from the Nov 10 references.
  halal captions : small heavy UPPERCASE 1-2 words, one neon accent word with glow, digital glitch-in
  head lock      : frame pinned to the speaker's head (head stays fixed, world moves), eased in/out
  halal grade    : matte lifted blacks, teal shadows / warm highlights, soft bloom, crisp clarity,
                   vignette, fine animated grain, slight edge chromatic aberration
"""
import numpy as np, cv2, re
from PIL import Image, ImageDraw, ImageFont

F = '/home/claude/fonts/'
YN = None


# ---------------------------------------------------------------- face track (every frame)
def face_track(frames_iter, n, W, H):
    global YN
    if YN is None:
        YN = cv2.FaceDetectorYN.create('/home/claude/models/yunet.onnx', '', (640, 360), 0.55, 0.3, 5000)
    xs, ys, ss = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    prev = None
    for i, fr in enumerate(frames_iter):
        if i >= n: break
        sm = cv2.resize(fr, (640, 360)); _, r = YN.detect(sm)
        if r is None: continue
        det = sorted(r, key=lambda d: (abs(d[0] + d[2] / 2 - prev) / 80 if prev is not None else 0) - d[2] * d[-1] / 40)
        x, y, w, h = det[0][:4]; prev = x + w / 2
        k = W / 640.
        xs[i], ys[i], ss[i] = (x + w / 2) * k, (y + h * 0.48) * k, h * k
    for a in (xs, ys, ss):
        idx = np.arange(n); ok = ~np.isnan(a)
        a[:] = np.interp(idx, idx[ok], a[ok]) if ok.any() else (W / 2 if a is xs else H / 2)
    return xs, ys, ss


def smooth(a, sec, fps=30):
    k = max(1, int(sec * fps)) | 1
    pad = np.pad(a, k // 2, mode='edge')
    return np.convolve(pad, np.ones(k) / k, mode='valid')


def ease(v):
    v = np.clip(v, 0, 1); return v * v * (3 - 2 * v)


def lock_weight(n, windows, fps=30, ramp=0.35):
    w = np.zeros(n)
    for a, d in windows:
        t = np.arange(n) / fps
        w = np.maximum(w, ease((t - a) / ramp) * ease((a + d - t) / ramp))
    return w


def crop_params(xs, ys, ss, W, H, CW, CH, locks):
    """per-frame crop centre + height in source pixels."""
    n = len(xs)
    asp = CW / CH
    base_h = np.full(n, float(H)); base_cx = smooth(xs, 1.2); base_cy = np.full(n, H / 2.)
    # lock: centre exactly on the head (tiny 3-frame smoothing against detector jitter), zoom 1.35,
    # head placed at 42% height of the output
    lk_h = H / 1.35
    lk_cx = smooth(xs, 0.1); lk_cy = smooth(ys, 0.1) + lk_h * (0.5 - 0.42)
    w = lock_weight(n, locks)
    ch = base_h * (1 - w) + lk_h * w
    cx = base_cx * (1 - w) + lk_cx * w
    cy = base_cy * (1 - w) + lk_cy * w
    cw = ch * asp
    cx = np.clip(cx, cw / 2, W - cw / 2); cy = np.clip(cy, ch / 2, H - ch / 2)
    return cx, cy, ch, w


def crop(fr, cx, cy, ch, CW, CH):
    s = CH / ch
    M = np.array([[s, 0, CW / 2 - cx * s], [0, s, CH / 2 - cy * s]], np.float32)
    return cv2.warpAffine(fr, M, (CW, CH), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


# ---------------------------------------------------------------- grade
class HalalGrade:
    def __init__(self, CW, CH, seed=7, grain=0.022):
        self.grain = grain
        yy, xx = np.mgrid[0:CH, 0:CW].astype(np.float32)
        r = np.sqrt(((xx - CW / 2) / (CW / 2)) ** 2 + ((yy - CH / 2) / (CH / 2)) ** 2) / 1.414
        self.vig = (1 - 0.62 * np.clip(r - 0.25, 0, 1) ** 1.6 / 0.75 ** 1.6)[..., None].astype(np.float32)
        # chromatic aberration maps: red pushed out, blue pulled in, stronger at the edges
        k = 3.0 * (r ** 2)
        dx, dy = (xx - CW / 2) / (CW / 2), (yy - CH / 2) / (CH / 2)
        self.mr = (xx + dx * k).astype(np.float32), (yy + dy * k).astype(np.float32)
        self.mb = (xx - dx * k).astype(np.float32), (yy - dy * k).astype(np.float32)
        self.rng = np.random.default_rng(seed)
        self.CW, self.CH = CW, CH

    def __call__(self, img):
        x = img.astype(np.float32) / 255.
        x = np.clip(x * 0.86, 0, 1) ** 1.12                         # darker, moodier base exposure
        # gentle S-curve, then matte: lift blacks, roll off whites
        x = x + 0.30 * (x - 0.5) * (1 - np.abs(2 * x - 1))
        lum = x @ np.array([0.114, 0.587, 0.299], np.float32)
        lum = lum[..., None]
        x = lum + (x - lum) * 0.80                                   # slight desaturation
        sh = np.clip(1 - lum * 2.2, 0, 1); hi = np.clip(lum * 1.6 - 0.6, 0, 1)
        x += sh * np.array([0.030, 0.018, -0.012], np.float32)       # teal/cyan shadows (BGR)
        x += hi * np.array([-0.020, 0.004, 0.022], np.float32)       # warm highlights
        x = 0.040 + x * (0.92 - 0.040)                               # lifted blacks / soft whites
        x[..., 0] += 0.012 * (1 - lum[..., 0])                       # a touch of blue in the blacks
        # bloom on highlights
        b = np.clip(x - 0.62, 0, 1)
        b = cv2.GaussianBlur(b, (0, 0), 22)
        x = 1 - (1 - x) * (1 - 0.55 * b)
        x *= self.vig
        x = np.clip(x, 0, 1)
        # chromatic aberration at the edges
        out = x.copy()
        out[..., 2] = cv2.remap(x[..., 2], *self.mr, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        out[..., 0] = cv2.remap(x[..., 0], *self.mb, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        # fine animated grain (luma), slightly soft so it reads as film, not digital noise
        g = self.rng.standard_normal((self.CH // 2, self.CW // 2)).astype(np.float32)
        g = cv2.resize(g, (self.CW, self.CH), interpolation=cv2.INTER_LINEAR)
        out += (g * self.grain)[..., None]
        return np.clip(out * 255, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- captions
STOP = set('a an the and or but of to in on at for with is are was were be been it its i you he she we they me my your our his her their this that so do does did not no as if by from up out what when who how just there here then than'.split())
ACCENTS = [(255, 232, 69), (106, 255, 76)]   # BGR: cyan, neon green
AR = re.compile(r'[؀-ۿﷰ-﷿]+')


class HalalCaps:
    def __init__(self, units, CW, CH, size=50, cy=0.52, seed=3):
        self.u = units; self.CW, self.CH, self.size, self.cy = CW, CH, size, cy
        self.f = ImageFont.truetype(F + 'Montserrat-ExtraBold.ttf', size)
        self.fa = ImageFont.truetype(F + 'NotoNaskhArabic.ttf', int(size * 1.15))
        self.cache = {}; self.rng = np.random.default_rng(seed)

    def sprite(self, i):
        if i in self.cache: return self.cache[i]
        a, b, text = self.u[i]
        words = text.split()
        # accent: the strongest word (longest non-stop word); single-word units accent every other time
        cand = [k for k, w in enumerate(words) if re.sub(r'\W', '', w).lower() not in STOP and not AR.search(w)]
        acc = max(cand, key=lambda k: len(words[k])) if cand and (len(words) > 1 or i % 2 == 0) else -1
        col = ACCENTS[(i // 2) % 2]
        parts = []
        for k, w in enumerate(words):
            ar = AR.search(w) is not None
            t = w if ar else w.upper()
            font = self.fa if ar else self.f
            parts.append((t, font, col if k == acc else (255, 255, 255), k == acc))
        sp = self.size * 0.26
        ws = [p[1].getlength(p[0]) for p in parts]
        W = int(sum(ws) + sp * (len(parts) - 1) + 80); H = int(self.size * 2.6)
        fill = Image.new('RGBA', (W, H)); glow = Image.new('RGBA', (W, H))
        d, dg = ImageDraw.Draw(fill), ImageDraw.Draw(glow)
        x = 40
        for (t, font, c, is_acc), w in zip(parts, ws):
            y = H / 2 - self.size * (0.62 if font is self.f else 0.9)
            rgb = (c[2], c[1], c[0], 255)
            d.text((x, y), t, font=font, fill=rgb)
            if is_acc: dg.text((x, y), t, font=font, fill=rgb)
            x += w + sp
        f = np.asarray(fill).astype(np.float32) / 255.
        g = np.asarray(glow).astype(np.float32) / 255.
        sh = cv2.GaussianBlur(f[..., 3], (0, 0), 3.0) * 0.55
        gl = cv2.GaussianBlur(g, (0, 0), 9.0) * 1.6
        spr = (f[..., 2::-1].copy(), f[..., 3].copy(), sh, gl[..., 2::-1].copy(), gl[..., 3].copy())
        self.cache[i] = spr
        return spr

    def draw(self, img, t):
        idx = [i for i, (a, b, _) in enumerate(self.u) if a <= t < b + 0.02]
        if not idx: return img
        i = idx[-1]; a, b, _ = self.u[i]
        rgb, al, sh, grgb, gal = self.sprite(i)
        h, w = al.shape
        x0 = int(self.CW / 2 - w / 2); y0 = int(self.CH * self.cy - h / 2)
        age = t - a
        out = img.astype(np.float32) / 255.
        reg = out[y0:y0 + h, x0:x0 + w]
        # glitch-in for the first ~0.13 s: horizontal slice offsets, RGB split, flicker
        glitch = age < 0.075
        if glitch:
            rr = np.random.default_rng(int(t * 1000) + i)
            off = np.zeros(h, int)
            for _ in range(5):
                y = rr.integers(0, h); hh = rr.integers(3, max(4, h // 5))
                off[y:y + hh] = rr.integers(-28, 29)
            sl = lambda m: np.stack([np.roll(m[r], off[r], axis=0) for r in range(h)])
            al_g = sl(al); rgb_g = np.stack([sl(rgb[..., c]) for c in range(3)], -1)
            split = int(rr.integers(4, 9))
            rgb_g[..., 2] = np.roll(rgb_g[..., 2], -split, 1); rgb_g[..., 0] = np.roll(rgb_g[..., 0], split, 1)
            op = 0.55 + 0.45 * rr.random()
            al, rgb = al_g * op, rgb_g
            # a thin bright scan bar over the word like the reference
            bar = np.zeros_like(al); yb = rr.integers(h // 3, 2 * h // 3); bar[yb:yb + 3] = 0.6 * (al.max(0) > 0)[None, :]
            al = np.maximum(al, bar); rgb = np.where(bar[..., None] > al_g[..., None] * op, 1.0, rgb)
        # soft shadow, glow (screen), fill
        reg *= (1 - sh[..., None])
        reg[:] = 1 - (1 - reg) * (1 - np.clip(grgb * gal[..., None], 0, 1) * 0.9)
        reg[:] = reg * (1 - al[..., None]) + rgb * al[..., None]
        return np.clip(out * 255, 0, 255).astype(np.uint8)


class Grain:
    """Fine animated film grain for clips that don't use the full halal grade."""
    def __init__(self, W, H, amount=0.028, seed=5):
        self.W, self.H, self.a, self.rng = W, H, amount, np.random.default_rng(seed)
    def __call__(self, img):
        g = self.rng.standard_normal((self.H // 2, self.W // 2)).astype(np.float32)
        g = cv2.resize(g, (self.W, self.H), interpolation=cv2.INTER_LINEAR) * (255 * self.a)
        return np.clip(img.astype(np.float32) + g[..., None], 0, 255).astype(np.uint8)


class FastHalal:
    """Fast version: tone/colour is done by ffmpeg (GR['halal']); here only soft bloom at 1/4 res,
    vignette and a slight edge colour fringe. Grain is added by ffmpeg's noise filter at encode."""
    def __init__(self, W, H, **kw):
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 1.414
        self.vig = (1 - 0.62 * np.clip(r - 0.25, 0, 1) ** 1.6 / 0.75 ** 1.6).astype(np.float32)[..., None]
        self.edge = np.clip((r - 0.45) / 0.5, 0, 1).astype(np.float32)[..., None]
        self.W, self.H = W, H
    def __call__(self, img):
        x = img.astype(np.float32)
        sm = cv2.resize(img, (self.W // 4, self.H // 4), interpolation=cv2.INTER_AREA).astype(np.float32)
        b = np.clip(sm - 160, 0, 255)
        b = cv2.GaussianBlur(b, (0, 0), 6)
        b = cv2.resize(b, (self.W, self.H), interpolation=cv2.INTER_LINEAR) / 255.
        x = 255 - (255 - x) * (1 - 0.55 * b)
        # edge fringe: red out, blue in (2-3 px), only near the borders
        sh = np.empty_like(x); sh[..., 1] = x[..., 1]
        sh[..., 2] = np.roll(x[..., 2], 3, 1); sh[..., 0] = np.roll(x[..., 0], -3, 1)
        x = x * (1 - self.edge) + sh * self.edge
        x *= self.vig
        return np.clip(x, 0, 255).astype(np.uint8)

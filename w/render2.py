import re
"""Batch-2 renderer: kinetic titles, star particles, B-roll cutaways with whip transitions,
IM watermark, beat-entry music (via render.make_audio)."""
import json, os, sys, subprocess, math, re
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
import track
from track import track as get_track
import caps, kinetic
import render as R

U = '/mnt/user-data/uploads'
SRC = {
    'ay': U + '/Downloads/vidssave.com Akhi Ayman Powerful Speech _ BG _ Halal Beats, Where you are 720P.mp4',
    'ud': U + '/Downloads/vidssave.com No One Escapes the Grave - A Powerful Reminder for Every Soul ! The Muslim Undertaker 720P.mp4',
    'r0': U + '/imanivated/_work/rep_0.mp4',
    'r1': U + '/imanivated/_work/rep_1.mp4',
    'hr': U + '/Downloads/vidssave.com Horrors of this World _ Akhi Ayman _ BG _ Wonder Where you are 720P.mp4',
}
import json as _j, os as _o
if _o.path.exists('b3/src.json'):
    SRC.update(_j.load(open('b3/src.json')))
track.SRC.update(SRC)
BR = {'adhan': U + '/imanivated/B-Roll videos/2-hours-adhan-ezan-beautiful-muslim-call-to-prayer-with-mosques-around-the-world-ytmp4.savetube.vip.mp4',
      'mosq': U + '/imanivated/B-Roll videos/10-most-beautiful-mosques-in-the-world-ytmp4.savetube.vip.mp4'}
GR = dict(R.GRADES)
GR['halal'] = "eq=contrast=1.16:saturation=0.80:gamma=0.90:brightness=-0.035,colorbalance=rs=-0.04:gs=0.0:bs=0.06:rm=0.0:bm=0.01:rh=0.05:gh=0.015:bh=-0.04,curves=all='0/0.045 0.25/0.21 0.5/0.47 0.8/0.80 1/0.92'"
GR['orig'] = "eq=contrast=1.06:saturation=1.05:brightness=-0.01,curves=all='0/0 0.08/0.05 0.5/0.5 1/0.98',vignette=PI/6"
CLARITY = R.CLARITY
FONTS = R.FONTS

# ---------- watermark ----------
def watermark_layer(CW, CH, h=160, win=None):
    logo = Image.open(U + '/imanivated/Logo PNG White.png').convert('RGBA')
    lw = int(logo.width * h / logo.height); logo = logo.resize((lw, h), Image.LANCZOS)
    fs = max(12, int(24 * h / 160)); f = ImageFont.truetype('/home/claude/fonts/Montserrat-SemiBold.ttf', fs)
    text = '@imanivated'; ws = [f.getlength(c) for c in text]; sp = (lw - sum(ws)) / (len(text) - 1)
    asc, desc = f.getmetrics(); gap = int(26 * h / 160)
    L = Image.new('RGBA', (lw, h + gap + asc + desc), (0, 0, 0, 0)); L.paste(logo, (0, 0), logo)
    d = ImageDraw.Draw(L); x = 0
    for c, w in zip(text, ws): d.text((x, h + gap), c, font=f, fill=(255, 255, 255, 255)); x += w + sp
    a = np.asarray(L).astype(np.float32) / 255.
    top = int(CH * 0.84 - h / 2)
    if win is not None:
        wy0, wh = win
        top = min(top, int(wy0 + wh - (h + gap + asc + desc) - wh * 0.05))
    return a[..., 2::-1].copy(), a[..., 3:4].copy(), (CW - lw) // 2, top

def apply_wm(canvas, wm, op=0.85):
    rgb, al, x, y = wm
    H, W = rgb.shape[:2]
    B = canvas[y:y + H, x:x + W] / 255.
    ov = np.where(B < 0.5, 2 * B * rgb, 1 - 2 * (1 - B) * (1 - rgb))
    scr = 1 - (1 - B) * (1 - rgb * 0.55)
    top = ov * 0.6 + scr * 0.4  # overlay look, but stays visible on dark footage
    canvas[y:y + H, x:x + W] = (B * (1 - al * op) + top * al * op) * 255


# ---------- animated watermark ----------
class AnimWM:
    """icon alone -> icon slides left while @imanivated reveals to its right -> hold -> back. Loops."""
    def __init__(self, CW, CH, h=160, win=None, period=9.0):
        logo = Image.open(U + '/imanivated/Logo PNG White.png').convert('RGBA')
        lw = int(logo.width * h / logo.height); logo = logo.resize((lw, h), Image.LANCZOS)
        a = np.asarray(logo).astype(np.float32) / 255.
        self.icon = (a[..., 2::-1].copy(), a[..., 3:4].copy())
        fs = int(h * 0.30); f = ImageFont.truetype('/home/claude/fonts/Montserrat-SemiBold.ttf', fs)
        text = '@IMANIVATED'; sp = fs * 0.22
        ws = [f.getlength(c) for c in text]; tw = int(sum(ws) + sp * (len(text) - 1)) + 4
        asc, desc = f.getmetrics()
        T = Image.new('RGBA', (tw, asc + desc + 4), (0, 0, 0, 0)); d = ImageDraw.Draw(T); x = 0
        for c, w in zip(text, ws): d.text((x, 2), c, font=f, fill=(255, 255, 255, 255)); x += w + sp
        t = np.asarray(T).astype(np.float32) / 255.
        self.text = (t[..., 2::-1].copy(), t[..., 3:4].copy())
        self.lw, self.h, self.tw, self.th = lw, h, tw, t.shape[0]
        self.gap = int(h * 0.22)
        total = lw + self.gap + tw
        self.cx = CW // 2
        self.shift = (total - lw) / 2       # how far the icon moves left
        top = int(CH * 0.84 - h / 2)
        if win is not None:
            wy0, wh = win
            top = min(top, int(wy0 + wh - h - wh * 0.05))
        self.top = top
        self.period = period
    @staticmethod
    def blend(canvas, rgb, al, x, y, op):
        H, W = rgb.shape[:2]; CH, CW = canvas.shape[:2]
        xs, ys, xe, ye = max(0, x), max(0, y), min(CW, x + W), min(CH, y + H)
        if xe <= xs or ye <= ys: return
        rgb = rgb[ys - y:ye - y, xs - x:xe - x]; al = al[ys - y:ye - y, xs - x:xe - x]
        B = canvas[ys:ye, xs:xe] / 255.
        ov = np.where(B < 0.5, 2 * B * rgb, 1 - 2 * (1 - B) * (1 - rgb))
        scr = 1 - (1 - B) * (1 - rgb * 0.55)
        top = ov * 0.6 + scr * 0.4
        canvas[ys:ye, xs:xe] = (B * (1 - al * op) + top * al * op) * 255
    def draw(self, canvas, T, op=0.85):
        ph = T % self.period
        # 0-3.2 icon only | 3.2-4.0 slide+reveal | 4.0-7.6 hold | 7.6-8.4 hide+slide back | 8.4-9 icon only
        def sm(v): v = min(1, max(0, v)); return v * v * (3 - 2 * v)
        if ph < 3.2: k = 0
        elif ph < 4.0: k = sm((ph - 3.2) / 0.8)
        elif ph < 7.6: k = 1
        elif ph < 8.4: k = 1 - sm((ph - 7.6) / 0.8)
        else: k = 0
        ix = int(round(self.cx - self.lw / 2 - self.shift * k))
        self.blend(canvas, *self.icon, ix, self.top, op)
        if k > 0.01:
            rgb, al = self.text
            tx = ix + self.lw + self.gap
            ty = int(self.top + self.h / 2 - self.th / 2)
            # wipe reveal from the left + fade
            vis = int(self.tw * k)
            if vis > 2:
                a2 = al[:, :vis] * k
                self.blend(canvas, rgb[:, :vis], a2, tx + int((1 - k) * -20), ty, op)

# ---------- stars ----------
def star_sprite(r):
    s = int(r * 8) | 1; c = s // 2
    yy, xx = (np.mgrid[0:s, 0:s] - c).astype(np.float32); d = np.sqrt(xx ** 2 + yy ** 2) + 1e-3
    core = np.exp(-(d / (r * 0.55)) ** 2)
    spikes = np.exp(-(np.abs(yy) / (r * 0.12)) ** 2) * np.exp(-np.abs(xx) / (r * 3.2)) + np.exp(-(np.abs(xx) / (r * 0.12)) ** 2) * np.exp(-np.abs(yy) / (r * 3.2))
    glow = np.exp(-(d / (r * 1.8)) ** 2) * 0.35
    return np.clip(core + spikes * 0.9 + glow, 0, 1)

def dot_sprite(r):
    s = int(r * 5) | 1; c = s // 2
    yy, xx = (np.mgrid[0:s, 0:s] - c).astype(np.float32); d = np.sqrt(xx ** 2 + yy ** 2)
    return np.clip(np.exp(-(d / (r * 0.8)) ** 2), 0, 1)

class Stars:
    def __init__(self, CW, CH, region, seed, n_star=45, n_dust=160):
        rng = np.random.default_rng(seed)
        x0, y0, w, h = region
        self.items = []
        for _ in range(n_star):
            r = rng.uniform(3, 7)
            self.items.append(dict(sp=star_sprite(r) * rng.uniform(0.5, 0.7), x=rng.uniform(x0, x0 + w), y=rng.uniform(y0, y0 + h),
                                   f=rng.uniform(0.6, 1.6), ph=rng.uniform(0, 6.28), vy=rng.uniform(-22, -6), vx=rng.uniform(-6, 6)))
        for _ in range(n_dust):
            r = rng.uniform(1.0, 2.0)
            self.items.append(dict(sp=dot_sprite(r) * rng.uniform(0.3, 0.55), x=rng.uniform(x0, x0 + w), y=rng.uniform(y0, y0 + h),
                                   f=rng.uniform(0.3, 1.0), ph=rng.uniform(0, 6.28), vy=rng.uniform(-30, -10), vx=rng.uniform(-10, 10)))
        self.region = region
        self.col = np.array((185, 228, 255), np.float32) / 255.  # BGR warm white

    def draw(self, canvas, t_local, env):
        x0, y0, w, h = self.region
        H, W = canvas.shape[:2]
        for it in self.items:
            a = env * (0.55 + 0.45 * math.sin(it['f'] * 6.283 * t_local + it['ph']))
            if a < 0.02: continue
            sp = it['sp']; s = sp.shape[0]
            cx = x0 + (it['x'] - x0 + it['vx'] * t_local) % w; cy = y0 + (it['y'] - y0 + it['vy'] * t_local) % h
            xa, ya = int(cx - s // 2), int(cy - s // 2)
            xs, ys, xe, ye = max(0, xa), max(0, ya), min(W, xa + s), min(H, ya + s)
            if xe <= xs or ye <= ys: continue
            A = sp[ys - ya:ye - ya, xs - xa:xe - xa, None] * a
            reg = canvas[ys:ye, xs:xe]
            canvas[ys:ye, xs:xe] = 255 - (255 - reg) * (1 - A * self.col)

# ---------- b-roll ----------
class BrollReader:
    def __init__(self, src, t, dur, grade, W=1280, H=720):
        vf = f"scale=1280:720:flags=lanczos,{CLARITY},{GR[grade]},fps=30"
        self.p = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f'{t:.2f}', '-t', f'{dur + 0.5:.2f}', '-i', BR[src], '-vf', vf,
                                   '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE)
        self.last = None
    def read(self):
        b = self.p.stdout.read(1280 * 720 * 3)
        if len(b) == 1280 * 720 * 3:
            self.last = np.frombuffer(b, np.uint8).reshape(720, 1280, 3)
        return self.last
    def close(self):
        try: self.p.stdout.close(); self.p.kill()
        except Exception: pass

def whip(img, strength, direction):
    """horizontal motion blur + shift"""
    if strength <= 0.01: return img
    k = int(3 + strength * 90) | 1
    ker = np.zeros((1, k), np.float32); ker[0, :] = 1.0 / k
    out = cv2.filter2D(img, -1, ker)
    sh = int(direction * strength * img.shape[1] * 0.18)
    return np.roll(out, sh, axis=1)

# ---------- main ----------
def render(cid, cfg):
    pieces = cfg['pieces']
    vertical = cfg['frame'] != 'comp'
    CW, CH = (1080, 1920) if vertical else (1440, 1080)
    od = f'out/{cid}'; os.makedirs(od, exist_ok=True)
    dur = sum(b - a for _, a, b in pieces); fps = 30; n_total = int(round(dur * fps))
    words = cfg['words']
    style = cfg['style']
    # captions
    timeline = None
    hcap = None
    if style == 'halal':
        import fx3
        Uh = caps.units([[a, b, w] for a, b, w in words], maxw=2)
        hun = []
        for k_, u in enumerate(Uh):
            t1_ = Uh[k_ + 1]['t0'] if k_ + 1 < len(Uh) and Uh[k_ + 1]['t0'] - u['t1'] < 0.6 else u['t1'] + 0.25
            parts = []
            for wd in u['words']:
                tt = wd['text'] if wd['text'].endswith('SWT.') else re.sub(r'[.,;:!?]+$', '', wd['text'])
                parts.append(tt + (' ' + wd['ar'] if wd.get('ar') else ''))
            hun.append((u['t0'], t1_, ' '.join(parts)))
        open(f'{od}/caps.ass', 'w').write('')
        sub = None
    if style == 'halal':
        pass
    elif style in ('kinetic', 'stoic', 'tinykin'):
        Uu = caps.units([[a, b, w] for a, b, w in words], maxw=4 if style == 'kinetic' else 3)
        _fw = 1080 if cfg['frame'] == 'sq' else R.layout(cfg['frame'], CW, CH)[0]
        timeline = kinetic.build(Uu, CW, CH, scale=1.0 if vertical else 0.8, seed=abs(hash(cid)) % 1000, maxw=min(900 if vertical else 1150, _fw - 110),
                                 mode='stoic' if style == 'stoic' else 'kinetic')
        open(f'{od}/caps.ass', 'w').write('')
        sub = None
    else:
        stl = caps.STYLES[style]
        Uu = caps.units([[a, b, w] for a, b, w in words], maxw=stl['n'], phrase=stl.get('phrase', False))
        caps.build_ass(Uu, stl, CW, CH, accent=cfg.get('accent', '&H002B8AFF&'), path=f'{od}/caps.ass')
        sub = f"subtitles={od}/caps.ass:fontsdir={FONTS}"
    zt = cfg.get('zooms') if cfg.get('zooms') is not None else R.pick_zooms(words, dur, 3 if dur > 40 else 2)
    Z = R.zoom_curve(zt, n_total + 5, amt=cfg.get('zamt', 0.08))
    if cfg['frame'] == 'sq':
        fw, fh, mask = 1080, 1080, None
    else:
        fw, fh, mask = R.layout(cfg['frame'], CW, CH)
    x0, y0 = (CW - fw) // 2, (CH - fh) // 2
    fish = R.fisheye_maps(fw) if cfg['frame'] == 'fish' else None
    wm = AnimWM(CW, CH, 96 if vertical else 68, win=(y0, fh))
    if style == 'halal':
        hcap = fx3.HalalCaps(hun, CW, CH, size=50 if vertical else 44, cy=(y0 + fh * 0.52) / CH, seed=abs(hash(cid)) % 1000)
    hg = None
    if cfg['grade'] == 'halal':
        import fx3
        hg = fx3.FastHalal(fw, fh)
    locks = cfg.get('locks', [])
    lockw = None
    if locks:
        import fx3
        lockw = fx3.lock_weight(n_total + 5, locks)
        YNl = cv2.FaceDetectorYN.create('/home/claude/models/yunet.onnx', '', (640, 360), 0.55, 0.3, 5000)
        lk_prev = [None, None]
    # stars windows
    rng = np.random.default_rng(abs(hash(cid + 'st')) % 2**32)
    st_windows = cfg.get('stars', [])
    stars = [Stars(CW, CH, (x0, y0, fw, fh), int(rng.integers(1e9))) for _ in st_windows]
    # b-roll windows: list of [t_clip, dur, src, src_t]
    brs = cfg.get('broll', [])
    # encoder
    sharpen = ("unsharp=5:5:0.8:5:5:0,noise=c0s=15:c0f=t+u" if cfg['grade'] == 'halal'
               else "unsharp=5:5:0.5:5:5:0,noise=c0s=10:c0f=t+u")   # film grain on every clip (more noise, Nov 11)
    if style == 'overlayword':
        fc = (f"[0:v]{sharpen},format=gbrp[b];color=c=black:s={CW}x{CH}:r=30:d={dur + 1:.2f},format=rgb24,{sub},rgbashift=rh=-4:bh=4:edge=smear,format=gbrp[t];"
              f"[b][t]blend=all_mode=difference:all_opacity=0.92,format=yuv420p[v]")
    elif sub:
        fc = f"[0:v]{sharpen},{sub},format=yuv420p[v]"
    else:
        fc = f"[0:v]{sharpen},format=yuv420p[v]"
    outp = f'{od}/{cid}.mp4'
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{CW}x{CH}', '-r', '30', '-i', '-',
                            '-i', f'{od}/final.wav', '-filter_complex', fc, '-map', '[v]', '-map', '1:a',
                            '-c:v', 'libx264', '-profile:v', 'high', '-preset', 'veryfast', '-crf', '21', '-maxrate', '8M', '-bufsize', '16M', '-pix_fmt', 'yuv420p', '-r', '30',
                            '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', '-t', f'{dur:.3f}', outp], stdin=subprocess.PIPE)
    lmask = np.zeros((CH, CW, 1), np.float32); lmask[y0:y0 + fh, x0:x0 + fw] = mask if mask is not None else 1
    asp = fw / fh
    cut_times = []
    for (t, d, *_ ) in brs: cut_times += [t, t + d]
    active_br = {}
    fi = 0; out = None
    SW, SH = 1280, 720
    def crop_to(img, cx, cy, z, base_h=None):
        bh = base_h or (SH if asp < 1.25 else min(SH, SW / asp))
        ch_ = bh / z; cw_ = ch_ * asp
        if cw_ > SW: cw_ = SW; ch_ = cw_ / asp
        cx = np.clip(cx, cw_ / 2, SW - cw_ / 2); cy = np.clip(cy, ch_ / 2, SH - ch_ / 2)
        s = fw / cw_
        M = np.array([[s, 0, -(cx - cw_ / 2) * s], [0, s, -(cy - ch_ / 2) * s]], np.float32)
        return cv2.warpAffine(img, M, (fw, fh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    for (src, a, b) in pieces:
        tr = get_track(src, a, b)
        tx, ty = np.array(tr['x']), np.array(tr['y'])
        vf = ['scale=1280:720:flags=lanczos', 'eq=gamma=0.97:brightness=-0.01', CLARITY, GR[cfg['grade']], 'fps=30']
        dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f'{a:.3f}', '-t', f'{b - a:.3f}', '-i', SRC[src], '-vf', ','.join(vf),
                                '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE)
        np_ = int(round((b - a) * fps)); k = 0
        while k < np_:
            buf = dec.stdout.read(SW * SH * 3)
            if len(buf) < SW * SH * 3: break
            img = np.frombuffer(buf, np.uint8).reshape(SH, SW, 3)
            t = k / fps; T = fi / fps
            z = Z[min(fi, len(Z) - 1)]
            # b-roll?
            brw = next((w for w in brs if w[0] <= T < w[0] + w[1]), None)
            if brw is not None:
                key = id(brw)
                if key not in active_br:
                    active_br[key] = BrollReader(brw[2], brw[3], brw[1], cfg['grade'])
                bimg = active_br[key].read()
                pz = 1.04 + 0.06 * (T - brw[0]) / brw[1]  # slow push-in
                content = crop_to(bimg, SW / 2, SH / 2, pz)
            else:
                for kk in list(active_br): active_br[kk].close(); del active_br[kk]
                ti = min(t * tr['fps'], len(tx) - 1); i0 = int(ti); fr = ti - i0; i1 = min(i0 + 1, len(tx) - 1)
                fxc = tx[i0] * (1 - fr) + tx[i1] * fr; fyc = ty[i0] * (1 - fr) + ty[i1] * fr
                ch_ = (SH if asp < 1.25 else min(SH, SW / asp)) / z
                fy_t = 0.36 if asp < 0.8 else 0.42
                lw_ = float(lockw[min(fi, len(lockw) - 1)]) if lockw is not None else 0.0
                if lw_ > 0.001:
                    # head lock: detect the head on this very frame and pin it (tiny smoothing vs jitter)
                    _, rr = YNl.detect(cv2.resize(img, (640, 360)))
                    if rr is not None:
                        dd = min(rr, key=lambda d: abs(d[0] + d[2] / 2 - fxc / 2) - d[2] * d[-1] / 4)
                        hx, hy = (dd[0] + dd[2] / 2) * 2, (dd[1] + dd[3] * 0.48) * 2
                        if lk_prev[0] is not None:
                            hx, hy = 0.55 * hx + 0.45 * lk_prev[0], 0.55 * hy + 0.45 * lk_prev[1]
                        lk_prev[:] = [hx, hy]
                    else:
                        hx, hy = lk_prev if lk_prev[0] is not None else (fxc, fyc)
                    zl = z * (1 + 0.35 * lw_)
                    chl = (SH if asp < 1.25 else min(SH, SW / asp)) / zl
                    lx = fxc * (1 - lw_) + hx * lw_
                    ly = (fyc + ch_ * (0.5 - fy_t)) * (1 - lw_) + (hy + chl * (0.5 - 0.42)) * lw_
                    content = crop_to(img, lx, ly, zl)
                else:
                    if lockw is not None: lk_prev[:] = [None, None]
                    content = crop_to(img, fxc, fyc + ch_ * (0.5 - fy_t), z)
            # opening zoom-out with blur
            if T < 0.5:
                p = T / 0.5; e = 1 - (1 - p) ** 3
                sc = 1.25 - 0.25 * e
                M = cv2.getRotationMatrix2D((fw / 2, fh / 2), 0, sc)
                content = cv2.warpAffine(content, M, (fw, fh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                bl = (1 - e) * 9
                if bl > 0.5: content = cv2.GaussianBlur(content, (0, 0), bl)
            # whip around cuts
            for ct in cut_times:
                dt = T - ct
                if abs(dt) < 0.13:
                    strength = 1 - abs(dt) / 0.13
                    content = whip(content, strength, 1 if dt < 0 else -1)
            if fish is not None:
                content = cv2.remap(content, fish[0], fish[1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            if hg is not None:
                content = hg(content)
            canvas = np.zeros((CH, CW, 3), np.float32)
            c = content.astype(np.float32)
            if mask is not None: c = c * mask
            canvas[y0:y0 + fh, x0:x0 + fw] = c
            # stars
            for (wt0, wd), S in zip(st_windows, stars):
                if wt0 <= T <= wt0 + wd:
                    tl = T - wt0; env = min(1, tl / 0.8, (wd - tl) / 0.8)
                    S.draw(canvas, tl, max(0, env))
            if timeline is not None:
                kinetic.render(canvas, timeline, T)
            if hcap is not None:
                canvas = hcap.draw(np.clip(canvas, 0, 255).astype(np.uint8), T).astype(np.float32)
            wm.draw(canvas, T)
            out = np.clip(canvas, 0, 255).astype(np.uint8)
            enc.stdin.write(out.tobytes())
            k += 1; fi += 1
        dec.stdout.close(); dec.wait()
    while fi < n_total and out is not None:
        enc.stdin.write(out.tobytes()); fi += 1
    for kk in list(active_br): active_br[kk].close()
    enc.stdin.close(); enc.wait()
    return outp

def plan_broll(words, dur, cands, rng, n=None, min_gap=8.0):
    """place 2-3 b-roll cutaways (2.2-3s) starting at sentence starts, after >=6s of speaker"""
    n = n or (3 if dur > 45 else 2)
    starts = [w[0] for i, w in enumerate(words) if i > 0 and words[i - 1][2][-1:] in '.!?' and 6 < w[0] < dur - 5]
    out = []; last = 0
    for s in starts:
        if s - last >= min_gap and len(out) < n:
            d = float(rng.uniform(2.2, 3.0))
            c = cands[int(rng.integers(len(cands)))]
            out.append([round(s - 0.05, 2), round(d, 2), c['src'], c['t'] + 0.2]); last = s + d
    return out

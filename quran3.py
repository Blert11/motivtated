"""Quran v2, @chahr_205 style: very dark cozy photos with slow motion, small centred Arabic + English, no names.
Formats: full 9:16, 9:16 with 3:4 window, 9:16 with square window, 16:9."""
import json, sys, os, subprocess, math
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quran import text_img, blit, ease, ayah, OUT, FPS

IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'img/bg_{:02d}.jpg')
CUSTOM = {}
SHADE = {}
FORMATS = {'full': (1080, 1920, None), 'rect': (1080, 1920, (960, 1280)), 'square': (1080, 1920, (960, 960)), 'wide': (1920, 1080, None)}

def dark_grade(img):
    x = img.astype(np.float32) / 255.
    x = x ** 1.15 * 0.80                      # low key, lighter (v3)
    g = x.mean(2, keepdims=True); x = g + (x - g) * 0.9
    x[..., 2] *= 1.04; x[..., 0] *= 0.95       # a touch warm
    h, w = x.shape[:2]; yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = ((xx - w / 2) / (w * 0.6)) ** 2 + ((yy - h / 2) / (h * 0.6)) ** 2
    x *= np.clip(1 - 0.45 * r, 0.35, 1)[..., None]
    return np.clip(x * 255, 0, 255).astype(np.uint8)

class Still:
    """an image prepared at cover size (with 14% headroom) for one output size; Ken Burns per shot."""
    _c = {}
    def __init__(self, path, W, H, seed):
        k = (path, W, H)
        if k not in Still._c:
            im = cv2.imread(path); h, w = im.shape[:2]
            s = max(W / w, H / h) * 1.14
            Still._c[k] = dark_grade(cv2.resize(im, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA))
        self.im = Still._c[k]
        r = np.random.default_rng(seed)
        self.mode = r.integers(0, 4)           # zoom in, zoom out, pan left, pan right
        self.W, self.H = W, H
    def frame(self, u):
        u = ease(u) * 0.85 + u * 0.15
        ih, iw = self.im.shape[:2]; W, H = self.W, self.H
        base = max(W / iw, H / ih)
        if self.mode == 0: z, px = 1.0 + 0.10 * u, 0.5
        elif self.mode == 1: z, px = 1.10 - 0.10 * u, 0.5
        elif self.mode == 2: z, px = 1.04, 0.62 - 0.24 * u
        else: z, px = 1.04, 0.38 + 0.24 * u
        s = base * z * (1 / 1.0)
        cw, ch = W / s, H / s
        x0 = (iw - cw) * px; y0 = (ih - ch) * 0.5
        M = np.array([[s, 0, -x0 * s], [0, s, -y0 * s]], np.float32)
        return cv2.warpAffine(self.im, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

def round_mask(w, h, r):
    m = np.zeros((h, w), np.float32); cv2.rectangle(m, (r, 0), (w - r, h), 1, -1); cv2.rectangle(m, (0, r), (w, h - r), 1, -1)
    for cx, cy in [(r, r), (w - r, r), (r, h - r), (w - r, h - r)]: cv2.circle(m, (cx, cy), r, 1, -1, cv2.LINE_AA)
    return cv2.GaussianBlur(m, (0, 0), 0.8)[..., None]

def render(job):
    s = job['surah']; a0, a1 = job['start'], job['end']; dur = a1 - a0
    CUSTOM.update({k: tuple(v) for k, v in job.get('custom', {}).items()})
    segs = [x for x in job['segs'] if x[1] - a0 < dur - 0.5]
    disp = []
    for k, (v, s0, s1) in enumerate(segs):
        st = max(0.0, s0 - a0 - 0.35); en = (segs[k + 1][1] - a0 - 0.35) if k + 1 < len(segs) else dur
        disp.append((v, st, en))
    wav = f"{OUT}/{job['name']}.wav"
    if not os.path.exists(wav): subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(a0), '-t', str(dur), '-i', job['audio'], '-ac', '2', '-ar', '48000',
                    '-af', f'afade=t=in:d=0.3,afade=t=out:st={dur - 1.5}:d=1.5,loudnorm=I=-14:TP=-1.5:LRA=11', wav], check=True)
    fmts = job.get('formats') or ['full', 'wide']
    encs, stills, masks = {}, {}, {}
    for fmt in fmts:
        W, H, win = FORMATS[fmt]
        PART = job.get('part')
        if PART:
            encs[fmt] = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                                          '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '17', '-maxrate', '8M', '-bufsize', '16M', '-pix_fmt', 'yuv420p',
                                          f"{OUT}/parts/{job['name']}_{fmt}_{PART[0]:04d}.tmp.mp4"], stdin=subprocess.PIPE)
        else:
          encs[fmt] = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                                      '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '17',
                                      '-maxrate', '8M', '-bufsize', '16M', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest',
                                      '-movflags', '+faststart', f"{OUT}/{job['name']}_{fmt}.mp4"], stdin=subprocess.PIPE)
        size = win or (W, H)
        stills[fmt] = [Still(IMG.format(i), size[0], size[1], k) for k, i in enumerate(job['images'][:len(disp)])]
        if win:
            masks[fmt] = round_mask(win[0], win[1], 26)
    rng = np.random.default_rng(1)
    gsrc = [rng.normal(0, 1, (480, 270)).astype(np.float32) for _ in range(6)]
    grains = {}
    for fmt in fmts:
        W, H, _ = FORMATS[fmt]; gl = []
        for g0 in gsrc:
            g = cv2.resize(g0, (W, H), interpolation=cv2.INTER_NEAREST) * 4.0
            gl.append((np.clip(g, 0, 255).astype(np.uint8)[..., None].repeat(3, 2), np.clip(-g, 0, 255).astype(np.uint8)[..., None].repeat(3, 2)))
        grains[fmt] = gl
    XF = 0.9
    f0, f1 = (int(job['part'][0] * FPS), min(int(dur * FPS), int(job['part'][1] * FPS))) if job.get('part') else (0, int(dur * FPS))
    for fi in range(f0, f1):
        t = fi / FPS
        cur = None
        for v, st, en in disp:
            if st <= t < en: cur = (v, st, en)
        for fmt, enc in encs.items():
            W, H, win = FORMATS[fmt]
            sw, sh = win or (W, H)
            img = None
            for k, (v, st, en) in enumerate(disp):
                if st - 0.001 <= t < en + XF:
                    u = (t - st) / (en - st + XF)
                    fr = stills[fmt][k].frame(min(1, max(0, u)))
                    a = 1.0 if (img is None or k == 0) else ease((t - st) / XF)
                    img = fr if img is None else cv2.addWeighted(img, 1 - a, fr, a, 0)
            if win:
                bg = cv2.GaussianBlur(cv2.resize(img, (W // 6, H // 6)), (0, 0), 4)
                cv = cv2.resize(bg, (W, H)).astype(np.float32) * 0.42
                x0, y0 = (W - sw) // 2, (H - sh) // 2
                m = masks[fmt]
                cv[y0:y0 + sh, x0:x0 + sw] = cv[y0:y0 + sh, x0:x0 + sw] * (1 - m) + img.astype(np.float32) * m
            else:
                cv = img
            wide = W > H
            if cur:
                v, st, en = cur
                ar, en_t = CUSTOM[v] if v in CUSTOM else ayah(s, v)
                fin = ease((t - st) / 0.7)
                fout = 1 - ease((t - (en - 0.35)) / 0.35) if v != disp[-1][0] else 1.0
                op = fin * fout
                maxw = 1300 if wide else (820 if win else 880)
                ai = text_img(ar, 'Amiri-Bold.ttf', 54 if wide else 50, (250, 248, 242), shadow=0.8, maxw=maxw)
                ei = text_img(en_t, 'MonaSans-Medium.otf', 27 if wide else 26, (205, 200, 190), line=1.4, shadow=0.8, maxw=maxw - 80)
                hi = text_img('imanivated', 'Cormorant-MediumItalic.ttf', 26, (170, 165, 155), shadow=0.6)
                ha, he = ai[0].shape[0], ei[0].shape[0]; gap = -30
                tot = ha + he + gap; cy = H / 2; y0 = cy - tot / 2
                lift = 10 * (1 - fin)
                ry0, ry1 = int(max(0, y0 - 60)), int(min(H, y0 + tot + 80))
                if cv is img: cv = img.copy()
                reg = cv[ry0:ry1].astype(np.float32)
                key = (W, ry1 - ry0)
                if key not in SHADE:
                    hh = ry1 - ry0; yy_, xx_ = np.mgrid[0:hh, 0:W].astype(np.float32)
                    sh = np.exp(-((yy_ - hh / 2) / (hh * 0.45)) ** 4) * np.exp(-((xx_ - W / 2) / (W * (0.42 if W > H else 0.55))) ** 4)
                    SHADE[key] = (1 - 0.42 * sh)[..., None]
                reg *= SHADE[key] ** op
                blit(reg, ai, W / 2, y0 + ha / 2 + lift - ry0, op)
                blit(reg, ei, W / 2, y0 + ha + gap + he / 2 + lift - ry0, op * 0.92)
                blit(reg, hi, W / 2, y0 + tot + 20 - ry0, op * 0.7)
                cv[ry0:ry1] = np.clip(reg, 0, 255).astype(np.uint8)
            gp, gn = grains[fmt][(fi // 2) % 6]
            cv = cv2.subtract(cv2.add(cv, gp), gn)
            fb = ease(t / 0.8) * (1 - ease((t - (dur - 1.2)) / 1.2))
            if fb < 1: cv = cv2.convertScaleAbs(cv, alpha=fb)
            enc.stdin.write(cv.tobytes())
        if fi % 600 == 0: print(f'{t:.0f}s', flush=True)
    for enc in encs.values():
        enc.stdin.close(); enc.wait()
    if job.get('part'):
        for fmt in encs:
            p = f"{OUT}/parts/{job['name']}_{fmt}_{job['part'][0]:04d}"
            os.replace(p + '.tmp.mp4', p + '.mp4')

if __name__ == '__main__':
    job = json.load(open(sys.argv[1]))
    if len(sys.argv) > 2: job['formats'] = sys.argv[2].split(',')
    if len(sys.argv) > 3: job['end'] = job['start'] + float(sys.argv[3])
    render(job); print('done')

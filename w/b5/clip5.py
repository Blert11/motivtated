"""Batch 5 @imanivated clips (Nov 21 references) on top of the batch-4 engine (head lock, 60 fps, enhance, outro, music).
New styles (Nov 21 Instagram refs), all captions fixed in the centre:
  clean   : full 9:16 head lock, natural colour, Inter SemiBold lowercase 2-3 words, now and then a yellow phrase
  typecap : 1:1 rounded window on black, heavy UPPERCASE typed letter by letter, next letters grey
  gold    : rounded 3:4 window on black, dark warm/purple grade, ONE word wide UPPERCASE in cream-gold + glow, dust
  mixed   : rounded landscape window on black, warm amber grade, dust; stacked mixed type
            (small spaced caps line / big bold yellow word / thin underlined word, gold serif lines between)
  film    : B&W heavy grain 4:3 band, small bold UPPERCASE grey->white, second line bold italic, "follow for more"
  serif   : full 9:16 natural, Playfair Display Bold lowercase 2-3 words (his "good font")
  hbox    : full 9:16, Poppins SemiBold lowercase, keyword in a red rounded box
  bracket : B&W high contrast + dot grid, one bold word at a time, sometimes [in brackets] or "in quotes", name tag
Batch-4 standards kept in the rotation: bright, cinema (from clip4_v3).
usage: python3 clip5.py CID [CID...]
"""
import sys, os, json, re, subprocess, math, random
import numpy as np, cv2
sys.path.insert(0, '/home/claude/w'); sys.path.insert(0, '/home/claude/w/long1'); sys.path.insert(0, '/home/claude/w/b4')
import caps, render2, fx3
import longvid as L
import clip4_v3 as C4
from PIL import Image, ImageDraw, ImageFont

B5 = '/home/claude/w/b5'
OUT = os.environ.get('B5_OUT', '/home/claude/w/out')
C4.OUT = OUT
W, H, FPS, OFPS = C4.W, C4.H, C4.FPS, C4.OFPS
FD = '/home/claude/fonts/'
CL = json.load(open(f'{B5}/clips.json'))
SRCS = json.load(open(f'{B5}/sources.json'))
for k, v in SRCS.items():
    L.SRC[k] = os.environ.get('B5_SRC_DIR', '/mnt/user-data/uploads/Downloads') + '/' + v['file']
    L.ASR[k] = f'b5/asr/{k}.json'
    L.NOSEP.add(k)
caps.SACRED.append((r"^musa('s)?$", ["alayhi", "alaihi", "salam", "as-salam", "assalam", "salatu", "wasalam", "wassalam"], 'Musa{p} AS', 'موسى'))
caps.SACRED.append((r"^yusuf('s)?$", ["alayhi", "alaihi", "salam", "as-salam", "assalam"], 'Yusuf{p} AS', 'يوسف'))
caps.SACRED.append((r"^isa('s)?$", ["alayhi", "alaihi", "salam", "as-salam", "assalam"], 'Isa{p} AS', 'عيسى'))
run_img, over, keyword = C4.run_img, C4.over, C4.keyword
F = lambda n: FD + n
YEL = (255, 214, 64); RED = (226, 38, 44); GOLD1 = (255, 236, 190); GOLD2 = (222, 170, 82)

def ease(x): x = min(1.0, max(0.0, x)); return x * x * (3 - 2 * x)

def scaled(img, s):
    rgb, al = img
    if abs(s - 1) < 0.004: return rgb, al
    h, w = rgb.shape[:2]; nw, nh = max(1, int(w * s)), max(1, int(h * s))
    return cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR), cv2.resize(al, (nw, nh), interpolation=cv2.INTER_LINEAR).reshape(nh, nw, 1)

def put(cv, img, cy, op=1.0, s=1.0, dy=0, blur=0.0):
    rgb, al = scaled(img, s)
    if blur > 0.3:
        k = int(blur) * 2 + 1; rgb = cv2.GaussianBlur(rgb, (k, k), 0); al = cv2.GaussianBlur(al, (k, k), 0).reshape(al.shape[0], al.shape[1], 1)
    h, w = rgb.shape[:2]; over(cv, rgb, al, W // 2 - w // 2, int(cy - h / 2 + dy), op)

def stack(imgs, gap=0):
    """vertically stack (rgb, al) images, centred horizontally."""
    w = max(i[0].shape[1] for i in imgs); h = sum(i[0].shape[0] for i in imgs) + gap * (len(imgs) - 1)
    rgb = np.zeros((h, w, 3), np.float32); al = np.zeros((h, w, 1), np.float32); y = 0
    for r, a in imgs:
        x = (w - r.shape[1]) // 2
        rgb[y:y + r.shape[0], x:x + r.shape[1]] = r * a + rgb[y:y + r.shape[0], x:x + r.shape[1]] * (1 - a)
        al[y:y + r.shape[0], x:x + r.shape[1]] = np.maximum(al[y:y + r.shape[0], x:x + r.shape[1]], a)
        y += r.shape[0] + gap
    return rgb, al

def words_runs(ws, font, size, col, upper=False, ar_font='NotoNaskhArabic.ttf', key=None, keycol=None):
    runs = []
    for i, w in enumerate(ws):
        t = w['text'].upper() if upper and not w['sacred'] else w['text']
        if not upper and not w['sacred'] and i > 0: t = t
        runs.append((t, F(font), size, keycol if (key is not None and i == key) else col))
        if w['ar']: runs.append((w['ar'], F(ar_font), int(size * 1.05), keycol if (key is not None and i == key) else col))
    return runs

def clean_text(t, lower):
    t = re.sub(r'[,;:]$', '', t)
    return t.lower() if lower else t

# ------------------------------------------------------------------ caption styles
class Base:
    def __init__(self, units, cy): self.cy = cy; self.items = []
    def cur(self, t):
        for it in self.items:
            if it[0] <= t < it[1]: return it
        return None

class Clean(Base):
    """2-3 words, lowercase Inter SemiBold white, ~30% of units fully yellow; quick pop."""
    def __init__(self, units, cy, font='Inter-SemiBold.ttf', size=58, yellow=0.3, lower=True):
        super().__init__(units, cy); rng = random.Random(len(units))
        for u in units:
            col = YEL if (rng.random() < yellow and len(u['words']) >= 2) else (255, 255, 255)
            runs = []
            for w in u['words']:
                runs.append((w['text'] if w['sacred'] else clean_text(w['text'], lower), F(font), size, col))
                if w['ar']: runs.append((w['ar'], F('NotoNaskhArabic.ttf'), int(size * 1.05), col))
            self.items.append((u['t0'], u['t1'], run_img(runs, shadow=0.7)))
    def draw(self, cv, t):
        it = self.cur(t)
        if it: age = t - it[0]; put(cv, it[2], self.cy, min(1, age / 0.05), 0.9 + 0.1 * ease(age / 0.1))

class Serif(Clean):
    def __init__(self, units, cy):
        super().__init__(units, cy, font='PlayfairDisplay-Bold.ttf', size=64, yellow=0.0)

class HBox(Base):
    """Poppins SemiBold lowercase, keyword white on a red rounded box."""
    def __init__(self, units, cy, size=56):
        super().__init__(units, cy); rng = random.Random(7)
        f = ImageFont.truetype(F('Poppins-SemiBold.ttf'), size)
        for u in units:
            ws = u['words']; k = keyword(ws) if rng.random() < 0.65 else None
            parts = []
            for i, w in enumerate(ws):
                txt = w['text'] if w['sacred'] else clean_text(w['text'], True)
                if w['ar']: txt = txt + ' ' + w['ar']
                parts.append((txt, i == k))
            self.items.append((u['t0'], u['t1'], self.img(parts, f, size)))
    @staticmethod
    def img(parts, f, size):
        pad = 40; gap = size * 0.28; bx = size * 0.22; by = size * 0.12
        ws = [f.getlength(t) + (2 * bx if b else 0) for t, b in parts]
        tw = int(sum(ws) + gap * (len(parts) - 1) + 2 * pad); asc, desc = f.getmetrics(); th = asc + desc + 2 * pad
        im = Image.new('RGBA', (tw, th), (0, 0, 0, 0)); d = ImageDraw.Draw(im); x = pad
        boxes = Image.new('RGBA', (tw, th), (0, 0, 0, 0)); db = ImageDraw.Draw(boxes)
        for (t, b), w in zip(parts, ws):
            if b:
                db.rounded_rectangle([x, pad + asc * 0.12 - by, x + w, pad + asc + desc * 0.55 + by], radius=int(size * 0.22), fill=RED + (255,))
                d.text((x + bx, pad + asc), t, font=f, fill=(255, 255, 255, 255), anchor='ls', direction='rtl' if C4.AR.search(t) and not re.search('[a-z]', t) else None)
            else:
                d.text((x, pad + asc), t, font=f, fill=(255, 255, 255, 255), anchor='ls')
            x += w + gap
        a = np.asarray(im).astype(np.float32) / 255.; b_ = np.asarray(boxes).astype(np.float32) / 255.
        al = a[..., 3]; ba = b_[..., 3]
        sh = np.roll(cv2.GaussianBlur(np.maximum(al, ba), (0, 0), size * 0.12), int(size * 0.05), 0) * 0.6
        A = np.maximum(np.maximum(al, ba), sh)
        C = (a[..., 2::-1] * al[..., None] + b_[..., 2::-1] * (ba * (1 - al))[..., None]) / np.maximum(A, 1e-4)[..., None]
        return C, A[..., None]
    def draw(self, cv, t):
        it = self.cur(t)
        if it: age = t - it[0]; put(cv, it[2], self.cy, min(1, age / 0.05), 0.92 + 0.08 * ease(age / 0.1))

class TypeCaps(Base):
    """heavy UPPERCASE typed letter by letter; the not-yet-spoken words show grey."""
    def __init__(self, units, cy, size=58):
        super().__init__(units, cy)
        self.f = F('HelveticaNeueHeavy.otf'); self.size = size
        for u in units:
            ws = u['words']
            txt = [w['text'] if w['sacred'] else w['text'].upper() for w in ws]
            self.items.append((u['t0'], u['t1'], ws, txt, {}))
    def draw(self, cv, t):
        it = self.cur(t)
        if not it: return
        t0, t1, ws, txt, cache = it
        # letters typed: within each word, letters appear over its duration (max 0.25 s)
        state = []
        for w, s in zip(ws, txt):
            if t < w['t0']: state.append((s, 0))
            else: state.append((s, len(s) if w['sacred'] else min(len(s), int(len(s) * (t - w['t0']) / min(0.25, max(0.06, w['t1'] - w['t0']))) + 1)))
        key = tuple(n for _, n in state)
        if key not in cache:
            runs = []
            for (s, n), w in zip(state, ws):
                if w['sacred']:
                    col = (255, 255, 255) if n else (120, 120, 120)
                    runs.append((s, self.f, self.size, col)); runs.append((w['ar'], F('NotoNaskhArabic.ttf'), self.size, col)); continue
                if n == 0: runs.append((s, self.f, self.size, (110, 110, 110)))
                elif n >= len(s): runs.append((s, self.f, self.size, (255, 255, 255)))
                else:
                    runs.append((s[:n], self.f, self.size, (255, 255, 255)))
                    runs[-1] = (s[:n], self.f, self.size, (255, 255, 255))
                    runs.append(('​' + s[n:], self.f, self.size, (110, 110, 110)))
            cache[key] = self.join(runs)
        put(cv, cache[key], self.cy)
    def join(self, runs):
        # like run_img but no gap between the typed and untyped part of one word
        merged = []
        for r in runs:
            if r[0].startswith('​') and merged:
                merged[-1] = merged[-1] + [(r[0][1:], r[1], r[2], r[3])]
            else: merged.append([r])
        imgs = [self.word(m) for m in merged]
        gap = int(self.size * 0.28)
        w = sum(i[0].shape[1] for i in imgs) + gap * (len(imgs) - 1); h = max(i[0].shape[0] for i in imgs)
        rgb = np.zeros((h, w, 3), np.float32); al = np.zeros((h, w, 1), np.float32); x = 0
        for r, a in imgs:
            y = (h - r.shape[0]) // 2
            rgb[y:y + r.shape[0], x:x + r.shape[1]] = r; al[y:y + r.shape[0], x:x + r.shape[1]] = a; x += r.shape[1] + gap
        return rgb, al
    def word(self, parts):
        fonts = [ImageFont.truetype(p[1], p[2]) for p in parts]
        pad = 30; asc = max(f.getmetrics()[0] for f in fonts); desc = max(f.getmetrics()[1] for f in fonts)
        tw = int(sum(f.getlength(p[0]) for p, f in zip(parts, fonts))) + 2 * pad
        im = Image.new('RGBA', (tw, asc + desc + 2 * pad), (0, 0, 0, 0)); d = ImageDraw.Draw(im); x = pad
        for p, f in zip(parts, fonts):
            ar = C4.AR.search(p[0]) is not None
            d.text((x, pad + asc), p[0], font=f, fill=p[3] + (255,), anchor='ls', direction='rtl' if ar else None); x += f.getlength(p[0])
        a = np.asarray(im).astype(np.float32) / 255.; al = a[..., 3]
        sh = np.roll(cv2.GaussianBlur(al, (0, 0), 6), 3, 0) * 0.6; A = np.maximum(al, sh)
        C = a[..., 2::-1] * al[..., None] / np.maximum(A, 1e-4)[..., None]
        return C, A[..., None]

class Gold(Base):
    """ONE word at a time, wide heavy UPPERCASE, cream->gold vertical gradient, warm glow; fades/blurs in."""
    def __init__(self, units, cy, size=82):
        super().__init__(units, cy)
        for u in units:
            for w in u['words']:
                t = w['text'] if w['sacred'] else re.sub(r"[^\w'’-]", '', w['text']).upper()
                if not t: continue
                runs = [(t, F('Montserrat-Black.ttf'), size if len(t) < 10 else int(size * 0.8), (255, 255, 255))]
                if w['ar']: runs.append((w['ar'], F('Amiri-Bold.ttf'), size, (255, 255, 255)))
                rgb, al = run_img(runs, shadow=0.0, spacing=0.05)
                g = np.linspace(0, 1, rgb.shape[0])[:, None, None]
                col = (np.array(GOLD1[::-1], np.float32) * (1 - g) + np.array(GOLD2[::-1], np.float32) * g) / 255.
                rgb = np.broadcast_to(col, rgb.shape).astype(np.float32).copy()
                glow = cv2.GaussianBlur(al, (0, 0), 14)[..., None] * 0.55
                A = np.maximum(al, glow); C = (rgb * al + np.array([60, 140, 230], np.float32) / 255 * glow * (1 - al)) / np.maximum(A, 1e-4)
                self.items.append((w['t0'], w['t1'], (C, A)))
        for i in range(len(self.items) - 1):   # hold each word until the next one
            a, b, im = self.items[i]; nb = self.items[i + 1][0]
            if nb - b < 0.6: self.items[i] = (a, nb, im)
    def draw(self, cv, t):
        it = self.cur(t)
        if it: age = t - it[0]; e = ease(age / 0.14); put(cv, it[2], self.cy, e, 1.06 - 0.06 * e, blur=(1 - e) * 6)

class Mixed(Base):
    """stacked mixed typography per phrase; layouts rotate:
       A small spaced caps line + big bold yellow word + thin underlined line
       B big gold bold serif lowercase phrase
       C bold white phrase + italic serif connector"""
    def __init__(self, units, cy):
        super().__init__(units, cy); rng = random.Random(11)
        groups = []; cur = []
        for u in units:
            cur.extend(u['words'])
            if len(cur) >= 3 or (cur and cur[-1]['end']): groups.append(cur); cur = []
        if cur: groups.append(cur)
        for k, g in enumerate(groups):
            lay = 'ABAC'[k % 4] if len(g) >= 3 else 'B'
            self.items.append((g[0]['t0'], g[-1]['t1'], g, lay, {}))
        for i in range(len(self.items) - 1):
            a, b, g, l, c = self.items[i]; nb = self.items[i + 1][0]
            if nb - b < 0.7: self.items[i] = (a, nb, g, l, c)
    def parts(self, g, lay):
        tx = lambda w: (w['text'] if w['sacred'] else clean_text(w['text'], True))
        if lay == 'A':
            k = keyword(g); k = len(g) - 2 if k is None or k == 0 else k
            top = g[:k]; key = g[k]; rest = g[k + 1:]
            lines = []
            if top: lines.append(('cap', [(' '.join(tx(w).upper() if not w['sacred'] else tx(w) for w in top), F('Montserrat-ExtraBold.ttf'), 40, (255, 255, 255))], top[0]['t0']))
            lines.append(('big', [(tx(key), F('Poppins-Bold.ttf'), 92, YEL)] + ([(key['ar'], F('NotoNaskhArabic.ttf'), 80, YEL)] if key['ar'] else []), key['t0']))
            if rest: lines.append(('thin', [(' '.join(tx(w) for w in rest), F('Inter-Light.ttf'), 50, (255, 255, 255))], rest[0]['t0']))
            return lines
        if lay == 'B':
            runs = []
            for w in g:
                runs.append((tx(w), F('PlayfairDisplay-Bold.ttf'), 66, (238, 200, 120)))
                if w['ar']: runs.append((w['ar'], F('Amiri-Bold.ttf'), 66, (238, 200, 120)))
            return [('serif', runs, g[0]['t0'])]
        a = g[:-1]; b = g[-1:]
        r1 = []
        for w in a:
            r1.append((tx(w), F('Poppins-Bold.ttf'), 62, (255, 255, 255)))
            if w['ar']: r1.append((w['ar'], F('NotoNaskhArabic.ttf'), 62, (255, 255, 255)))
        r2 = [(tx(b[0]), F('PlayfairDisplay-Italic.ttf'), 60, (255, 255, 255))] + ([(b[0]['ar'], F('Amiri-Regular.ttf'), 60, (255, 255, 255))] if b[0]['ar'] else [])
        return [('w', r1, a[0]['t0']), ('it', r2, b[0]['t0'])]
    def draw(self, cv, t):
        it = self.cur(t)
        if not it: return
        t0, t1, g, lay, cache = it
        lines = self.parts(g, lay) if 'p' not in cache else cache['p']; cache['p'] = lines
        if 'imgs' not in cache:
            imgs = []
            for kind, runs, ts in lines:
                im = run_img(runs, shadow=0.6, spacing=0.12 if kind == 'cap' else 0.0, pad=18)
                if kind == 'thin':   # underline
                    rgb, al = im; al = al.copy(); y = int(al.shape[0] * 0.80); al[y:y + 3, 18:-18] = 1.0; rgb = rgb.copy(); rgb[y:y + 3, 18:-18] = 1.0; im = (rgb, al)
                imgs.append((ts, im))
            cache['imgs'] = imgs
        imgs = cache['imgs']
        hs = [im[0].shape[0] for _, im in imgs]; tot = sum(hs) - 22 * (len(hs) - 1)
        y = self.cy - tot / 2
        for (ts, im), h in zip(imgs, hs):
            if t >= ts - 0.02:
                e = ease((t - ts) / 0.22)
                rgb, al = im; w = rgb.shape[1]
                over(cv, rgb, al, W // 2 - w // 2, int(y + (1 - e) * 18), e)
            y += h - 22

class Film(Base):
    """small bold UPPERCASE, words grey until spoken; when a phrase wraps, the 2nd line is bold italic."""
    def __init__(self, units, cy, size=46):
        super().__init__(units, cy)
        groups = []; cur = []
        for u in units:
            cur.extend(u['words'])
            if len(cur) >= 4 or (cur and cur[-1]['end']): groups.append(cur); cur = []
        if cur: groups.append(cur)
        for g in groups:
            l1 = g[:2] if len(g) > 2 else g; l2 = g[2:] if len(g) > 2 else []
            self.items.append((g[0]['t0'], g[-1]['t1'], l1, l2, {}))
        for i in range(len(self.items) - 1):
            a, b, l1, l2, c = self.items[i]; nb = self.items[i + 1][0]
            if nb - b < 0.6: self.items[i] = (a, nb, l1, l2, c)
        self.size = size
        self.foot = run_img([('follow for more', F('PlayfairDisplay-Italic.ttf'), 30, (230, 230, 230))], shadow=0.5, pad=10)
    def line(self, ws, t, italic):
        runs = []
        for w in ws:
            col = (255, 255, 255) if t >= w['t0'] else (125, 125, 125)
            txt = w['text'] if w['sacred'] else re.sub(r'[,.;:]$', '', w['text']).upper()
            runs.append((txt, F('HelveticaNeueBoldItalic.otf' if italic else 'HelveticaNeueBold.otf'), self.size, col))
            if w['ar']: runs.append((w['ar'], F('NotoNaskhArabic.ttf'), self.size, col))
        return run_img(runs, shadow=0.6, glow=((255, 255, 255), 0.12), pad=14)
    def draw(self, cv, t):
        it = self.cur(t)
        if it:
            t0, t1, l1, l2, cache = it
            key = sum(1 for w in l1 + l2 if t >= w['t0'])
            if key not in cache:
                ims = [self.line(l1, t, False)] + ([self.line(l2, t, True)] if l2 else [])
                cache[key] = stack(ims, gap=-14)
            put(cv, cache[key], self.cy, min(1, (t - t0) / 0.06))
        put(cv, self.foot, H * 0.80, 0.8)

class Bracket(Base):
    """one bold lowercase word at a time; ~1 in 5 in [brackets] or "quotes"; small name tag at the bottom."""
    def __init__(self, units, cy, credit='', size=74):
        super().__init__(units, cy); rng = random.Random(5); n = 0
        for u in units:
            for w in u['words']:
                t = w['text'] if w['sacred'] else re.sub(r'[^\w\'’-]', '', w['text']).lower()
                if not t: continue
                r = rng.random()
                if not w['sacred'] and len(t) > 2:
                    if r < 0.12: t = f'[{t}]'
                    elif r < 0.2: t = f'"{t}"'
                runs = [(t, F('HelveticaNeueBold.otf'), size, (255, 255, 255))]
                if w['ar']: runs.append((w['ar'], F('NotoNaskhArabic.ttf'), size, (255, 255, 255)))
                self.items.append((w['t0'], w['t1'], run_img(runs, shadow=0.5, pad=16)))
        for i in range(len(self.items) - 1):
            a, b, im = self.items[i]; nb = self.items[i + 1][0]
            if nb - b < 0.5: self.items[i] = (a, nb, im)
        self.tag = None
        if credit:
            f = ImageFont.truetype(F('Inter-SemiBold.ttf'), 24); tw = int(f.getlength(credit)) + 28
            im = Image.new('RGBA', (tw, 40), (0, 0, 0, 230)); ImageDraw.Draw(im).text((14, 20), credit, font=f, fill=(255, 255, 255, 255), anchor='lm')
            a = np.asarray(im).astype(np.float32) / 255.; self.tag = (a[..., 2::-1].copy(), a[..., 3:4].copy())
    def draw(self, cv, t):
        it = self.cur(t)
        if it: put(cv, it[2], self.cy)
        if self.tag: put(cv, self.tag, H * 0.78, 0.95)

# ------------------------------------------------------------------ looks
GRADE5 = {
 'clean':   "eq=contrast=1.06:saturation=1.04:brightness=0.0,curves=all='0/0.01 0.5/0.5 1/0.98'",
 'serif':   "eq=contrast=1.08:saturation=0.98:brightness=-0.02,colorbalance=rh=0.02:bh=-0.02,curves=all='0/0.01 0.5/0.48 1/0.97'",
 'hbox':    "eq=contrast=1.08:saturation=1.02:brightness=-0.01,curves=all='0/0.01 0.5/0.49 1/0.98'",
 'typecap': "eq=contrast=1.10:saturation=0.85:brightness=-0.04,colorbalance=bs=0.03:rh=0.02,curves=all='0/0.01 0.5/0.45 1/0.95'",
 'gold':    "eq=contrast=1.12:saturation=0.95:brightness=-0.07:gamma=0.92,colorbalance=rs=0.04:bs=0.08:rm=0.03:bm=0.04:rh=0.05:bh=-0.03,curves=all='0/0 0.5/0.42 1/0.9'",
 'mixed':   "eq=contrast=1.08:saturation=0.95:brightness=-0.04,colorbalance=rs=0.05:gs=0.01:bs=-0.05:rm=0.05:bm=-0.05:rh=0.05:bh=-0.06,curves=all='0/0.01 0.5/0.46 1/0.93'",
 'film':    "hue=s=0,eq=contrast=1.16:brightness=-0.04:gamma=0.92,curves=all='0/0.03 0.5/0.47 1/0.93'",
 'bracket': "hue=s=0,eq=contrast=1.30:brightness=-0.06:gamma=0.86,curves=all='0/0 0.2/0.05 0.6/0.58 1/0.98'",
}
# (window w, h, top) inside 1080x1920; None = full frame head lock
LAYOUT = {'clean': None, 'serif': None, 'hbox': None, 'bracket': None,
          'typecap': (960, 960, 480), 'gold': (960, 1200, 360), 'mixed': (1000, 860, 530), 'film': (1080, 810, 555)}
CAPY = {'clean': 0.56, 'serif': 0.56, 'hbox': 0.56, 'bracket': 0.50, 'typecap': 0.50, 'gold': 0.50, 'mixed': 0.50, 'film': 0.50}
HEAD = {None: (0.17, 0.36), 'typecap': (0.30, 0.40), 'gold': (0.24, 0.36), 'mixed': (0.30, 0.40), 'film': (0.34, 0.42)}

def round_mask(w, h, r):
    m = np.zeros((h, w), np.float32)
    cv2.rectangle(m, (r, 0), (w - r, h), 1, -1); cv2.rectangle(m, (0, r), (w, h - r), 1, -1)
    for cx, cy in [(r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)]: cv2.circle(m, (cx, cy), r, 1, -1, cv2.LINE_AA)
    return cv2.GaussianBlur(m, (0, 0), 0.8)[..., None]

class Dust:
    """fine slow dust/sparkle on the black canvas (low opacity)."""
    def __init__(self, n=140, seed=3):
        r = np.random.default_rng(seed)
        self.x = r.uniform(0, W, n); self.y = r.uniform(0, H, n); self.vx = r.uniform(-6, 6, n); self.vy = r.uniform(-14, -3, n)
        self.s = r.uniform(1.0, 2.6, n); self.ph = r.uniform(0, 6.28, n); self.a = r.uniform(0.15, 0.55, n)
    def draw(self, cv, t):
        x = (self.x + self.vx * t) % W; y = (self.y + self.vy * t) % H
        a = self.a * (0.6 + 0.4 * np.sin(self.ph + t * 1.7))
        for xi, yi, si, ai in zip(x.astype(int), y.astype(int), self.s, a):
            cv2.circle(cv, (xi, yi), max(1, int(si)), (ai * 255, ai * 245, ai * 230), -1, cv2.LINE_AA)

def grain(cv, amt, rng):
    n = rng.standard_normal((H // 2, W // 2)).astype(np.float32)
    n = cv2.resize(n, (W, H), interpolation=cv2.INTER_LINEAR)[..., None]
    cv += n * amt

_DOTS = None
def dots():
    global _DOTS
    if _DOTS is None:
        m = np.zeros((H, W), np.float32)
        for y in range(18, H, 36):
            for x in range(18, W, 36): cv2.circle(m, (x, y), 2, 1, -1, cv2.LINE_AA)
        _DOTS = m[..., None]
    return _DOTS

# ------------------------------------------------------------------ main render
def render(cid):
    c = CL[cid]; od = f'{OUT}/{cid}'; os.makedirs(od, exist_ok=True)
    st = c['style']
    if st in ('bright', 'cinema', 'text'):
        C4.CL[cid] = c
        return C4.render(cid)
    src = L.SRC[c['src']]
    a2, b2 = L.snap(c['src'], c['a'] - 0.1, 'start'), L.snap(c['src'], c['b'] + 0.15, 'end')
    d = b2 - a2
    va = L.piece_audio(od, 'v', c['src'], a2, b2)
    subprocess.run(['cp', va, f'{od}/voice.wav'], check=True)
    words = C4.words_for(cid, c, a2, b2)
    json.dump(words, open(f'{od}/words.json', 'w'))
    lay = LAYOUT[st]
    wm = render2.AnimWM(W, H, 96, win=(lay[2], lay[1]) if lay else None)
    nat = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', src], capture_output=True, text=True).stdout.split(',')
    SW, SH = int(nat[0]), int(nat[1]); pre = ''
    if SH > 1080: pre = 'scale=1920:1080:flags=lanczos,'; SW, SH = 1920, 1080
    crop = c.get('crop')
    if crop: SW, SH = crop[0], crop[1]
    xs, ys, ss, n_t = C4.track(src, a2, d, tuple(crop) if crop else None, pre)
    if lay is None:
        OWn, OHn = W, H; hf, hy = HEAD[None]
        cx, cy, s = C4.lock_path(xs, ys, ss, n_t, SW, SH, W, H, hf, hy, H / SH * 1.22)
    else:
        OWn, OHn = lay[0], lay[1]; hf, hy = HEAD[st]
        cx, cy, s = C4.lock_path(xs, ys, ss, n_t, SW, SH, OWn, OHn, hf, hy, max(OWn / SW, OHn / SH) * 1.12)
        mask = round_mask(OWn, OHn, 0 if st == 'film' else 38)
    vf = pre + (f'crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]},' if crop else '') + render2.CLARITY + ',' + GRADE5[st] + f',fps={FPS}'
    dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f'{a2:.3f}', '-t', f'{d:.3f}', '-i', src, '-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE)
    fsz = SW * SH * 3
    U = caps.units(words, maxw={'gold': 1, 'bracket': 1, 'typecap': 3, 'clean': 3, 'serif': 3, 'hbox': 3}.get(st, 2))
    cy_ = H * CAPY[st]
    cap = {'clean': lambda: Clean(U, cy_), 'serif': lambda: Serif(U, cy_), 'hbox': lambda: HBox(U, cy_), 'typecap': lambda: TypeCaps(U, cy_),
           'gold': lambda: Gold(U, cy_), 'mixed': lambda: Mixed(U, cy_), 'film': lambda: Film(U, cy_),
           'bracket': lambda: Bracket(U, cy_, c.get('credit', ''))}[st]()
    noise = {'film': 'noise=c0s=30:c0f=t+u', 'bracket': 'noise=c0s=16:c0f=t+u'}.get(st, 'noise=c0s=12:c0f=t+u')
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(OFPS), '-i', '-',
                            '-vf', f'unsharp=5:5:0.45:5:5:0,{noise}', '-c:v', 'libx264', '-profile:v', 'high', '-preset', 'veryfast', '-crf', '20',
                            '-maxrate', '12M', '-bufsize', '24M', '-pix_fmt', 'yuv420p', '-r', str(OFPS), '-video_track_timescale', '15360', f'{od}/{cid}.mp4'], stdin=subprocess.PIPE)
    def readf():
        b = dec.stdout.read(fsz)
        return np.frombuffer(b, np.uint8).reshape(SH, SW, 3) if len(b) == fsz else None
    cur = readf()
    if cur is None: raise RuntimeError('no frames')
    nxt = readf()
    PT = C4.Portrait() if c.get('blur') else None
    if PT: m_cur = PT.next(cur); m_nxt = PT.next(nxt) if nxt is not None else m_cur
    tt = np.arange(len(cx)) / FPS
    dust = Dust() if st in ('gold', 'mixed', 'typecap') else None
    rng = np.random.default_rng(1)
    n_out = int(round(d * OFPS)); src_i = 0
    for k in range(n_out):
        t = k / OFPS
        while (src_i + 1) / FPS <= t + 1e-6 and nxt is not None:
            cur, nxt, src_i = nxt, readf(), src_i + 1
            if PT: m_cur = m_nxt; m_nxt = PT.next(nxt) if nxt is not None else m_cur
        frac = t * FPS - src_i
        if nxt is not None and frac > 0.25:
            if frac < 0.75: fr = C4.midframe(cur, nxt); mk = (m_cur + m_nxt) / 2 if PT else None
            else: fr = nxt; mk = m_nxt if PT else None
        else: fr = cur; mk = m_cur if PT else None
        if PT: fr = C4.portrait_fx(fr, mk)
        X = np.interp(t, tt, cx); Y = np.interp(t, tt, cy)
        fp, P = C4.padded(fr)
        M = np.array([[s, 0, OWn / 2 - (X + P) * s], [0, s, OHn / 2 - (Y + P) * s]], np.float32)
        img = cv2.warpAffine(fp, M, (OWn, OHn), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        if lay is None:
            cv = img * C4.VIG
        else:
            cv = np.zeros((H, W, 3), np.float32)
            if st == 'gold': cv[:] = (14, 6, 12)
            x0 = (W - OWn) // 2; y0 = lay[2]
            cv[y0:y0 + OHn, x0:x0 + OWn] = img * mask + cv[y0:y0 + OHn, x0:x0 + OWn] * (1 - mask)
        if dust: dust.draw(cv, t)
        if st == 'film': grain(cv, 22, rng)
        if st == 'bracket':
            cv = cv * (1 - 0.10 * dots()) + 255 * 0.05 * dots()
        cap.draw(cv, t)
        wm.draw(cv, t, 0.85)
        enc.stdin.write(np.clip(cv, 0, 255).astype(np.uint8).tobytes())
    enc.stdin.close(); enc.wait(); dec.stdout.close(); dec.wait()
    print(cid, 'video', round(d, 1), 's', flush=True)
    return d

MUSICS = [('/home/claude/w/mus/m_new.wav', 2.9), ('/home/claude/w/mus/m2.wav', 4.48), ('/home/claude/w/mus/m3.wav', 8.43), ('/home/claude/w/mus/m4.wav', 14.35)]

def finish(cid, d):
    m = CL[cid].get('music', 0)
    C4.MUSIC, C4.MUS_ENTRY = MUSICS[m % len(MUSICS)]
    C4.finish(cid, d)

if __name__ == '__main__':
    for cid in sys.argv[1:]:
        if os.path.exists(f'{OUT}/{cid}/{cid}_o.mp4'): continue
        d = render(cid); finish(cid, d)

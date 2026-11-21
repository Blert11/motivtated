"""Kinetic letter-by-letter titles (shakilmalji style), rendered in Python per frame.
Titles are always centred on the canvas (user rule)."""
import numpy as np, cv2, re, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FD = '/home/claude/fonts/'
F_BOLD = FD + 'HelveticaNeueBold.otf'
F_HEAVY = FD + 'HelveticaNeueHeavy.otf'
F_MED = FD + 'HelveticaNeueMedium.otf'
F_BI = FD + 'HelveticaNeueBoldItalic.otf'
F_SERIF = FD + 'PlayfairDisplay-Italic.ttf'
F_AR = FD + 'NotoNaskhArabic.ttf'
YELLOW = (255, 238, 20)
WHITE = (255, 255, 255)
STOP = set("a an the of to and or but in on at for with is are was were be been it its i you he she we they me my your his her our their this that these those so as if then than not no do does did have has had will would can could should just like what who which when where why how am from by up out about into all".split())

_font = {}
def font(path, size):
    k = (path, size)
    if k not in _font:
        _font[k] = ImageFont.truetype(path, size)
    return _font[k]

BLURS = [0, 2, 4, 7, 11]
_sprite = {}
def sprite(ch, path, size, col, glow=None, shadow=True):
    """Return list of RGBA float arrays (one per blur level) for one glyph, plus offset."""
    k = (ch, path, size, col, glow, shadow)
    if k in _sprite: return _sprite[k]
    f = font(path, size)
    if path == F_AR:
        f.set_variation_by_axes([700]) if hasattr(f, 'set_variation_by_axes') else None
    l, t, r, b = f.getbbox(ch, direction='rtl' if path == F_AR else None)
    pad = int(size * 0.5) + 14
    W, H = max(1, r - l) + 2 * pad, max(1, b - t) + 2 * pad
    base = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    ox, oy = pad - l, pad - t
    layers = []
    if shadow:
        sh = Image.new('RGBA', (W, H), (0, 0, 0, 0)); ImageDraw.Draw(sh).text((ox + 2, oy + 4), ch, font=f, fill=(0, 0, 0, 150),
                                                                           direction='rtl' if path == F_AR else None)
        layers.append(sh.filter(ImageFilter.GaussianBlur(size * 0.08 + 3)))
    if glow:
        gl = Image.new('RGBA', (W, H), (0, 0, 0, 0)); ImageDraw.Draw(gl).text((ox, oy), ch, font=f, fill=glow + (200,),
                                                                       direction='rtl' if path == F_AR else None)
        layers.append(gl.filter(ImageFilter.GaussianBlur(size * 0.12 + 4)))
    d.text((ox, oy), ch, font=f, fill=col + (255,), direction='rtl' if path == F_AR else None)
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    for L in layers: img = Image.alpha_composite(img, L)
    img = Image.alpha_composite(img, base)
    arrs = []
    for bl in BLURS:
        im = img if bl == 0 else img.filter(ImageFilter.GaussianBlur(bl))
        a = np.asarray(im).astype(np.float32) / 255.
        arrs.append(a)
    res = (arrs, ox, oy)  # glyph origin inside sprite
    _sprite[k] = res
    return res

def advance(ch, path, size):
    return font(path, size).getlength(ch)

def line_layout(segments, cy, W=1080, track=0):
    """segments: list of (text, path, size, col, glow, word_index). Returns glyph items centred at x=W/2, baseline y."""
    total = 0
    adv = []
    for s in segments:
        text, path, size = s[0], s[1], s[2]
        if path == F_AR:
            w = font(path, size).getlength(text, direction='rtl'); adv.append([w]); total += w
        else:
            ws = [advance(c, path, size) + track * size for c in text]; adv.append(ws); total += sum(ws)
        total += size * 0.28  # word gap
    total -= segments[-1][2] * 0.28
    x = W / 2 - total / 2
    items = []
    for s, ws in zip(segments, adv):
        text, path, size, col, glow, wi = s
        if path == F_AR:
            items.append(dict(ch=text, path=path, size=size, col=col, glow=glow, x=x, y=cy, wi=wi, k=0)); x += ws[0]
        else:
            for k, (c, w) in enumerate(zip(text, ws)):
                if c != ' ':
                    items.append(dict(ch=c, path=path, size=size, col=col, glow=glow, x=x, y=cy, wi=wi, k=k))
                x += w
        x += size * 0.28
    return items, total

def fit_size(segments, maxw, W=1080):
    _, tw = line_layout(segments, 0, W)
    if tw <= maxw: return segments
    s = maxw / tw
    return [(a, p, max(14, int(sz * s)), c, g, wi) for a, p, sz, c, g, wi in segments]

def norm(w): return re.sub(r"[^\w']", '', w.lower())

def disp_words(unit_words):
    """unit word dicts from caps.units -> list of (latin_text, arabic or None, t0)."""
    out = []
    for w in unit_words:
        if w.get('sacred'):
            out.append((w['text'], w['ar'], w['t0'], True))
        else:
            out.append((re.sub(r'[,;:.!]+$', '', w['text']), None, w['t0'], False))
    return out

def merge_orphans(units):
    """merge single stop-word units into the following unit"""
    out = []
    i = 0
    while i < len(units):
        u = units[i]
        if len(u['words']) == 1 and not u['words'][0].get('sacred') and norm(u['words'][0]['text']) in STOP and i + 1 < len(units) \
                and units[i + 1]['t0'] - u['words'][0]['t1'] < 1.2 and not units[i + 1]['words'][0].get('sacred'):
            nxt = dict(units[i + 1]); nxt['words'] = u['words'] + nxt['words']; nxt['t0'] = u['t0']
            out.append(nxt); i += 2; continue
        if len(u['words']) == 1 and not u['words'][0].get('sacred') and norm(u['words'][0]['text']) in STOP and out:
            prv = dict(out[-1]); prv['words'] = prv['words'] + u['words']; prv['t1'] = u['t1']; out[-1] = prv; i += 1; continue
        out.append(u); i += 1
    return out

def build(units, W=1080, H=1920, cy=None, scale=1.0, seed=0, maxw=900, mode='kinetic'):
    """Choose a layout per unit and produce timed glyph items."""
    units = merge_orphans(units)
    rng = np.random.default_rng(seed)
    cy = cy if cy is not None else H // 2
    S = lambda v: int(v * scale)
    timeline = []
    layouts = ['glow', 'stack', 'plain', 'huge', 'italic', 'plain2']
    li = 0
    for ui, u in enumerate(units):
        words = disp_words(u['words'])
        n = len(words)
        has_sacred = any(w[3] for w in words)
        # pick layout
        if mode == 'stoic':
            lay = 'stoic'
        elif n == 1 and not has_sacred and len(words[0][0]) <= 7 and norm(words[0][0]) not in STOP:
            lay = 'huge' if rng.random() < 0.5 else 'glow'
        else:
            lay = layouts[li % len(layouts)]; li += 1
            if lay == 'huge': lay = 'stack'
            if lay == 'glow' and (norm(words[0][0]) in STOP or n > 4): lay = 'plain2'
        lines = []  # each line: list of segments
        def seg(text, ar, wi, path, size, col, glow=None):
            out = [(text, path, size, col, glow, wi)]
            if ar: out.append((ar, F_AR, int(size * 1.15), col, glow, wi))
            return out
        if lay == 'glow':
            # first part yellow glowing, rest white smaller below
            cut = max(1, n // 2) if n > 1 else 1
            l1, l2 = [], []
            for i, (t, ar, _, sac) in enumerate(words):
                if i < cut: l1 += seg(t, ar, i, F_BOLD, S(96), YELLOW, YELLOW)
                else: l2 += seg(t, ar, i, F_BOLD, S(66), WHITE)
            lines = [l1] + ([l2] if l2 else [])
        elif lay == 'stack':
            cut = max(1, n - max(1, n // 2))
            l1 = []; l2 = []
            for i, (t, ar, _, sac) in enumerate(words):
                if i < cut: l1 += seg(t.upper(), ar, i, F_MED, S(40), WHITE)
                else: l2 += seg(t.upper(), ar, i, F_HEAVY, S(92), (240, 240, 245))
            lines = [l1, l2] if l2 else [l1]
            if n == 1: lines = [[s for s in seg(words[0][0].upper(), words[0][1], 0, F_HEAVY, S(110), WHITE)]]
        elif lay == 'huge':
            t, ar, _, sac = words[0]
            lines = [seg(t.upper(), ar, 0, F_HEAVY, S(230), (232, 240, 255))]
        elif lay == 'italic':
            l1 = []; l2 = []
            for i, (t, ar, _, sac) in enumerate(words):
                if i == n - 1 and n > 1: l2 += seg(t, ar, i, F_SERIF, S(104), WHITE)
                else: l1 += seg(t, ar, i, F_BI, S(78), WHITE)
            lines = [l1] + ([l2] if l2 else [])
        elif lay == 'stoic':
            # stoicmuslims: heavy bold-italic key word, thin italic serif connectors, regular sans others; stacked
            cand = [i for i, w in enumerate(words) if norm(w[0]) not in STOP and not w[3]]
            key = max(cand, key=lambda i: len(words[i][0])) if cand else -1
            cur = []; lines = []
            for i, (t, ar, _, sac) in enumerate(words):
                if i == key:
                    if cur: lines.append(cur); cur = []
                    lines.append(seg(t.lower(), ar, i, F_BI, S(128), WHITE)); continue
                if norm(t) in STOP: cur += seg(t.lower(), ar, i, F_SERIF, S(64), WHITE)
                else: cur += seg(t if sac else t.lower(), ar, i, F_MED, S(70), WHITE)
            if cur: lines.append(cur)
        elif lay == 'plain2':
            # small line above + bold line
            cut = max(1, n // 3)
            l1 = []; l2 = []
            for i, (t, ar, _, sac) in enumerate(words):
                if i < cut and n > 2: l1 += seg(t, ar, i, F_BOLD, S(40), WHITE)
                else: l2 += seg(t, ar, i, F_BOLD, S(72), WHITE)
            lines = [l for l in (l1, l2) if l]
        else:  # plain
            l = []
            for i, (t, ar, _, sac) in enumerate(words): l += seg(t, ar, i, F_BOLD, S(76), WHITE)
            lines = [l]
        lines = [fit_size(l, maxw, W) for l in lines]
        # vertical stacking centred on cy
        heights = [max(s[2] for s in l) for l in lines]
        gap = S(10)
        total_h = sum(heights) + gap * (len(lines) - 1)
        y = cy - total_h / 2
        items = []
        for l, h in zip(lines, heights):
            base = y + h * 0.80
            its, _ = line_layout(l, base, W)
            items += its
            y += h + gap
        # timing
        t_end = u['t1']
        for it in items:
            wt = words[it['wi']][2]
            it['t_in'] = max(u['t0'] - 0.05, wt - 0.06) + it['k'] * 0.038
            it['t_out'] = t_end
            it['arc'] = (rng.random() - 0.5) * 0.6
        timeline.append(dict(t0=u['t0'], t1=t_end, items=items, lay=lay))
    return timeline

def ease(p): return 1 - (1 - p) ** 3

def render(canvas, timeline, t, IN=0.30, OUT=0.20):
    """Composite active titles onto canvas (float32 BGR 0-255) in place."""
    for blk in timeline:
        if t < blk['t0'] - 0.1 or t > blk['t1'] + OUT: continue
        for it in blk['items']:
            if t < it['t_in']: continue
            arrs, ox, oy = sprite(it['ch'], it['path'], it['size'], it['col'], it['glow'])
            p = min(1, (t - it['t_in']) / IN); e = ease(p)
            q = 0 if t < it['t_out'] else min(1, (t - it['t_out']) / OUT)
            alpha = e * (1 - q)
            if alpha <= 0.01: continue
            dy = (1 - e) * it['size'] * 0.32 - q * it['size'] * 0.12
            dx = (1 - e) * it['size'] * 0.10 * it['arc']
            bl = (1 - e) * 11 + q * 9
            bi = min(range(len(BLURS)), key=lambda j: abs(BLURS[j] - bl))
            A = arrs[bi]
            x0 = int(round(it['x'] - ox + dx)); y0 = int(round(it['y'] - it['size'] * 0.80 - oy + it['size'] * 0.0 + dy))
            # PIL text origin is top of ascent; we positioned baseline at y; approximate ascent = 0.8*size
            h, w = A.shape[:2]
            H, W = canvas.shape[:2]
            xs, ys = max(0, x0), max(0, y0); xe, ye = min(W, x0 + w), min(H, y0 + h)
            if xe <= xs or ye <= ys: continue
            a = A[ys - y0:ye - y0, xs - x0:xe - x0]
            al = a[..., 3:4] * alpha
            rgb = a[..., 2::-1] * 255  # RGBA->BGR
            region = canvas[ys:ye, xs:xe]
            canvas[ys:ye, xs:xe] = region * (1 - al) + rgb * al
    return canvas

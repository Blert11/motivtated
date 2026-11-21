"""Caption builder: word list -> display units -> ASS file for a given style."""
import re, difflib
from PIL import ImageFont

FD = '/home/claude/fonts/'
FONTFILES = {
    'Bebas Neue': 'BebasNeue.ttf', 'Coolvetica': 'coolvetica rg.otf', 'Montserrat Light': 'Montserrat-Light.ttf',
    'Montserrat SemiBold': 'Montserrat-SemiBold.ttf', 'Montserrat Black': 'Montserrat-Black.ttf', 'Montserrat Medium': 'Montserrat-Medium.ttf',
    'Helvetica Neue Medium': 'HelveticaNeueMedium.otf', 'Helvetica Neue Bold': 'HelveticaNeueBold.otf',
    'Helvetica Neue Heavy': 'HelveticaNeueHeavy.otf', 'Courier Prime': 'CourierPrime-Bold.ttf',
    'Playfair Display': 'PlayfairDisplay-Italic.ttf', 'Amiri': 'Amiri-Bold.ttf',
}
STOP = set("don't doesn't didn't can't won't isn't i'm it's you're we're they're that's he's she's what's there's let's i've you've i'll".split()) | set('a an the of to and or but in on at for with is are was were be been it its i you he she we they me my your his her our their this that these those so as if then than not no do does did have has had will would can could should just like what who whom which when where why how am im youre dont its thats there here from by up down out about into over all any some'.split())

# Sacred names: regex over lowercased joined tokens -> (display, arabic)
SACRED = [
    (r"^allah('s)?$", ["subhanahu", "wa", "ta'ala", "ta'ala's", "taala", "azza", "jal", "wajal", "wa'jal", "azzawajal"], 'Allah{p} SWT.', 'الله'),
    (r"^muhammad('s)?$", ["sallallahu", "alayhi", "alaihi", "wasallam", "wa", "sallam"], 'Muhammad{p}', 'محمد ﷺ'),
    (r"^rasulullah('s)?$", ["sallallahu", "alayhi", "alaihi", "wasallam", "wa", "sallam"], 'Rasulullah{p}', 'رسول الله ﷺ'),
    (r"^rasulallah('s)?$", ["sallallahu", "alayhi", "alaihi", "wasallam", "wa", "sallam"], 'Rasulullah{p}', 'رسول الله ﷺ'),
    (r"^ali$", ["ibn", "abi", "talib", "radiallahu", "anhu"], 'Ali ibn Abi Talib RA', 'علي'),
    (r"^ibrahim('s)?$", ["alaihi", "alayhi", "salam", "as-salam", "assalam"], 'Ibrahim{p} AS', 'إبراهيم'),
]

def norm(w):
    return re.sub(r"[^\w']", '', w.lower())

def align(asr_words, corrected_text):
    """Map corrected words onto ASR word timings."""
    cw = corrected_text.split()
    a = [norm(w[2]) for w in asr_words]
    b = [norm(w) for w in cw]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = [None] * len(cw)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(j2 - j1):
                out[j1 + k] = [asr_words[i1 + k][0], asr_words[i1 + k][1], cw[j1 + k]]
        elif tag in ('replace',) and i2 > i1:
            t0, t1 = asr_words[i1][0], asr_words[i2 - 1][1]
            n = j2 - j1
            for k in range(n):
                out[j1 + k] = [t0 + (t1 - t0) * k / n, t0 + (t1 - t0) * (k + 1) / n, cw[j1 + k]]
    # inserts: interpolate between neighbours
    for i in range(len(out)):
        if out[i] is None:
            prev = next((out[j] for j in range(i - 1, -1, -1) if out[j]), None)
            nxt = next((out[j] for j in range(i + 1, len(out)) if out[j]), None)
            t0 = prev[1] if prev else (nxt[0] - 0.3 if nxt else 0)
            t1 = nxt[0] if nxt else t0 + 0.3
            if t1 <= t0: t1 = t0 + 0.2
            out[i] = [t0, min(t1, t0 + 0.5), cw[i]]
    return out

def units(words, maxw=1, phrase=False):
    """Group words into display units. Sacred names merged with honorifics into own unit."""
    toks = []
    i = 0
    while i < len(words):
        w = words[i]
        n = norm(w[2])
        hit = None
        for pat, hon, disp, ar in SACRED:
            m = re.match(pat, n)
            if m:
                j = i + 1
                H = [h.replace("'s", '') for h in hon]
                starters = {'ibn', 'radiallahu', 'subhanahu', 'azza', 'azzawajal', 'sallallahu', 'alaihi', 'alayhi', 'swt', 'saw'}
                if j < len(words) and re.sub("'s$", '', norm(words[j][2])) in starters:
                    while j < len(words) and re.sub("'s$", '', norm(words[j][2])) in H + list(starters):
                        j += 1
                p = "'s" if ((m.groups() and m.group(1)) or norm(words[j - 1][2]).endswith("'s")) else ''
                hit = {'t0': w[0], 't1': words[j - 1][1], 'text': disp.format(p=p), 'ar': ar, 'sacred': True, 'end': words[j - 1][2][-1] in '.!?'}
                # keep "Prophet"/"the" before name as normal words
                i = j
                break
        if not hit and n == 'prophet':
            nx = norm(words[i + 1][2]) if i + 1 < len(words) else ''
            if re.match(r"^muhammad('s)?$", nx):
                j = i + 2
                if j < len(words) and norm(words[j][2]) in ('sallallahu', 'alayhi', 'alaihi'):
                    while j < len(words) and norm(words[j][2]) in ('sallallahu', 'alayhi', 'alaihi', 'wa', 'sallam', 'wasallam'):
                        j += 1
                p = "'s" if nx.endswith("'s") else ''
                hit = {'t0': w[0], 't1': words[j - 1][1], 'text': f"Prophet Muhammad{p}", 'ar': 'محمد ﷺ', 'sacred': True, 'end': words[j - 1][2][-1] in '.!?'}
                i = j
            else:
                hit = {'t0': w[0], 't1': w[1], 'text': 'Prophet', 'ar': 'النبي ﷺ', 'sacred': True, 'end': w[2][-1] in '.!?'}
                i += 1
        if hit:
            toks.append(hit); continue
        toks.append({'t0': w[0], 't1': w[1], 'text': w[2], 'ar': None, 'sacred': False, 'end': w[2][-1] in '.!?,'})
        i += 1
    # group
    U = []
    cur = []
    for k, t in enumerate(toks):
        if t['sacred']:
            if cur: U.append(cur); cur = []
            U.append([t]); continue
        cur.append(t)
        gap = toks[k + 1]['t0'] - t['t1'] if k + 1 < len(toks) else 9
        if len(cur) >= maxw or t['end'] or gap > 0.35 or (k + 1 < len(toks) and toks[k + 1]['sacred']):
            if phrase and len(cur) < 3 and not (t['end'] and t['text'][-1] in '.!?') and gap < 0.6 and k + 1 < len(toks) and not toks[k+1]['sacred']:
                continue
            U.append(cur); cur = []
    if cur: U.append(cur)
    # timing: show from first start to next unit start (cap)
    res = []
    for k, u in enumerate(U):
        t0 = u[0]['t0']
        nxt = U[k + 1][0]['t0'] if k + 1 < len(U) else u[-1]['t1'] + 0.6
        t1 = min(nxt, u[-1]['t1'] + 0.7)
        if t1 - t0 < 0.18: t1 = t0 + 0.18
        res.append({'t0': t0, 't1': t1, 'words': u})
    # no overlaps
    for k in range(len(res) - 1):
        res[k]['t1'] = min(res[k]['t1'], res[k + 1]['t0'])
    return res

def ts(t):
    t = max(0, t)
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f'{h}:{m:02d}:{s:05.2f}'

_fc = {}
def width(font, size, text, sp=0):
    key = (font, size)
    if key not in _fc:
        _fc[key] = ImageFont.truetype(FD + FONTFILES[font], size)
    return _fc[key].getlength(text) + sp * len(text)

def clean(w):
    return w.replace('{', '').replace('}', '')

def strip_p(w):
    return re.sub(r'[,.;:]+$', '', w) if not w.endswith('...') else w

def case(text, mode):
    if mode == 'upper': return text.upper()
    if mode == 'lower': return text.lower()
    if mode == 'title': return ' '.join(x[:1].upper() + x[1:] for x in text.split(' '))
    return text

def sacred_txt(u, mode, font, size, color=None, arsize=None):
    t = u['text']
    if mode == 'upper': t = t.replace('Allah', 'ALLAH').replace('Muhammad', 'MUHAMMAD').replace('Rasulullah', 'RASULULLAH').replace('Ibrahim', 'IBRAHIM').replace('Prophet', 'PROPHET').replace("'s", "'S")
    elif mode == 'lower': t = t  # keep sacred names capitalised always
    ars = arsize or int(size * 1.6)
    return f"{t} {{\\fnNoto Naskh Arabic\\b1\\i0\\fsp0\\fs{ars}}}{u['ar']}"

def build_ass(units_, style, W, H, accent='&H002B8AFF&', path='caps.ass'):
    cx, cy = W // 2, H // 2
    scale = W / 1080
    S = style
    lines = []
    def ev(t0, t1, txt, layer=1):
        if S.get('soft'):
            sh = re.sub(r'\\[13]?c&H[0-9A-Fa-f]+&', '', txt).replace('\\blur1', '').replace('\\blur2', '')
            blk = f'\\1c&H000000&\\1a&H{S["soft"]}&\\bord{S.get("sbord", 2)}\\3c&H000000&\\3a&H{S["soft"]}&\\shad0\\blur6'
            sh = sh.replace('}', blk + '}')
            lines.append(f'Dialogue: 0,{ts(t0)},{ts(t1)},Default,,0,0,0,,{{\\an5\\pos({cx+2},{cy+4}){blk}}}' + sh)
        lines.append(f'Dialogue: {layer},{ts(t0)},{ts(t1)},Default,,0,0,0,,{{\\an5\\pos({cx},{cy})}}{txt}')
    maxw = 880 * scale if W < H else 1100
    for u in units_:
        words = u['words']; t0, t1 = u['t0'], u['t1']
        if S['name'] == 'resolute':
            if words[0]['sacred']:
                sz = fit(S['font'], 104, sacred_txt(words[0], 'upper', '', 104), maxw)
                ev(t0, t1, f"{{\\fn{S['font']}\\fs{sz}\\fad(80,0)}}" + sacred_txt(words[0], 'upper', S['font'], sz, arsize=int(sz*1.4)))
                continue
            ws = [strip_p(clean(w['text'])) for w in words]
            cand = [k for k, w in enumerate(ws) if norm(w) not in STOP]
            if not cand:
                msz = fit('Montserrat Black', int(84 * scale), ' '.join(ws).upper(), maxw)
                ev(t0, t1, f"{{\\fad(70,0)\\fnMontserrat Black\\fs{msz}}}" + ' '.join(ws).upper())
                continue
            kidx = max(cand, key=lambda k: len(ws[k]))
            pre = ' '.join(ws[:kidx]).lower(); post = ' '.join(ws[kidx + 1:]).lower()
            key = ws[kidx].upper()
            ksz = fit('Montserrat Black', int(118 * scale), key, maxw)
            small = f"{{\\fnPlayfair Display\\i1\\b0\\fs{int(46*scale)}}}"
            big = f"{{\\fnMontserrat Black\\i0\\fs{ksz}}}"
            txt = (small + pre + '\\N' if pre else '') + big + key + ('\\N' + small + post if post else '')
            ev(t0, t1, '{\\fad(70,0)}' + txt)
            continue
        if S['name'] == 'accent':
            # per-word highlight within unit
            for k, w in enumerate(words):
                if w['sacred']:
                    sz = fit(S['font'], S['size'], sacred_txt(w, 'lower', '', S['size']), maxw)
                    ev(w['t0'], t1 if k == len(words) - 1 else words[k + 1]['t0'], f"{{\\fs{sz}\\c{accent}}}" + sacred_txt(w, 'lower', '', sz))
                    continue
                parts = []
                for j, w2 in enumerate(words):
                    tx = strip_p(clean(w2['text'])).lower()
                    parts.append((f"{{\\c{accent}}}" if j == k else "{\\c&H00FFFFFF&}") + tx)
                e = t1 if k == len(words) - 1 else words[k + 1]['t0']
                sz = fit(S['font'], S['size'], ' '.join(strip_p(w2['text']).lower() for w2 in words), maxw)
                ev(w['t0'], e, f"{{\\fs{sz}}}" + ' '.join(parts))
            continue
        if words[0]['sacred']:
            sz = fit(S['font'], S['size'], sacred_txt(words[0], S['case'], '', S['size']), maxw, S.get('sp', 0))
            ev(t0, t1, f"{{\\fs{sz}{S.get('fx','')}}}" + sacred_txt(words[0], S['case'], S['font'], sz))
            continue
        if S['name'] == 'boldital':
            parts = []
            for w in words:
                tx = strip_p(clean(w['text'])).lower()
                parts.append(('{\\fnHelvetica Neue Bold\\i1}' if (norm(tx) not in STOP and len(norm(tx)) >= 5) else '{\\fnHelvetica Neue Bold\\i0}') + tx)
            txt = ' '.join(parts)
            plain = ' '.join(strip_p(w['text']).lower() for w in words)
        else:
            plain = ' '.join(clean(w['text']) for w in words)
            if S.get('strip', True): plain = ' '.join(strip_p(x) for x in plain.split())
            plain = case(plain, S['case'])
            txt = plain
        sz = fit(S['font'], S['size'], plain, maxw, S.get('sp', 0))
        ev(t0, t1, f"{{\\fs{sz}{S.get('fx','')}}}" + txt)
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{S['font']},{S['size']},{S.get('col','&H00FFFFFF')},&H00FFFFFF,{S.get('ocol','&H00000000')},{S.get('bcol','&H80000000')},{S.get('bold',0)},0,0,0,100,100,{S.get('sp',0)},0,1,{S.get('bord',0)},{S.get('shad',0)},5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    body = re.sub(r'\bdna\b', 'DNA', re.sub(r'\bquran', 'Quran', '\n'.join(lines)))
    open(path, 'w').write(hdr + body + '\n')

def fit(font, size, text, maxw, sp=0):
    # strip ASS tags/arabic for measure
    t = re.sub(r'\{[^}]*\}', '', text)
    lat = re.sub(r'[؀-ۿﷰ-﷿]+', 'WWW', t)
    try:
        w = width(font, size, lat, sp)
    except Exception:
        w = len(lat) * size * 0.55
    if w > maxw:
        return max(int(size * maxw / w), int(size * 0.45))
    return size

STYLES = {
    'bebas': dict(name='bebas', font='Bebas Neue', size=86, case='upper', col='&H00DCE6ED', bord=0, shad=0, soft='70', fx='\\fad(50,0)', n=1),
    'coolv': dict(name='coolv', font='Coolvetica', size=80, case='lower', bord=0, shad=0, soft='50', fx='', n=1),
    'montlight': dict(name='montlight', font='Montserrat Light', size=54, case='upper', sp=6, bord=0, shad=0, soft='20', fx='\\fad(60,0)', n=3),
    'helvmed': dict(name='helvmed', font='Helvetica Neue Medium', size=64, case='as', bord=0, shad=0, soft='70', fx='', n=1),
    'accent': dict(name='accent', font='Coolvetica', size=82, case='lower', bord=0, shad=0, soft='50', fx='', n=2),
    'boldital': dict(name='boldital', font='Helvetica Neue Bold', size=74, case='lower', bord=0, shad=0, soft='50', fx='\\fad(80,0)', n=2),
    'resolute': dict(name='resolute', font='Montserrat Black', size=118, case='upper', bord=0, shad=0, soft='60', n=3),
    'eidos': dict(name='eidos', font='Montserrat SemiBold', size=50, case='lower', bord=4, ocol='&H70000000', shad=0, fx='\\blur6\\fad(120,60)', n=6, phrase=True),
    'podcast': dict(name='podcast', font='Montserrat SemiBold', size=42, case='upper', sp=2, bord=0, shad=0, soft='30', n=3),
    'typewriter': dict(name='typewriter', font='Courier Prime', size=62, case='title', bord=2, ocol='&H00101010', shad=1, bcol='&H80000000', n=3, bold=1),
    'overlayword': dict(name='overlayword', font='Montserrat Black', size=180, case='lower', bord=0, shad=0, n=1),
    'tiny': dict(name='tiny', font='Helvetica Neue Medium', size=36, case='lower', bord=0, shad=0, soft='80', n=3),
}

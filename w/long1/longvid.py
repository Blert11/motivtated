"""Long-form horizontal (1920x1080) compilation renderer for @imanivated.
usage: python3 longvid.py <video_dir>   (dir contains cfg.json, fix.txt)
cfg.json: {"chapters": [[["src",a,b], ...], ...], "punch": ["phrase", ...], "broll_chapters": [1,4,7]}
"""
import json, os, sys, re, subprocess, math, random
import numpy as np, soundfile as sf
sys.path.insert(0, '/home/claude/w'); sys.path.insert(0, '/home/claude/w/long1')
import caps, render2
from PIL import Image, ImageDraw, ImageFont

U = '/mnt/user-data/uploads'
SRC = {
 'hr': U+'/Downloads/vidssave.com Horrors of this World _ Akhi Ayman _ BG _ Wonder Where you are 720P.mp4',
 'ud': U+'/Downloads/vidssave.com No One Escapes the Grave - A Powerful Reminder for Every Soul ! The Muslim Undertaker 720P.mp4',
 'ay': U+'/Downloads/vidssave.com Akhi Ayman Powerful Speech _ BG _ Halal Beats, Where you are 720P.mp4',
 'fu': U+'/Downloads/vidssave.com Fix Up! - Akhi Ayman Powerful Message _ BG Halal Beats _ Where you are 720P.mp4',
 'wp': U+'/Downloads/vidssave.com Why Do You Not Pray_! - Akhi Ayman Powerful Speech __ BG_ Wonder Where You Are 720P.mp4',
 'tr': U+"/Downloads/vidssave.com The Trap of the Streets_ Don't Walk Away From the Ones Who Love You 720P.mp4",
 'r0': U+'/imanivated/_work/rep_0.mp4', 'r1': U+'/imanivated/_work/rep_1.mp4',
}
for i in range(4): SRC[f'rd{i}'] = U+f'/imanivated/_work/rd_{i}.mp4'
for i in range(6): SRC[f'yt{i}'] = U+f'/imanivated/_work/yt_{i}.mp4'
ASR = {'hr': 'hr.json', 'ud': 'ud.json', 'ay': 'ayman.json', 'r0': 'r0.json', 'r1': 'r1.json'}
for k in ['fu', 'wp', 'tr'] + [f'rd{i}' for i in range(4)] + [f'yt{i}' for i in range(6)]: ASR[k] = f'b3/{k}.json'
NOSEP = {'tr'} | {f'rd{i}' for i in range(4)} | {f'yt{i}' for i in range(6)}
# source crops (w:h:x:y in 1280x720) removing burned captions, channel logos, letterbox
CROP = {'tr': (1052, 592, 60, 66), 'wp': (871, 490, 141, 72), 'fu': (986, 555, 26, 144)}
W, H, FPS = 1920, 1080, 30
XF = 0.7          # chapter crossfade
FONTS = '/home/claude/fonts'
ROOT = '/home/claude/w'

def sh(*a, **k):
    subprocess.run(a, check=True, **k)

def asr_words(s):
    return [w for d in json.load(open(os.path.join(ROOT, ASR[s]))) for w in d['w']]

def read_audio(path, a, d, sr=44100):
    p = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{a:.3f}', '-t', f'{d:.3f}', '-i', path, '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.float32)

def seg_bounds(src, a, b):
    segs = [d for d in json.load(open(os.path.join(ROOT, ASR[src]))) if d['t'].strip()]
    first = next(d for d in segs if d['s'] >= a - 0.6)
    last = [d for d in segs if d['s'] < b][-1]
    return first['s'] - 0.12, last['e'] + 0.18

def snap(src, t, side):
    """move a cut point to the quietest 40ms window within +-0.22s (never into speech of the kept side much)"""
    x = read_audio(SRC[src], max(0, t - 0.25), 0.5, 8000)
    win = 320; best = None
    for i in range(0, len(x) - win, 40):
        e = float(np.sqrt(np.mean(x[i:i+win] ** 2)) + 1e-9)
        c = max(0, t - 0.25) + (i + win / 2) / 8000
        if abs(c - t) > 0.22: continue
        # slight bias: for starts prefer earlier, for ends prefer later (keep words whole)
        bias = (t - c) if side == 'start' else (c - t)
        score = e * (1.0 - 0.6 * max(-1, min(1, bias / 0.22)))
        if best is None or score < best[0]: best = (score, c)
    return best[1] if best else t

def mono(al):
    """force word times to be non-decreasing (corrected text may reorder words vs ASR)"""
    out = []; last = -1e9
    for t0, t1, w in al:
        t0 = max(t0, last + 0.02); t1 = max(t1, t0 + 0.08)
        out.append([t0, t1, w]); last = t0
    return out

def load_fix(path):
    fx = {}; cur = None
    for line in open(path):
        line = line.strip()
        if line.startswith('@'): cur = line[1:]; fx[cur] = ''
        elif line and cur is not None: fx[cur] += ' ' + line
    return fx

def zoom_expr(d, k, punches):
    drift = f"(1.02+0.045*{'t' if k % 2 == 0 else f'({d:.3f}-t)'}/{d:.3f})"
    terms = []
    for te in punches:
        r = f"clip((t-{te-0.9:.3f})/0.9,0,1)"; f = f"clip(({te+2.4:.3f}-t)/1.5,0,1)"
        b = f"min({r},{f})"
        terms.append(f"0.13*({b})*({b})*(3-2*({b}))")
    return drift + ('+' + '+'.join(terms) if terms else '')

def broll_pick(rng):
    lib = [b for b in json.load(open(os.path.join(ROOT, 'broll_lib.json'))) if 60 < b['bright'] < 170 and b['motion'] < 6]
    return rng.choice(lib)

def render_piece(od, key, src, a, b, k, punches, broll):
    vf = []
    if src in CROP:
        cw, ch, cx, cy = CROP[src]; vf.append(f'crop={cw}:{ch}:{cx}:{cy}')
    d = b - a
    Z = zoom_expr(d, k, punches)
    vf += [render2.CLARITY, render2.GR['halal'], f"scale=w='trunc({W}*({Z})/2)*2':h='trunc({H}*({Z})/2)*2':eval=frame:flags=bicubic",
           f"crop={W}:{H}:(in_w-{W})/2:(in_h-{H})*0.40",
           'unsharp=5:5:0.6:5:5:0', 'vignette=PI/5', f'fps={FPS}', 'format=yuv420p']
    out = f'{od}/v_{key}.mp4'
    if os.path.exists(out): return out
    if broll:
        bl = broll
        bsrc = render2.BR[bl['src']]
        fc = (f"[0:v]{','.join(vf)}[m];"
              f"[1:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{render2.GR['halal']},vignette=PI/5,fps={FPS},"
              f"trim=0:3.4,setpts=PTS-STARTPTS,format=yuva420p,fade=in:st=0:d=0.01:alpha=1,fade=out:st=2.9:d=0.5:alpha=1[bb];"
              f"[m][bb]overlay=eof_action=pass:enable='lt(t,3.4)',format=yuv420p[o]")
        sh('ffmpeg', '-v', 'error', '-y', '-ss', f'{a:.3f}', '-t', f'{d:.3f}', '-i', SRC[src], '-ss', f"{bl['t']:.2f}", '-t', '3.6', '-i', bsrc,
           '-filter_complex', fc, '-map', '[o]', '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '15', out)
    else:
        sh('ffmpeg', '-v', 'error', '-y', '-ss', f'{a:.3f}', '-t', f'{d:.3f}', '-i', SRC[src], '-vf', ','.join(vf), '-an',
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '15', out)
    return out

def piece_audio(od, key, src, a, b):
    out = f'{od}/a_{key}.wav'
    if os.path.exists(out): return out
    mix = f'{od}/m_{key}.wav'
    sh('ffmpeg', '-v', 'error', '-y', '-ss', f'{a-0.5:.3f}', '-t', f'{b-a+1.0:.3f}', '-i', SRC[src], '-ac', '2', '-ar', '44100', mix)
    voc = f'{od}/s_{key}.wav'
    if src in NOSEP:
        sh('ffmpeg', '-v', 'error', '-y', '-i', mix, '-af', 'highpass=f=70,afftdn=nf=-30', voc)
    else:
        sh('python3', os.path.join(ROOT, 'sep.py'), mix, voc)
    # trim the 0.5s pads, voice polish, 12ms edge fades
    d = b - a
    sh('ffmpeg', '-v', 'error', '-y', '-i', voc, '-af',
       f'atrim=0.5:{0.5+d:.3f},asetpts=PTS-STARTPTS,highpass=f=75,equalizer=f=3000:t=q:w=1:g=2,acompressor=threshold=0.1:ratio=2.5:attack=8:release=120,'
       f'afade=t=in:d=0.012,afade=t=out:st={d-0.012:.3f}:d=0.012', '-ar', '44100', '-ac', '2', out)
    os.remove(mix)
    return out

def make_watermark(path):
    logo = Image.open(U + '/imanivated/Logo PNG White.png').convert('RGBA')
    lh = 54; logo = logo.resize((int(logo.width * lh / logo.height), lh), Image.LANCZOS)
    f = ImageFont.truetype(FONTS + '/Montserrat-SemiBold.ttf', 22)
    txt = '@IMANIVATED'
    tw = int(f.getlength(txt)) + 2 * 3 * len(txt)
    im = Image.new('RGBA', (logo.width + 14 + tw, lh), (0, 0, 0, 0))
    im.paste(logo, (0, 0), logo)
    dr = ImageDraw.Draw(im); x = logo.width + 14
    for ch in txt:
        dr.text((x, lh / 2), ch, font=f, fill=(255, 255, 255, 255), anchor='lm'); x += f.getlength(ch) + 3
    a = np.array(im); a[..., 3] = (a[..., 3] * 0.55).astype(np.uint8)
    Image.fromarray(a).save(path)

def make_endcard(path, dur=6.0):
    """horizontal follow/subscribe outro"""
    od = os.path.dirname(path); fr = f'{od}/endcard.png'
    im = Image.new('RGB', (W, H), (8, 12, 14))
    g = np.zeros((H, W, 3), np.float32)
    yy, xx = np.mgrid[0:H, 0:W]; r = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H / 2) / H) ** 2)
    g[..., 0] = 14 + 26 * np.clip(1 - r * 1.8, 0, 1); g[..., 1] = 20 + 34 * np.clip(1 - r * 1.8, 0, 1); g[..., 2] = 22 + 30 * np.clip(1 - r * 1.8, 0, 1)
    im = Image.fromarray(g.astype(np.uint8))
    logo = Image.open(U + '/imanivated/Logo PNG White.png').convert('RGBA')
    lh = 190; logo = logo.resize((int(logo.width * lh / logo.height), lh), Image.LANCZOS)
    im.paste(logo, ((W - logo.width) // 2, 300), logo)
    dr = ImageDraw.Draw(im)
    f1 = ImageFont.truetype(FONTS + '/Montserrat-ExtraBold.ttf', 64); f2 = ImageFont.truetype(FONTS + '/Montserrat-SemiBold.ttf', 34)
    dr.text((W / 2, 580), '@IMANIVATED', font=f1, fill=(255, 255, 255), anchor='mm')
    dr.text((W / 2, 660), 'SUBSCRIBE FOR DAILY REMINDERS', font=f2, fill=(69, 232, 255), anchor='mm')
    # subscribe pill
    bw, bh = 300, 70; bx, by = (W - bw) // 2, 730
    dr.rounded_rectangle((bx, by, bx + bw, by + bh), radius=35, fill=(220, 30, 40))
    dr.text((W / 2, by + bh / 2), 'SUBSCRIBE', font=ImageFont.truetype(FONTS + '/Montserrat-ExtraBold.ttf', 30), fill=(255, 255, 255), anchor='mm')
    im.save(fr)
    sh('ffmpeg', '-v', 'error', '-y', '-loop', '1', '-t', f'{dur}', '-i', fr, '-vf',
       f"scale=w='trunc({W}*(1+0.03*t/{dur})/2)*2':h='trunc({H}*(1+0.03*t/{dur})/2)*2':eval=frame,crop={W}:{H},noise=c0s=8:c0f=t+u,fade=in:d=0.6,fade=out:st={dur-0.8}:d=0.8,fps={FPS},format=yuv420p",
       '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '15', path)

def music_bed(od, total):
    """chain the BG tracks (cycled) with 3s crossfades to cover total seconds"""
    out = f'{od}/music.wav'
    tracks = [f'{ROOT}/mus/m{i}.wav' for i in (1, 2, 3, 4)]
    ins = []; L = 0; i = 0
    durs = {t: float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', t], capture_output=True, text=True).stdout) for t in tracks}
    while L < total + 4:
        t = tracks[i % len(tracks)]; ins.append(t); L += durs[t] - (3 if ins[1:] else 0); i += 1
    args = []
    for t in ins: args += ['-i', t]
    fc = ''; last = '[0:a]'
    for j in range(1, len(ins)):
        fc += f'{last}[{j}:a]acrossfade=d=3:c1=tri:c2=tri[x{j}];'; last = f'[x{j}]'
    fc += f'{last}atrim=0:{total:.3f},afade=t=in:d=1.5,afade=t=out:st={total-4:.3f}:d=4,aformat=sample_rates=44100:channel_layouts=stereo[m]'
    sh('ffmpeg', '-v', 'error', '-y', *args, '-filter_complex', fc, '-map', '[m]', out)
    return out

def rms_db(path, active=False):
    x, sr = sf.read(path, dtype='float32'); x = x.mean(1) if x.ndim > 1 else x
    fr = x[: len(x) // 4410 * 4410].reshape(-1, 4410); e = np.sqrt((fr ** 2).mean(1) + 1e-12)
    if active: e = e[e > np.percentile(e, 40)]
    return 20 * np.log10(np.sqrt((e ** 2).mean()))

def main(vd):
    cfg = json.load(open(f'{vd}/cfg.json'))
    fx = load_fix(f'{vd}/fix.txt')
    od = f'{vd}/work'; os.makedirs(od, exist_ok=True)
    rng = random.Random(cfg.get('seed', 7))
    chapters = cfg['chapters']; punch = [p.lower() for p in cfg.get('punch', [])]
    used_br = set()
    chap_files = []; all_words = []; chap_durs = []
    k_global = 0
    for c, ch in enumerate(chapters):
        vparts, aparts, cwords, t_acc = [], [], [], 0.0
        for p, pc in enumerate(ch):
            src, a, b = pc[:3]
            key = f'{c}.{p}'
            if cfg.get('segsnap') and 'raw' not in pc[3:]: a, b = seg_bounds(src, a, b)
            a2, b2 = snap(src, a, 'start'), snap(src, b, 'end')
            # words of the piece (aligned corrected text)
            ws = [w for w in asr_words(src) if w[0] >= a - 0.05 and w[1] <= b + 0.3]
            al = mono(caps.align(ws, fx[key].strip()))
            loc = [[max(0.0, x[0] - a2), min(b2 - a2, max(0.05, x[1] - a2)), x[2]] for x in al]
            # punch-in landings at chosen phrase ends
            txt = [caps.norm(x[2]) for x in loc]; pts = []
            for ph in punch:
                pw = [caps.norm(q) for q in ph.split()]
                for i in range(len(txt) - len(pw) + 1):
                    if txt[i:i+len(pw)] == pw: pts.append(loc[i+len(pw)-1][1])
            pts = sorted(t for t in pts if 1.2 < t < (b2 - a2) - 0.5)
            br = None
            if p == 0 and c in cfg.get('broll_chapters', []):
                while True:
                    br = broll_pick(rng)
                    if (br['src'], br['t']) not in used_br: used_br.add((br['src'], br['t'])); break
                pts = [t for t in pts if t > 6]
            vparts.append(render_piece(od, key, src, a2, b2, k_global, pts, br)); k_global += 1
            aparts.append(piece_audio(od, key, src, a2, b2))
            cwords += [[x[0] + t_acc, x[1] + t_acc, x[2]] for x in loc]
            t_acc += b2 - a2
            print('piece', key, round(b2 - a2, 1), 'punch', [round(t, 1) for t in pts], 'broll' if br else '', flush=True)
        # join pieces of chapter
        cv, ca = f'{od}/c{c}.mp4', f'{od}/c{c}.wav'
        with open(f'{od}/c{c}.txt', 'w') as f:
            for v in vparts: f.write(f"file '{os.path.abspath(v)}'\n")
        sh('ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', f'{od}/c{c}.txt', '-c', 'copy', cv)
        args = []
        for x in aparts: args += ['-i', x]
        sh('ffmpeg', '-v', 'error', '-y', *args, '-filter_complex', ''.join(f'[{i}:a]' for i in range(len(aparts))) + f'concat=n={len(aparts)}:v=0:a=1[a]', '-map', '[a]', ca)
        dv = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', cv], capture_output=True, text=True).stdout)
        chap_files.append((cv, ca)); chap_durs.append(dv)
        off = sum(chap_durs[:-1]) - XF * (len(chap_durs) - 1)
        all_words += [[x[0] + off, x[1] + off, x[2]] for x in cwords]
    # ---- final assembly ----
    total = sum(chap_durs) - XF * (len(chap_durs) - 1)
    END = 6.0
    endc = f'{od}/endcard.mp4'; make_endcard(endc, END)
    wm = f'{od}/wm.png'; make_watermark(wm)
    # captions
    Uu = caps.units([[a, b, w] for a, b, w in all_words], maxw=3)
    stl = dict(caps.STYLES['accent']); stl['size'] = 66
    ass = f'{od}/caps.ass'
    caps.build_ass(Uu, stl, W, H, accent='&H00FFE845&', path=ass)
    s = open(ass).read()
    s = re.sub(r'\\pos\((\d+),(\d+)\)', lambda m: f'\\pos({m.group(1)},{int(m.group(2)) + 345})', s)
    open(ass, 'w').write(s)
    # video xfade chain
    args = []
    for v, _ in chap_files: args += ['-i', v]
    args += ['-i', endc, '-i', wm]
    n = len(chap_files); fc = ''; last = '[0:v]'; acc = chap_durs[0]
    for i in range(1, n):
        fc += f'{last}[{i}:v]xfade=transition=fade:duration={XF}:offset={acc - XF:.3f}[v{i}];'; last = f'[v{i}]'; acc += chap_durs[i] - XF
    fc += f"{last}subtitles={ass}:fontsdir={FONTS}[sv];[sv][{n+1}:v]overlay=W-w-48:44,noise=c0s=11:c0f=t+u[wv];"
    fc += f"[wv][{n}:v]xfade=transition=fade:duration=0.8:offset={total - 0.8:.3f},format=yuv420p[vo]"
    vid = f'{od}/video.mp4'
    # keep the delivered file under ~370 MB (chat upload limit 400 MB)
    vr = min(9000, int((365 * 8 * 1000) / (total + END) - 200))
    sh('ffmpeg', '-v', 'error', '-y', *args, '-filter_complex', fc, '-map', '[vo]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
       '-maxrate', f'{vr}k', '-bufsize', f'{2*vr}k', '-r', str(FPS), vid)
    # voice chain
    args = []
    for _, a in chap_files: args += ['-i', a]
    fc = ''; last = '[0:a]'
    for i in range(1, n):
        fc += f'{last}[{i}:a]acrossfade=d={XF}:c1=tri:c2=tri[a{i}];'; last = f'[a{i}]'
    fc += f'{last}apad=pad_dur={END:.2f}[ao]'
    voice = f'{od}/voice.wav'
    sh('ffmpeg', '-v', 'error', '-y', *args, '-filter_complex', fc, '-map', '[ao]', '-ar', '44100', '-ac', '2', voice)
    full = total + END + 0.2
    mus = music_bed(od, full)
    # music level: ~0.8 of voice amplitude during speech
    gv = rms_db(voice, True); gm = rms_db(mus)
    mg = 10 ** (((gv + 20 * math.log10(cfg.get('music_ratio', 0.8))) - gm) / 20)
    mixw = f'{od}/mix.wav'
    sh('ffmpeg', '-v', 'error', '-y', '-i', voice, '-i', mus, '-filter_complex',
       f'[1:a]volume={mg:.4f}[m];[0:a]asplit=2[v][sc];[m][sc]sidechaincompress=threshold=0.08:ratio=1.5:attack=20:release=400[md];'
       f'[v][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.85:level=false[o]',
       '-map', '[o]', '-ar', '48000', mixw)
    final = f"{vd}/{cfg['out']}"
    sh('ffmpeg', '-v', 'error', '-y', '-i', vid, '-i', mixw, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', final)
    json.dump({'chapters': chap_durs, 'total': total + END}, open(f'{vd}/done.json', 'w'))
    print('DONE', final, round(total + END, 1), flush=True)

if __name__ == '__main__':
    main(sys.argv[1])

import json, os, sys, subprocess, math, re
import numpy as np, cv2, soundfile as sf
from track import track, SRC
import caps

W_ = '/home/claude/w/'
FONTS = '/home/claude/fonts'
MUS = {'m1': 'mus/m1.wav', 'm2': 'mus/m2.wav', 'm3': 'mus/m3.wav', 'm4': 'mus/m4.wav', 'm5': 'mus/m5.wav'}
MUS_ENTRY = {'m1': [24.26, 0.23], 'm2': [4.48, 17.0, 28.7], 'm3': [8.43, 19.53, 37.31], 'm4': [14.35, 24.78, 36.55], 'm5': [0.18]}
MUS_LUFS = {'m1': -20.5, 'm2': -21.5, 'm3': -24.0, 'm4': -19.5, 'm5': -21.0}   # target integrated level under -14 LUFS voice

GRADES = {
    'moody': "eq=contrast=1.10:brightness=-0.06:saturation=0.45:gamma=0.90,colorbalance=rs=-0.03:bs=0.04:rh=0.02:bh=-0.01,curves=all='0/0 0.14/0.05 0.5/0.44 1/0.94',vignette=PI/4.2",
    'bw': "hue=s=0,eq=contrast=1.18:brightness=-0.05:gamma=0.88,curves=all='0/0 0.16/0.04 0.62/0.6 1/0.98',vignette=PI/4.6",
    'cool': "eq=saturation=0.30:contrast=1.03:brightness=-0.035,colorbalance=bs=0.05:bm=0.035:bh=0.025:rh=-0.02:rm=-0.01,curves=all='0/0.01 0.5/0.46 1/0.92',vignette=PI/5.5",
    'warm': "eq=saturation=0.88:contrast=1.07:brightness=-0.03,colorbalance=rs=0.02:rm=0.035:rh=0.045:bs=-0.03:bm=-0.02:bh=-0.05,curves=all='0/0 0.1/0.05 0.55/0.5 1/0.92',vignette=PI/4.6",
    'comp': "hue=s=0,eq=contrast=1.28:brightness=-0.11:gamma=0.80,curves=all='0/0 0.2/0.03 0.6/0.5 1/0.92',vignette=PI/3.6",
}
CLARITY = "hqdn3d=1.2:1.2:4:4,unsharp=13:13:0.32:13:13:0"

def rr_mask(w, h, r, soft=1.5):
    m = np.zeros((h, w), np.float32)
    cv2.rectangle(m, (r, 0), (w - r, h), 1, -1); cv2.rectangle(m, (0, r), (w, h - r), 1, -1)
    for cx, cy in [(r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)]:
        cv2.circle(m, (cx, cy), r, 1, -1, lineType=cv2.LINE_AA)
    return cv2.GaussianBlur(m, (0, 0), soft)[..., None]

def circle_mask(d, soft=1.5):
    m = np.zeros((d, d), np.float32); cv2.circle(m, (d // 2, d // 2), d // 2 - 2, 1, -1, lineType=cv2.LINE_AA)
    return cv2.GaussianBlur(m, (0, 0), soft)[..., None]

# frame layouts on canvas: (content w, h, mask)
def layout(frame, CW, CH):
    if frame == 'full': return CW, CH, None
    if frame == 'rwin': return 920, 1480, rr_mask(920, 1480, 46)
    if frame == 'rect34': return 1080, 1440, None
    if frame == 'rsq': return 980, 980, rr_mask(980, 980, 52)
    if frame == 'band169': return 1080, 608, None
    if frame == 'band43': return 1080, 810, None
    if frame == 'fish': return 1000, 1000, circle_mask(1000)
    if frame == 'comp': return CW, CH, None

def fisheye_maps(d, k=0.32):
    yy, xx = np.mgrid[0:d, 0:d].astype(np.float32)
    nx = (xx - d / 2) / (d / 2); ny = (yy - d / 2) / (d / 2)
    r = np.sqrt(nx ** 2 + ny ** 2)
    f = 1 / (1 + k * r ** 2) * (1 + k)  # barrel: sample closer to centre near edges? keep centre ~1
    f = (1 - k * 0.5) + k * 0.5 * r ** 2
    mx = (nx * f * d / 2 + d / 2).astype(np.float32); my = (ny * f * d / 2 + d / 2).astype(np.float32)
    return mx, my

def asr_words(wav16):
    out = wav16 + '.json'
    if not os.path.exists(out):
        subprocess.run(['python3', 'asr.py', wav16, out, '2'], check=True, stdout=subprocess.DEVNULL)
    d = json.load(open(out))
    return [w for s in d for w in s['w']]

def music_bed(music, dur, entry, out, xf=1.5):
    a, sr = sf.read(MUS[music], dtype='float32', always_2d=True)
    # trim trailing silence
    e = np.abs(a).max(1); nz = np.where(e > 1e-3)[0]; a = a[:nz[-1] + 1] if len(nz) else a
    seg = a[int(entry * sr):]
    need = int((dur + 0.5) * sr); bed = seg.copy(); n = int(xf * sr)
    loop = a[int(MUS_ENTRY[music][0] * sr):] if music != 'm5' else a
    while len(bed) < need:  # loop with a crossfade so short tracks cover the whole clip
        f = np.linspace(0, 1, n)[:, None]
        bed = np.concatenate([bed[:-n], bed[-n:] * (1 - f) + loop[:n] * f, loop[n:]])
    sf.write(out, bed[:need], sr)

def make_audio(cid, pieces, music, dur_hint=None, entry=None):
    """voice from separated stems -> processed voice; mix with music; master."""
    od = f'out/{cid}'; os.makedirs(od, exist_ok=True)
    vparts = [f'aud/{cid}_{i}_voc.wav' for i in range(len(pieces))]
    # concat voice
    v = np.concatenate([sf.read(p, dtype='float32', always_2d=True)[0].mean(1) for p in vparts])
    sf.write(f'{od}/voice_raw.wav', v, 44100)
    dur = len(v) / 44100
    # voice chain
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f'{od}/voice_raw.wav', '-af',
                    'highpass=f=75,lowpass=f=15000,afftdn=nr=6:nf=-45,acompressor=threshold=0.09:ratio=2.6:attack=8:release=160:makeup=1.5,equalizer=f=3200:t=q:w=1.2:g=2,equalizer=f=220:t=q:w=1:g=-1.5,afade=t=in:d=0.04,afade=t=out:st=%f:d=0.12' % max(0, dur - 0.12),
                    '-ar', '48000', '-ac', '1', f'{od}/voice_p.wav'], check=True)
    vI = loud(f'{od}/voice_p.wav')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f'{od}/voice_p.wav', '-af', f'volume={-14 - vI:.2f}dB', '-ac', '2', f'{od}/voice.wav'], check=True)
    # music
    if entry is None: entry = MUS_ENTRY[music][0]
    music_bed(music, dur, entry, f'{od}/bed.wav')
    mI = loud(f'{od}/bed.wav')
    g = MUS_LUFS[music] - mI
    fade_out = f',afade=t=out:st={max(0, dur - 2.0):.2f}:d=2.0'
    fc = (f"[1:a]atrim=0:{dur:.3f},volume={g:.2f}dB,afade=t=in:d=0.4{fade_out},apad=whole_dur={dur:.3f}[m];"
          f"[0:a]asplit=2[v1][v2];[m][v2]sidechaincompress=threshold=0.035:ratio=3.5:attack=25:release=450:makeup=1[md];"
          f"[v1][md]amix=inputs=2:normalize=0:duration=first[mx]")
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f'{od}/voice.wav', '-i', f'{od}/bed.wav', '-filter_complex', fc, '-map', '[mx]', '-ar', '48000', f'{od}/mix.wav'], check=True)
    I = loud(f'{od}/mix.wav')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f'{od}/mix.wav', '-af', f'volume={-13 - I:.2f}dB,alimiter=limit=0.78:attack=3:release=60:level=disabled', '-ar', '48000', '-c:a', 'pcm_s16le', f'{od}/final.wav'], check=True)
    # 16k voice for ASR
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f'{od}/voice_raw.wav', '-ac', '1', '-ar', '16000', f'{od}/voice16.wav'], check=True)
    return dur

def loud(path):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True).stderr
    return float(re.findall(r'I:\s+(-?[\d.]+) LUFS', r)[-1])

def zoom_curve(times, n, fps=30, amt=0.10):
    z = np.ones(n)
    t = np.arange(n) / fps
    for te in times:
        up = np.clip((t - (te - 1.1)) / 1.1, 0, 1); up = up * up * (3 - 2 * up)
        down = np.clip((t - (te + 1.4)) / 1.6, 0, 1); down = down * down * (3 - 2 * down)
        z = np.maximum(z, 1 + amt * (up - down))
    return z

def pick_zooms(words, dur, k=3):
    # sentence ends followed by pause, spread out
    cands = []
    for i, w in enumerate(words):
        if w[2][-1:] in '.!?':
            gap = words[i + 1][0] - w[1] if i + 1 < len(words) else 0
            if 4 < w[1] < dur - 3 and gap >= 0.3:
                cands.append((gap, w[1]))
    cands.sort(reverse=True)
    chosen = []
    for g, t in cands:
        if all(abs(t - c) > dur / (k + 1.5) for c in chosen):
            chosen.append(t)
        if len(chosen) >= k: break
    return sorted(chosen)

def render(cid, cfg, words_fixed=None, preview=False):
    pieces = cfg['pieces']
    vertical = cfg['frame'] != 'comp'
    CW, CH = (1080, 1920) if vertical else (1440, 1080)
    od = f'out/{cid}'; os.makedirs(od, exist_ok=True)
    dur = sum(b - a for _, a, b in pieces)
    fps = 30
    n_total = int(round(dur * fps))
    # words + captions
    words = cfg['words']
    stl = caps.STYLES[cfg['style']]
    U = caps.units([[a, b, w] for a, b, w in words], maxw=stl['n'], phrase=stl.get('phrase', False))
    caps.build_ass(U, stl, CW, CH, accent=cfg.get('accent', '&H002B8AFF&'), path=f'{od}/caps.ass')
    zt = cfg.get('zooms') if cfg.get('zooms') is not None else pick_zooms(words, dur, 3 if dur > 40 else 2)
    Z = zoom_curve(zt, n_total + 5, amt=cfg.get('zamt', 0.09))
    fw, fh, mask = layout(cfg['frame'], CW, CH)
    x0, y0 = (CW - fw) // 2, (CH - fh) // 2
    fish = fisheye_maps(fw) if cfg['frame'] == 'fish' else None
    # effects precompute
    rng = np.random.default_rng(abs(hash(cid)) % 2**32)
    leak = np.zeros((CH // 4, CW // 4, 3), np.float32)
    lw, lh = CW // 4, CH // 4
    yy, xx = np.mgrid[0:lh, 0:lw]
    def leak_frame(t):
        p = t / 1.3
        cxl = lw * (0.85 - 0.5 * p); cyl = lh * (0.2 + 0.25 * p)
        g = np.exp(-(((xx - cxl) / (lw * 0.55)) ** 2 + ((yy - cyl) / (lh * 0.45)) ** 2))
        a = (np.sin(min(p, 1) * math.pi) ** 1.5) * 0.30
        col = np.array([95, 170, 255], np.float32) if cfg['grade'] in ('warm', 'moody') else np.array([215, 215, 225], np.float32)
        img = (g[..., None] * col * a).astype(np.float32)
        return cv2.resize(img, (CW, CH), interpolation=cv2.INTER_LINEAR)
    lmask = np.zeros((CH, CW, 1), np.float32)
    lmask[y0:y0 + fh, x0:x0 + fw] = mask if mask is not None else 1
    dust_times = cfg.get('dust', [dur * 0.36, dur * 0.72])
    parts = [(rng.uniform(0, CW, 70), rng.uniform(0, CH, 70), rng.uniform(0.6, 2.2, 70), rng.uniform(-12, 12, 70), rng.uniform(-30, -8, 70)) for _ in dust_times]
    # encoder
    sub = f"subtitles={od}/caps.ass:fontsdir={FONTS}"
    sharpen = "unsharp=5:5:0.55:5:5:0"
    if cfg['style'] == 'overlayword':
        fc = (f"[0:v]{sharpen},format=gbrp[b];color=c=black:s={CW}x{CH}:r=30:d={dur+1:.2f},format=rgb24,{sub},rgbashift=rh=-4:bh=4:edge=smear,format=gbrp[t];"
              f"[b][t]blend=all_mode=difference:all_opacity=0.92,format=yuv420p[v]")
    else:
        fc = f"[0:v]{sharpen},{sub},format=yuv420p[v]"
    outp = f'{od}/{cid}.mp4' if not preview else f'{od}/{cid}_prev.mp4'
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{CW}x{CH}', '-r', '30', '-i', '-',
                            '-i', f'{od}/final.wav', '-filter_complex', fc, '-map', '[v]', '-map', '1:a',
                            '-c:v', 'libx264', '-profile:v', 'high', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', '30',
                            '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', '-t', f'{dur:.3f}', outp], stdin=subprocess.PIPE)
    fi = 0
    for (src, a, b) in pieces:
        tr = track(src, a, b)
        tx, ty, tsz = np.array(tr['x']), np.array(tr['y']), np.array(tr['s'])
        vf = []
        if src.startswith('h'): vf.append('delogo=x=1092:y=1:w=186:h=66')
        if src.startswith('h'): vf.append('eq=gamma=1.4:brightness=0.03:contrast=0.96')
        else: vf.append('eq=gamma=0.92:brightness=-0.025')
        vf += [CLARITY, GRADES[cfg['grade']], 'fps=30']
        dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f'{a:.3f}', '-t', f'{b-a:.3f}', '-i', SRC[src], '-vf', ','.join(vf),
                                '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE)
        SW, SH = 1280, 720
        np_ = int(round((b - a) * fps)); k = 0
        while k < np_:
            buf = dec.stdout.read(SW * SH * 3)
            if len(buf) < SW * SH * 3: break
            src_img = np.frombuffer(buf, np.uint8).reshape(SH, SW, 3)
            t = k / fps; T = fi / fps
            ti = min(t * tr['fps'], len(tx) - 1)
            i0 = int(ti); fr = ti - i0; i1 = min(i0 + 1, len(tx) - 1)
            fxc = tx[i0] * (1 - fr) + tx[i1] * fr; fyc = ty[i0] * (1 - fr) + ty[i1] * fr; fs = tsz[i0] * (1 - fr) + tsz[i1] * fr
            z = Z[min(fi, len(Z) - 1)]
            asp = fw / fh
            base_h = SH if asp < 1.25 else min(SH, SW / asp)
            ch_ = base_h / z / cfg.get('zbase', 1.0); cw_ = ch_ * asp
            if cw_ > SW: cw_ = SW; ch_ = cw_ / asp
            # face placement: centre x on face; y so face sits ~36% from top (vertical) / 40% (wide)
            fy_target = 0.36 if asp < 0.8 else 0.42
            cx = fxc; cy = fyc + ch_ * (0.5 - fy_target)
            cx = np.clip(cx, cw_ / 2, SW - cw_ / 2); cy = np.clip(cy, ch_ / 2, SH - ch_ / 2)
            s = fw / cw_
            M = np.array([[s, 0, -(cx - cw_ / 2) * s], [0, s, -(cy - ch_ / 2) * s]], np.float32)
            content = cv2.warpAffine(src_img, M, (fw, fh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
            if fish is not None:
                content = cv2.remap(content, fish[0], fish[1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            if mask is None and fw == CW and fh == CH:
                canvas = content.astype(np.float32) if (T < 1.3 or any(dt <= T <= dt + 1.5 for dt in dust_times)) else content
            else:
                canvas = np.zeros((CH, CW, 3), np.float32)
                c = content.astype(np.float32)
                if mask is not None: c = c * mask
                canvas[y0:y0 + fh, x0:x0 + fw] = c
            # effects
            if T < 1.3:
                canvas = canvas.astype(np.float32)
                L = leak_frame(T) * lmask
                canvas = 255 - (255 - canvas) * (1 - L / 255)  # screen
            for (dt, P) in zip(dust_times, parts):
                if dt <= T <= dt + 1.5:
                    canvas = canvas.astype(np.float32)
                    pa = math.sin((T - dt) / 1.5 * math.pi) * 0.55
                    layer = np.zeros((CH, CW), np.float32)
                    px = (P[0] + P[3] * (T - dt)) % CW; py = (P[1] + P[4] * (T - dt)) % CH
                    for X, Y, R in zip(px, py, P[2]):
                        cv2.circle(layer, (int(X), int(Y)), int(round(R)), 210, -1, lineType=cv2.LINE_AA)
                    layer = cv2.GaussianBlur(layer, (0, 0), 1.0)
                    layer *= lmask[..., 0]
                    canvas = canvas + layer[..., None] * pa
            out = np.clip(canvas, 0, 255).astype(np.uint8) if canvas.dtype != np.uint8 else canvas
            enc.stdin.write(out.tobytes())
            k += 1; fi += 1
        dec.stdout.close(); dec.wait()
    # pad if short
    while fi < n_total:
        enc.stdin.write(out.tobytes()); fi += 1
    enc.stdin.close(); enc.wait()
    return outp

if __name__ == '__main__':
    pass

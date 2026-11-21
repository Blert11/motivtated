"""Append a 3.2s follow outro to a clip and remix audio with louder music.
usage: python3 outro.py CID  -> out/CID/CID_o.mp4"""
import sys, json, os, subprocess, numpy as np, cv2, soundfile as sf
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, '/home/claude/w')
import render as R

L = 3.2; FPS = 30; MUSIC_LUFS = -18.5
F = '/home/claude/fonts/'
LOGO = '/mnt/user-data/uploads/imanivated/Logo PNG White.png'

def sm(v): v = min(1, max(0, v)); return v * v * (3 - 2 * v)
def eo(v): v = min(1, max(0, v)); return 1 - (1 - v) ** 3

def rgba(im):
    a = np.asarray(im).astype(np.float32) / 255.
    return a[..., 2::-1].copy(), a[..., 3:4].copy()

def paste(cv, rgb, al, cx, cy, op=1.0, scale=1.0, blur=0):
    if op <= 0.003: return
    if scale != 1.0:
        h, w = rgb.shape[:2]; nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        rgb = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR); al = cv2.resize(al, (nw, nh))[..., None]
    if blur > 0.3:
        k = int(blur * 3) * 2 + 1
        rgb = cv2.GaussianBlur(rgb, (k, k), blur); al = cv2.GaussianBlur(al, (k, k), blur)[..., None]
    h, w = rgb.shape[:2]; x, y = int(cx - w / 2), int(cy - h / 2)
    H, W = cv.shape[:2]; xs, ys, xe, ye = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if xe <= xs or ye <= ys: return
    r = rgb[ys - y:ye - y, xs - x:xe - x]; a = al[ys - y:ye - y, xs - x:xe - x] * op
    cv[ys:ye, xs:xe] = cv[ys:ye, xs:xe] * (1 - a) + r * 255 * a

def text_img(s, font, size, sp=0.0, fill=(255, 255, 255, 255)):
    f = ImageFont.truetype(F + font, size); ws = [f.getlength(c) for c in s]
    tw = int(sum(ws) + sp * size * (len(s) - 1)) + 8; asc, desc = f.getmetrics()
    im = Image.new('RGBA', (tw, asc + desc + 8), (0, 0, 0, 0)); d = ImageDraw.Draw(im); x = 4
    for c, w in zip(s, ws): d.text((x, 4), c, font=f, fill=fill); x += w + sp * size
    return im

def pill(label, w, h, bg, fg, font='Montserrat-Bold.ttf', size=None, outline=None):
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=bg, outline=outline, width=3 if outline else 0)
    size = size or int(h * 0.42); f = ImageFont.truetype(F + font, size)
    tw = f.getlength(label); asc, desc = f.getmetrics()
    d.text(((w - tw) / 2, (h - asc - desc) / 2 + 1), label, font=f, fill=fg)
    return im

def build_outro(cid, src, CW, CH):
    od = f'out/{cid}'
    # background: last frame, heavily blurred and darkened
    dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', src], capture_output=True, text=True).stdout)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{max(0, dur - 0.08):.3f}', '-i', src, '-frames:v', '1', f'{od}/last.png'], check=True)
    last = cv2.imread(f'{od}/last.png').astype(np.float32)
    bg = cv2.GaussianBlur(last, (0, 0), 38) * 0.28
    u = min(CW, CH) / 1080.
    lg = Image.open(LOGO).convert('RGBA'); lh = int(250 * u); lg = lg.resize((int(lg.width * lh / lg.height), lh), Image.LANCZOS)
    LG = rgba(lg)
    handle = '@IMANIVATED'; hs = int(58 * u); hf = ImageFont.truetype(F + 'Montserrat-SemiBold.ttf', hs)
    letters = [rgba(text_img(c, 'Montserrat-SemiBold.ttf', hs)) for c in handle]
    lw = [hf.getlength(c) for c in handle]; sp = hs * 0.22; total = sum(lw) + sp * (len(handle) - 1)
    sub = rgba(text_img('FOLLOW FOR DAILY REMINDERS', 'Montserrat-Medium.ttf', int(30 * u), sp=0.28, fill=(255, 255, 255, 200)))
    pw, ph = int(330 * u), int(92 * u)
    P1 = rgba(pill('Follow', pw, ph, (255, 255, 255, 255), (15, 15, 15, 255)))
    P2 = rgba(pill('Following', pw, ph, (255, 255, 255, 0), (255, 255, 255, 255), font='Montserrat-SemiBold.ttf', outline=(255, 255, 255, 230)))
    cx = CW / 2; cy = CH / 2 - 120 * u
    frames = []
    n = int(L * FPS)
    for i in range(n):
        t = i / FPS; cv = bg.copy()
        # crossfade in from the last frame of the clip
        k0 = sm(t / 0.35); cv = last * (1 - k0) + cv * k0
        # logo: blur-in + scale
        a = eo((t - 0.15) / 0.55); paste(cv, *LG, cx, cy, op=a, scale=0.86 + 0.14 * a, blur=(1 - a) * 12)
        # handle letter by letter
        x = cx - total / 2; ty = cy + lh * 0.5 + 70 * u
        for j, (L_, w) in enumerate(zip(letters, lw)):
            b = eo((t - 0.55 - j * 0.035) / 0.35)
            paste(cv, *L_, x + w / 2, ty + (1 - b) * 22 * u, op=b, blur=(1 - b) * 6)
            x += w + sp
        b = eo((t - 1.0) / 0.4); paste(cv, *sub, cx, ty + 62 * u, op=b * 0.9, blur=(1 - b) * 4)
        # follow button: pop in, tap at 2.05s, becomes Following
        py = ty + 175 * u
        p = eo((t - 1.15) / 0.35)
        tap = t - 2.05
        if tap < 0:
            paste(cv, *P1, cx, py, op=p, scale=0.8 + 0.2 * p)
        else:
            press = 1 - 0.08 * np.sin(min(1, tap / 0.18) * np.pi)
            sw = sm(tap / 0.22)
            paste(cv, *P1, cx, py, op=1 - sw, scale=press)
            paste(cv, *P2, cx, py, op=sw, scale=press)
            # tap ripple
            if tap < 0.45:
                r = int((20 + tap * 260) * u); ov = cv.copy()
                cv2.circle(ov, (int(cx + pw * 0.18), int(py + ph * 0.1)), r, (255, 255, 255), -1, cv2.LINE_AA)
                al = 0.28 * (1 - tap / 0.45); cv = cv * (1 - al) + ov * al
        # final fade
        cv = cv * (1 - sm((t - (L - 0.35)) / 0.35))
        frames.append(np.clip(cv, 0, 255).astype(np.uint8))
    return frames

def ratio(od):
    v, _ = sf.read(f'{od}/voice.wav'); m, _ = sf.read(f'{od}/mus2.wav'); n = min(len(v), len(m))
    v = v[:n].mean(1); m = m[:n].mean(1); w = 4800; k = n // w
    vr = np.sqrt((v[:k*w].reshape(k, w)**2).mean(1)); mr = np.sqrt((m[:k*w].reshape(k, w)**2).mean(1))
    sp = vr > vr.max() * 0.1
    return float(np.median(mr[sp] / (vr[sp] + 1e-9)))

TARGET = 0.8

def remix(cid, cfg, dur, adj=0.0, it=0):
    od = f'out/{cid}'; music = cfg['music']; entry = cfg.get('entry') or R.MUS_ENTRY[music][0]
    tot = dur + L
    R.music_bed(music, tot, entry, f'{od}/bed2.wav')
    mI = R.loud(f'{od}/bed2.wav'); g = MUSIC_LUFS - mI + adj
    fc = (f"[1:a]atrim=0:{tot:.3f},volume={g:.2f}dB,afade=t=in:d=0.4,afade=t=out:st={tot - 1.6:.2f}:d=1.6[m];"
          f"[0:a]apad=whole_dur={tot:.3f},asplit=2[v1][v2];[m][v2]sidechaincompress=threshold=0.08:ratio=1.5:attack=40:release=500:makeup=1,asplit=2[md][mo];"
          f"[v1][md]amix=inputs=2:normalize=0:duration=first[mx]")
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f'{od}/voice.wav', '-i', f'{od}/bed2.wav', '-filter_complex', fc, '-map', '[mx]', '-ar', '48000', f'{od}/mix2.wav', '-map', '[mo]', '-ar', '48000', f'{od}/mus2.wav'], check=True)
    r = ratio(od)
    if it < 2 and abs(r - TARGET) > 0.03:
        return remix(cid, cfg, dur, adj + 20 * np.log10(TARGET / max(r, 1e-3)), it + 1)
    print(cid, 'music/voice', round(r, 2))
    I = R.loud(f'{od}/mix2.wav')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f'{od}/mix2.wav', '-af', f'volume={-13.3 - I:.2f}dB,alimiter=limit=0.76:attack=2:release=60:level=disabled', '-ar', '48000', '-c:a', 'pcm_s16le', f'{od}/final2.wav'], check=True)

def main(cid):
    cfg = json.load(open('cfg2.json'))[cid]; od = f'out/{cid}'; src = f'{od}/{cid}.mp4'
    W, H = map(int, subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', src], capture_output=True, text=True).stdout.split(','))
    nfr = int(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-count_packets', '-show_entries', 'stream=nb_read_packets', '-of', 'csv=p=0', src], capture_output=True, text=True).stdout)
    dur = nfr / FPS
    if os.environ.get('AUDIO_ONLY'):
        remix(cid, cfg, dur); subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f'{od}/{cid}_o.mp4', '-i', f'{od}/final2.wav', '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest', '-movflags', '+faststart', f'{od}/tmp_o.mp4'], check=True)
        os.replace(f'{od}/tmp_o.mp4', f'{od}/{cid}_o.mp4'); print(cid, 'ok'); return
    frames = build_outro(cid, src, W, H)
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', '30', '-i', '-',
                            '-c:v', 'libx264', '-profile:v', 'high', '-level', '4.0', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', '30',
                            '-video_track_timescale', '15360', f'{od}/outro.mp4'], stdin=subprocess.PIPE)
    for f in frames: enc.stdin.write(f.tobytes())
    enc.stdin.close(); enc.wait()
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-an', '-c', 'copy', '-video_track_timescale', '15360', f'{od}/main_v.mp4'], check=True)
    open(f'{od}/cat.txt', 'w').write("file 'main_v.mp4'\nfile 'outro.mp4'\n")
    remix(cid, cfg, dur)
    if os.environ.get('AUDIO_ONLY'):
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f'{od}/{cid}_o.mp4', '-i', f'{od}/final2.wav', '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest', '-movflags', '+faststart', f'{od}/tmp_o.mp4'], check=True)
        os.replace(f'{od}/tmp_o.mp4', f'{od}/{cid}_o.mp4'); print(cid, 'ok'); return
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', f'{od}/cat.txt', '-i', f'{od}/final2.wav',
                    '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest',
                    '-movflags', '+faststart', f'{od}/{cid}_o.mp4'], check=True)
    print(cid, 'ok')

if __name__ == '__main__':
    for c in sys.argv[1:]: main(c)

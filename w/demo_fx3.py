import sys, subprocess, numpy as np, cv2, re
sys.argv += []
import render, caps, render2, fx3

cid = sys.argv[1] if len(sys.argv) > 1 else 'W7'
src, A, B = 'hr', 1451.84, 1484.34
locks = [(8.0, 3.6), (20.8, 3.6)]
out = f'/home/claude/w/demo_{cid}_halal.mp4'
SRCP = render2.SRC[src]; W, H, CW, CH, FPS = 1280, 720, 1080, 1920, 30
dur = B - A; n = int(round(dur * FPS))

w = render.asr_words(f'out/{cid}/voice16.wav'); w = caps.align(w, open(f'fix/{cid}.txt').read())
U = caps.units([[a, b, x] for a, b, x in w], maxw=2)
units = []
for k, u in enumerate(U):
    t1 = U[k + 1]['t0'] if k + 1 < len(U) and U[k + 1]['t0'] - u['t1'] < 0.6 else u['t1'] + 0.25
    parts = []
    for wd in u['words']:
        t = wd['text'] if wd['text'].endswith('SWT.') else re.sub(r'[.,;:!?]+$', '', wd['text'])
        parts.append(t + (' ' + wd['ar'] if wd.get('ar') else ''))
    units.append((u['t0'], t1, ' '.join(parts)))


def frames():
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', str(A), '-t', f'{dur:.3f}', '-i', SRCP, '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                         stdout=subprocess.PIPE)
    while True:
        buf = p.stdout.read(W * H * 3)
        if len(buf) < W * H * 3: break
        yield np.frombuffer(buf, np.uint8).reshape(H, W, 3)
    p.wait()


xs, ys, ss = fx3.face_track(frames(), n, W, H)
cx, cy, chh, lw = fx3.crop_params(xs, ys, ss, W, H, CW, CH, locks)
grade = fx3.HalalGrade(CW, CH); cap = fx3.HalalCaps(units, CW, CH)
wm = render2.AnimWM(CW, CH, 96, win=(0, CH))
enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{CW}x{CH}', '-r', '30', '-i', '-',
                        '-ss', '0', '-t', f'{dur:.3f}', '-i', f'out/{cid}/final2.wav',
                        '-filter_complex', '[0:v]unsharp=5:5:0.9:5:5:0,format=yuv420p[v]', '-map', '[v]', '-map', '1:a',
                        '-c:v', 'libx264', '-profile:v', 'high', '-preset', 'veryfast', '-crf', '18', '-c:a', 'aac', '-b:a', '192k',
                        '-ar', '48000', '-shortest', '-movflags', '+faststart', out], stdin=subprocess.PIPE)
for i, fr in enumerate(frames()):
    if i >= n: break
    t = i / FPS
    img = fx3.crop(fr, cx[i], cy[i], chh[i], CW, CH)
    img = grade(img)
    img = cap.draw(img, t)
    c = img.astype(np.float32); wm.draw(c, t); img = np.clip(c, 0, 255).astype(np.uint8)
    enc.stdin.write(img.tobytes())
enc.stdin.close(); enc.wait()
print(out, 'locks', locks)

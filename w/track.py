import cv2, numpy as np, subprocess, json, os, sys
SRC = {'ay': '/mnt/user-data/uploads/Downloads/vidssave.com Akhi Ayman Powerful Speech _ BG _ Halal Beats, Where you are 720P.mp4',
       'h0': '/mnt/user-data/uploads/motiviman/_work/hoblos_0.mp4',
       'h1': '/mnt/user-data/uploads/motiviman/_work/hoblos_1.mp4',
       'h2': '/mnt/user-data/uploads/motiviman/_work/hoblos_2.mp4'}
FF = cv2.CascadeClassifier('/home/claude/models/haarcascade_frontalface_default.xml')
PF = cv2.CascadeClassifier('/home/claude/models/haarcascade_profileface.xml')
FPS = 4
YN = cv2.FaceDetectorYN.create('/home/claude/models/yunet.onnx', '', (640, 360), 0.55, 0.3, 5000)

def track(src, a, b):
    key = f'track3/{src}_{a:.2f}_{b:.2f}.json'
    if os.path.exists(key):
        return json.load(open(key))
    os.makedirs('track3', exist_ok=True)
    W, H = 640, 360
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', str(a), '-t', str(b - a), '-i', SRC[src], '-vf', f'fps={FPS},scale={W}:{H},format=gray',
                          '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
    xs, ys, ss = [], [], []
    prev = None
    while True:
        buf = p.stdout.read(W * H)
        if len(buf) < W * H:
            break
        g = np.frombuffer(buf, np.uint8).reshape(H, W)
        img = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
        _, r = YN.detect(img)
        det = [] if r is None else [(float(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[-1])) for x in r]
        if det:
            if prev is not None:
                det.sort(key=lambda d: abs(d[0] + d[2] / 2 - prev) / 100 - d[4] * 2 - d[2] / 60)
            else:
                det.sort(key=lambda d: -(d[2] * d[4]))
            x, y, w, h, sc = det[0]
            cx = x + w / 2
            xs.append(cx * 2); ys.append((y + h / 2) * 2); ss.append(w * 2); prev = cx
            continue
        xs.append(np.nan); ys.append(np.nan); ss.append(np.nan)
    p.wait()
    xs, ys, ss = [np.array(v, float) for v in (xs, ys, ss)]
    n = len(xs)
    # outlier rejection: size and position vs rolling median
    ok = ~np.isnan(xs)
    if ok.sum() > 3:
        msz = np.nanmedian(ss)
        bad = ss < 0.6 * msz
        xs[bad] = np.nan; ys[bad] = np.nan; ss[bad] = np.nan
        for _ in range(2):
            ref = np.array([np.nanmedian(xs[max(0, i - 8):i + 9]) if np.any(~np.isnan(xs[max(0, i - 8):i + 9])) else np.nan for i in range(n)])
            bad = np.abs(xs - ref) > 160
            xs[bad] = np.nan; ys[bad] = np.nan; ss[bad] = np.nan
    def fill(v, default):
        ok = ~np.isnan(v)
        if ok.sum() == 0:
            return np.full(n, default)
        return np.interp(np.arange(n), np.where(ok)[0], v[ok])
    xs, ys, ss = fill(xs, 640), fill(ys, 300), fill(ss, 150)
    # robust smoothing: median then gaussian (sigma 1.2 s)
    def smooth(v, sig):
        k = int(FPS * 0.75) | 1
        vp = np.pad(v, k // 2, mode='edge')
        med = np.array([np.median(vp[i:i + k]) for i in range(n)])
        s = sig * FPS; r = int(3 * s) + 1
        ker = np.exp(-0.5 * (np.arange(-r, r + 1) / s) ** 2); ker /= ker.sum()
        return np.convolve(np.pad(med, r, mode='edge'), ker, 'valid')
    out = {'x': smooth(xs, 1.2).tolist(), 'y': smooth(ys, 1.5).tolist(), 's': smooth(ss, 2).tolist(), 'fps': FPS}
    json.dump(out, open(key, 'w'))
    return out

if __name__ == '__main__':
    P = json.load(open('pieces.json'))
    for c, v in P.items():
        for s, a, b in v:
            t = track(s, a, b)
            print(c, s, round(min(t['x'])), round(max(t['x'])), round(np.mean(t['y'])), round(np.mean(t['s'])), flush=True)

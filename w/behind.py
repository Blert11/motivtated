import cv2, numpy as np, onnxruntime as ort, subprocess, sys
from PIL import Image, ImageDraw, ImageFont
sess = ort.InferenceSession('/home/claude/models/u2net_human_seg.onnx', providers=['CPUExecutionProvider'])
def mask(img):
    x = cv2.resize(img, (320, 320))[:, :, ::-1].astype(np.float32) / 255.
    x = (x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    o = sess.run(None, {sess.get_inputs()[0].name: x.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
    o = (o - o.min()) / (o.max() - o.min() + 1e-6)
    m = cv2.resize(o, (img.shape[1], img.shape[0]))
    m = np.clip((m - 0.35) / 0.3, 0, 1)
    return cv2.GaussianBlur(m, (0, 0), 1.5)[..., None]
def frame(src, t, cx):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(t), '-i', src, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True).stdout
    im = np.frombuffer(raw, np.uint8).reshape(720, 1280, 3)
    w = 405; x0 = int(np.clip(cx - w / 2, 0, 1280 - w))
    c = im[:, x0:x0 + w]
    c = cv2.resize(c, (1080, 1920), interpolation=cv2.INTER_CUBIC)
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    c = cv2.addWeighted(c, 0.55, cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), 0.45, 0)
    c = np.clip((c.astype(np.float32) - 18) * 0.92, 0, 255).astype(np.uint8)
    return c
F = '/home/claude/fonts/'
def text_layer(lines):
    L = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    ys = []; tot = 0
    for txt, font, size, col in lines:
        f = ImageFont.truetype(F + font, size); bb = d.textbbox((0, 0), txt, font=f); ys.append((txt, f, bb, col)); tot += bb[3] - bb[1] + 10
    y = 960 - tot / 2
    for txt, f, bb, col in ys:
        w = bb[2] - bb[0]; d.text((540 - w / 2 - bb[0], y - bb[1]), txt, font=f, fill=col); y += bb[3] - bb[1] + 10
    return np.array(L).astype(np.float32) / 255.
def comp(img, lines, out):
    m = mask(img)
    T = text_layer(lines)
    a = T[..., 3:4] * (1 - m)  # text hidden where the person is
    o = img.astype(np.float32) * (1 - a) + (T[..., 2::-1] * 255) * a
    cv2.imwrite(out, o.astype(np.uint8))
AY = '/mnt/user-data/uploads/Downloads/vidssave.com Akhi Ayman Powerful Speech _ BG _ Halal Beats, Where you are 720P.mp4'
HO = '/mnt/user-data/uploads/motiviman/_work/hoblos_0.mp4'
a = frame(AY, 300, 700)
comp(a, [('the', 'PlayfairDisplay-Italic.ttf', 70, (255, 255, 255, 255)), ('DUNYA', 'Montserrat-Black.ttf', 250, (255, 255, 255, 255))], '/tmp/behind_a.jpg')
h = frame(HO, 470, 640)
comp(h, [('in complete', 'PlayfairDisplay-Italic.ttf', 78, (190, 240, 225, 255)), ('control', 'HelveticaNeueBoldItalic.otf', 220, (255, 255, 255, 255))], '/tmp/behind_h.jpg')

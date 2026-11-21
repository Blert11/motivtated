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

import track
AY = '/mnt/user-data/uploads/Downloads/vidssave.com Akhi Ayman Powerful Speech _ BG _ Halal Beats, Where you are 720P.mp4'

def frame2(src, t, z=1.35, lift=0):
    raw = subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',src,'-frames:v','1','-f','rawvideo','-pix_fmt','bgr24','-'],capture_output=True).stdout
    im = np.frombuffer(raw, np.uint8).reshape(720,1280,3).copy()
    _, r = track.YN.detect(cv2.resize(im,(640,360)))
    x,y,w,h = [float(v)*2 for v in r[0][:4]]
    fx, fy = x+w/2, y+h/2 + h*0.55 + lift   # centre frame on chin/neck
    ch = 720/z; cw = ch*9/16
    cx = np.clip(fx, cw/2, 1280-cw/2); cy = np.clip(fy, ch/2, 720-ch/2)
    c = im[int(cy-ch/2):int(cy+ch/2), int(cx-cw/2):int(cx+cw/2)]
    c = cv2.resize(c,(1080,1920),interpolation=cv2.INTER_CUBIC)
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    c = cv2.addWeighted(c,0.5,cv2.cvtColor(g,cv2.COLOR_GRAY2BGR),0.5,0)
    return np.clip((c.astype(np.float32)-25)*0.9,0,255).astype(np.uint8)
a = frame2(AY, 300)
comp(a, [('this', 'HelveticaNeueBold.otf', 90, (255,255,255,255)), ('dunya', 'HelveticaNeueHeavy.otf', 300, (255,255,255,255))], '/tmp/behind_a.jpg')
h = frame2('/mnt/user-data/uploads/motiviman/_work/hoblos_2.mp4', 1000, z=1.0)
comp(h, [('complete', 'HelveticaNeueHeavy.otf', 230, (255,255,255,255))], '/tmp/behind_h.jpg')


def frame4(src, t, W=1080, H=1440, ch=640, fxr=0.30, fyr=0.47):
    raw = subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',src,'-frames:v','1','-f','rawvideo','-pix_fmt','bgr24','-'],capture_output=True).stdout
    im = np.frombuffer(raw, np.uint8).reshape(720,1280,3).copy()
    _, r = track.YN.detect(cv2.resize(im,(640,360)))
    x,y,w,h = [float(v)*2 for v in r[0][:4]]
    fx, fy = x+w/2, y+h/2
    cw = ch*W/H
    x0 = np.clip(fx - cw*fxr, 0, 1280-cw); y0 = np.clip(fy - ch*fyr, 0, 720-ch)
    c = im[int(y0):int(y0+ch), int(x0):int(x0+cw)]
    c = cv2.resize(c,(W,H),interpolation=cv2.INTER_CUBIC)
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    c = cv2.addWeighted(c,0.5,cv2.cvtColor(g,cv2.COLOR_GRAY2BGR),0.5,0)
    c = np.clip((c.astype(np.float32)-25)*0.92,0,255).astype(np.uint8)
    canvas = np.zeros((1920,1080,3),np.uint8); canvas[240:240+H] = c
    return canvas
h = frame4('/mnt/user-data/uploads/motiviman/_work/hoblos_2.mp4', 1000, fxr=0.13, ch=560)
comp(h, [('in complete', 'HelveticaNeueBoldItalic.otf', 58, (235,235,235,255)), ('control', 'HelveticaNeueHeavy.otf', 158, (255,255,255,255))], '/tmp/behind_h.jpg')
a = frame4(AY, 300, fxr=0.13, ch=560)
comp(a, [('this', 'HelveticaNeueBoldItalic.otf', 70, (25,25,25,255)), ('dunya', 'HelveticaNeueHeavy.otf', 200, (25,25,25,255))], '/tmp/behind_a.jpg')

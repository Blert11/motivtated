import cv2, numpy as np, subprocess
exec(open('behind2.py').read().split("def frame4")[0])
def grab(src,t):
    raw = subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',src,'-frames:v','1','-f','rawvideo','-pix_fmt','bgr24','-'],capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(720,1280,3).copy()
def grade(c):
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    c = cv2.addWeighted(c,0.5,cv2.cvtColor(g,cv2.COLOR_GRAY2BGR),0.5,0)
    return np.clip((c.astype(np.float32)-25)*0.92,0,255).astype(np.uint8)
def best(src, t, lines, out, W=1080, H=1440, ch=640, target=0.08):
    im = grab(src,t)
    if 'hoblos' in src: im = cv2.inpaint(im, np.pad(np.ones((66,186),np.uint8)*255,((1,653),(1092,2))), 5, cv2.INPAINT_TELEA)
    M = mask(im)  # mask at source res
    _, rr = track.YN.detect(cv2.resize(im,(640,360))); bx,by,bw,bh = [float(v)*2 for v in rr[0][:4]]
    E = np.zeros((720,1280),np.float32)
    cv2.ellipse(E, (int(bx+bw/2), int(by+bh*0.4)), (int(bw*0.65), int(bh*1.0)), 0, 0, 360, 1, -1)
    M = M*cv2.GaussianBlur(E,(0,0),5)[...,None]   # only the head hides text; text stays in front of the body
    T = text_layer(lines)[240:240+H]  # text alpha in content coords
    ta = T[...,3]
    cw = ch*W/H; y0 = 0
    _, r = track.YN.detect(cv2.resize(im,(640,360))); fy = (r[0][1]+r[0][3]/2)*2; fx = (r[0][0]+r[0][2]/2)*2
    y0 = int(np.clip(fy - ch*0.40, 0, 720-ch))
    bestv=None
    y0 = int(np.clip(fy - ch*0.40, 0, 720-ch))
    for x0 in range(0, int(1280-cw), 6):
        fr = (fx-x0)/cw
        if not (0.13 <= fr <= 0.87): continue
        m = cv2.resize(M[y0:y0+ch, x0:x0+int(cw)], (W,H))
        cov = (ta*m).sum()/ta.sum()
        sc = abs(cov-target)
        if bestv is None or sc<bestv[0]: bestv=(sc,x0,cov,y0)
    _,x0,cov,y0 = bestv
    c = cv2.resize(im[y0:y0+ch, x0:x0+int(cw)], (W,H), interpolation=cv2.INTER_CUBIC)
    m = cv2.resize(M[y0:y0+ch, x0:x0+int(cw)], (W,H))[...,None]
    c = grade(c).astype(np.float32)
    a = T[...,3:4]*(1-m)
    sh = cv2.GaussianBlur(a,(0,0),8)[...,None]*0.45
    c = c*(1-sh)
    o = c*(1-a) + T[...,2::-1]*255*a
    cv2.imwrite(out, o.astype(np.uint8)); print(out, round(cov,2))
best(AY, 300, [('this','HelveticaNeueBoldItalic.otf',60,(25,25,25,255)),('dunya','HelveticaNeueHeavy.otf',205,(25,25,25,255))], '/tmp/b3a.jpg')
best('/mnt/user-data/uploads/motiviman/_work/hoblos_2.mp4', 1000, [('in complete','HelveticaNeueBoldItalic.otf',56,(240,240,240,255)),('control','HelveticaNeueHeavy.otf',185,(255,255,255,255))], '/tmp/b3h.jpg')

import cv2, numpy as np, subprocess
exec(open('behind3.py').read().split("best(AY")[0])
def band(src, t, lines, out, target=0.12, cw=960, ch=720):
    im = grab(src,t)
    if 'hoblos' in src: im = cv2.inpaint(im, np.pad(np.ones((66,186),np.uint8)*255,((1,653),(1092,2))), 5, cv2.INPAINT_TELEA)
    M = mask(im)[...,0]
    _, r = track.YN.detect(cv2.resize(im,(640,360))); fx=(r[0][0]+r[0][2]/2)*2; fy=(r[0][1]+r[0][3]/2)*2
    s = 1080/cw; BH = int(ch*s)
    top = int(960 - (fy - r[0][3]*2*0.15)*s)  # canvas y of band top so the eyes/forehead sit at caption height
    T = text_layer(lines); ta = T[...,3]
    best=None
    for x0 in range(0, 1280-cw+1, 8):
        if not (0.2 <= (fx-x0)/cw <= 0.8): continue
        m = np.zeros((1920,1080),np.float32)
        mm = cv2.resize(M[:, x0:x0+cw], (1080, BH)); y1=max(top,0); m[y1:min(top+BH,1920)] = mm[y1-top:min(BH,1920-top)]
        cov=(ta*m).sum()/ta.sum(); sc=abs(cov-target)
        if best is None or sc<best[0]: best=(sc,x0,cov,m)
    _,x0,cov,m = best
    canvas=np.zeros((1920,1080,3),np.float32)
    c = grade(cv2.resize(im[:, x0:x0+cw], (1080,BH), interpolation=cv2.INTER_CUBIC)).astype(np.float32)
    canvas[top:top+BH]=c
    a = T[...,3:4]*(1-m[...,None])
    o = canvas*(1-a)+T[...,2::-1]*255*a
    cv2.imwrite(out,o.astype(np.uint8)); print(out, round(cov,2), top)
band(AY, 300, [('this','HelveticaNeueBoldItalic.otf',70,(25,25,25,255)),('dunya','HelveticaNeueHeavy.otf',215,(25,25,25,255))], '/tmp/b4a.jpg')
band('/mnt/user-data/uploads/motiviman/_work/hoblos_2.mp4', 1000, [('in complete','HelveticaNeueBoldItalic.otf',64,(240,240,240,255)),('control','HelveticaNeueHeavy.otf',190,(255,255,255,255))], '/tmp/b4h.jpg')

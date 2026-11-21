import cv2, numpy as np, subprocess
AY='/mnt/user-data/uploads/Downloads/vidssave.com Akhi Ayman Powerful Speech _ BG _ Halal Beats, Where you are 720P.mp4'
raw=subprocess.run(['ffmpeg','-v','error','-ss','1640','-i',AY,'-vf','hqdn3d=1.2:1.2:4:4,unsharp=13:13:0.32:13:13:0,eq=gamma=0.92:brightness=-0.03:contrast=1.06:saturation=1.05','-frames:v','1','-f','rawvideo','-pix_fmt','bgr24','-'],capture_output=True).stdout
im=np.frombuffer(raw,np.uint8).reshape(720,1280,3)
c=cv2.resize(im[:, 438:843],(1080,1920),interpolation=cv2.INTER_CUBIC)
c=cv2.filter2D(c,-1,np.array([[0,-0.35,0],[-0.35,2.4,-0.35],[0,-0.35,0]]))
def star_sprite(r, rays=4):
    s=int(r*8)|1; img=np.zeros((s,s),np.float32); cx=s//2
    yy,xx=np.mgrid[0:s,0:s]-cx
    d=np.sqrt(xx**2+yy**2)+1e-3
    core=np.exp(-(d/(r*0.55))**2)
    ang=np.arctan2(yy,xx)
    spikes=np.zeros_like(img)
    for k in range(rays):
        a=k*np.pi/rays*2/2*2/ (2 if rays==4 else 1)
    # 4 rays: horizontal + vertical thin streaks
    spikes=np.exp(-(np.abs(yy)/(r*0.12))**2)*np.exp(-(np.abs(xx)/(r*3.2)))+np.exp(-(np.abs(xx)/(r*0.12))**2)*np.exp(-(np.abs(yy)/(r*3.2)))
    glow=np.exp(-(d/(r*1.8))**2)*0.35
    return np.clip(core+spikes*0.9+glow,0,1)
rng=np.random.default_rng(7)
def overlay(base, n_stars=22, n_dust=90, warm=(200,230,255)):
    H,W=base.shape[:2]; L=np.zeros((H,W),np.float32)
    for _ in range(n_stars):
        r=rng.uniform(3,7); sp=star_sprite(r)*rng.uniform(0.5,0.7)
        s=sp.shape[0]; x=int(rng.uniform(40,W-40)); y=int(rng.uniform(60,H-60))
        x0,y0=x-s//2,y-s//2
        xs,ys=max(0,x0),max(0,y0); xe,ye=min(W,x0+s),min(H,y0+s)
        L[ys:ye,xs:xe]=np.maximum(L[ys:ye,xs:xe], sp[ys-y0:ye-y0, xs-x0:xe-x0])
    D=np.zeros((H,W),np.float32)
    for _ in range(n_dust):
        cv2.circle(D,(int(rng.uniform(0,W)),int(rng.uniform(0,H))),int(rng.uniform(1,2)),float(rng.uniform(0.3,0.55)),-1,cv2.LINE_AA)
    D=cv2.GaussianBlur(D,(0,0),1.2)
    B=np.zeros((H,W),np.float32)  # soft bokeh orbs
    for _ in range(10):
        cv2.circle(B,(int(rng.uniform(0,W)),int(rng.uniform(0,H))),int(rng.uniform(14,34)),float(rng.uniform(0.04,0.09)),-1,cv2.LINE_AA)
    B=cv2.GaussianBlur(B,(0,0),6)
    A=np.clip(L+D+B,0,1)[...,None]
    col=np.array(warm,np.float32)[None,None,:]
    out=255-(255-base.astype(np.float32))*(1-A*col/255)   # screen blend
    return np.clip(out,0,255).astype(np.uint8)
a=overlay(c, 55, 200, warm=(185,228,255))
cv2.imwrite('/tmp/st_a.png',a)

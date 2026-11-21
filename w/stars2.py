import cv2, numpy as np, subprocess
exec(open('stars.py').read().split("def star_sprite")[0])
rng=np.random.default_rng(21)
def sprite(kind, r):
    s=int(r*9)|1; c=s//2; yy,xx=(np.mgrid[0:s,0:s]-c).astype(np.float32); d=np.sqrt(xx**2+yy**2)+1e-3
    core=np.exp(-(d/(r*0.5))**2); glow=np.exp(-(d/(r*1.8))**2)*0.3
    def ray(ax, ay, w=0.11, L=3.2):  # streak along direction (ax,ay)
        along=xx*ax+yy*ay; perp=-xx*ay+yy*ax
        return np.exp(-(perp/(r*w))**2)*np.exp(-np.abs(along)/(r*L))
    if kind=='star4': img=core+0.9*(ray(1,0)+ray(0,1))+glow
    elif kind=='star8': k=0.7071; img=core+0.9*(ray(1,0)+ray(0,1))+0.45*(ray(k,k,0.08,1.8)+ray(k,-k,0.08,1.8))+glow
    elif kind=='star6': img=core+glow+0.8*sum(ray(np.cos(a),np.sin(a),0.1,2.4) for a in [0,np.pi/3,2*np.pi/3])
    elif kind=='flare': img=core*1.0+np.exp(-(d/(r*3))**2)*0.25+0.7*ray(1,0,0.07,6)   # horizontal lens glint
    elif kind=='orb': img=np.exp(-(d/(r*1.1))**2)*0.9
    elif kind=='ring':  # hollow bokeh circle
        img=np.exp(-((d-r*2.2)/(r*0.35))**2)*0.5+np.exp(-(d/(r*2.2))**2)*0.12
    elif kind=='glitter': img=np.exp(-(d/(r*0.35))**2)
    return np.clip(img,0,1)
def place(L, sp):
    H,W=L.shape; s=sp.shape[0]; x=int(rng.uniform(20,W-20)); y=int(rng.uniform(30,H-30)); x0,y0=x-s//2,y-s//2
    xs,ys=max(0,x0),max(0,y0); xe,ye=min(W,x0+s),min(H,y0+s)
    L[ys:ye,xs:xe]=np.maximum(L[ys:ye,xs:xe], sp[ys-y0:ye-y0, xs-x0:xe-x0])
H,W=c.shape[:2]; L=np.zeros((H,W),np.float32)
mix=[('star4',26,(3,6.5),(0.5,0.7)),('star8',14,(3.5,6.5),(0.45,0.65)),('star6',12,(3,5.5),(0.45,0.6)),('flare',5,(3,5),(0.4,0.55)),
     ('orb',40,(1.5,3.5),(0.35,0.6)),('glitter',180,(1.2,2.2),(0.4,0.8)),('ring',12,(7,14),(0.25,0.4))]
for kind,n,(r0,r1),(a0,a1) in mix:
    for _ in range(n): place(L, sprite(kind, rng.uniform(r0,r1))*rng.uniform(a0,a1))
A=np.clip(L*1.3,0,1)[...,None]
col=np.array((185,228,255),np.float32)[None,None,:]
out=255-(255-c.astype(np.float32))*(1-A*col/255)
cv2.imwrite('/tmp/st_c.png',np.clip(out,0,255).astype(np.uint8))

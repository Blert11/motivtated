import cv2, numpy as np, subprocess
from PIL import Image
def grab(src,t,cx):
    raw=subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',src,'-vf','hqdn3d=1.2:1.2:4:4,unsharp=13:13:0.32:13:13:0','-frames:v','1','-f','rawvideo','-pix_fmt','bgr24','-'],capture_output=True).stdout
    im=np.frombuffer(raw,np.uint8).reshape(720,1280,3); x0=int(np.clip(cx-202,0,1280-405))
    return cv2.resize(im[:,x0:x0+405],(1080,1920),interpolation=cv2.INTER_CUBIC).astype(np.float32)/255
def logo(path,h):
    im=Image.open(path).convert('RGBA'); w=int(im.width*h/im.height); im=im.resize((w,h),Image.LANCZOS)
    a=np.array(im).astype(np.float32)/255; return a[...,[2,1,0]], a[...,3:4]
def put(base, path, mode, op, h=78, y=1770):
    rgb,a=logo(path,h); H,W=rgb.shape[:2]; x=(1080-W)//2; y0=y-H//2
    B=base[y0:y0+H,x:x+W]
    if mode=='overlay': top=np.where(B<0.5, 2*B*rgb, 1-2*(1-B)*(1-rgb))
    else: top=rgb
    base[y0:y0+H,x:x+W]=B*(1-a*op)+top*a*op
    return base
AY='/mnt/user-data/uploads/Downloads/vidssave.com Akhi Ayman Powerful Speech _ BG _ Halal Beats, Where you are 720P.mp4'
HO='/mnt/user-data/uploads/motiviman/_work/hoblos_2.mp4'
L1='/mnt/user-data/uploads/53c41074-image.png'; L2='/mnt/user-data/uploads/aa00cc5a-image.png'
fa=grab(AY,1640,640); fh=grab(HO,1000,760)
outs=[]
for name,f in [('ay',fa),('ho',fh)]:
    for k,(L,mode,op) in enumerate([(L1,'overlay',0.85),(L2,'normal',0.6)]):
        o=put(f.copy(),L,mode,op); p=f'/tmp/wm_{name}_{k}.png'; cv2.imwrite(p,(np.clip(o,0,1)*255).astype(np.uint8)); outs.append(p)
print(outs)

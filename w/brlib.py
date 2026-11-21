import subprocess, numpy as np, json, cv2
V={'adhan':'/mnt/user-data/uploads/imanivated/B-Roll videos/2-hours-adhan-ezan-beautiful-muslim-call-to-prayer-with-mosques-around-the-world-ytmp4.savetube.vip.mp4',
   'mosq':'/mnt/user-data/uploads/imanivated/B-Roll videos/10-most-beautiful-mosques-in-the-world-ytmp4.savetube.vip.mp4'}
D={'adhan':7567,'mosq':1141}
out=[]
for k,step in [('adhan',75),('mosq',38)]:
    for t in np.arange(20, D[k]-30, step):
        raw=subprocess.run(['ffmpeg','-v','error','-ss',f'{t:.1f}','-t','4.2','-i',V[k],'-vf','fps=5,scale=96:54,format=gray','-f','rawvideo','-'],capture_output=True).stdout
        fr=np.frombuffer(raw,np.uint8).reshape(-1,54,96).astype(np.float32)
        if len(fr)<18: continue
        dif=np.abs(np.diff(fr,axis=0)).mean((1,2))
        if dif.max()>18: continue   # contains a cut
        m=fr.mean()
        if m<25: continue
        out.append(dict(src=k,t=round(float(t),1),bright=round(float(m),1),motion=round(float(dif.mean()),2)))
json.dump(out,open('broll_cands.json','w')); print(len(out))

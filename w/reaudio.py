import subprocess, os, re, sys
src = open('final.py').read()
ORDER = eval(src[src.index('ORDER = ')+8:src.index(']\nos.makedirs')+1])
for i,(cid,name) in enumerate(ORDER,1):
    if sys.argv[1:] and cid not in sys.argv[1:]: continue
    f=f'deliver/{i}. {name}.mp4'; tmp=f'deliver/_tmp.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-i',f,'-i',f'out/{cid}/final.wav','-map','0:v','-map','1:a','-c:v','copy',
        '-af','alimiter=limit=0.72:attack=1:release=50:level=disabled,volume=1.0','-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart','-shortest',tmp],check=True)
    r=subprocess.run(['ffmpeg','-nostats','-hide_banner','-i',tmp,'-af','ebur128=peak=true:framelog=quiet','-f','null','-'],capture_output=True,text=True).stderr
    I=re.findall(r'I:\s+(-?[\d.]+) LUFS',r)[-1]; P=re.findall(r'Peak:\s+(-?[\d.]+) dBFS',r)[-1]
    os.replace(tmp,f); print(cid,I,P,flush=True)

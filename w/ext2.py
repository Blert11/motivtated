import json, subprocess, os, sys
import render2
P=json.load(open('pieces2.json'))
NOSEP={'tr','rd0','rd1','rd2','rd3','yt0','yt1','yt2','yt3','yt4','yt5'}
for c,v in P.items():
    if len(sys.argv)>1 and c not in sys.argv[1:]: continue
    for i,(s,a,b) in enumerate(v):
        o=f'aud/{c}_{i}'
        if os.path.exists(o+'_voc.wav'): continue
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(a),'-t',str(b-a),'-i',render2.SRC[s],'-ac','2','-ar','44100',o+'_mix.wav'],check=True)
        if s in NOSEP:
            # clean masjid recording, no music bed: no separation needed (light hum/noise cleanup only)
            subprocess.run(['ffmpeg','-v','error','-y','-i',o+'_mix.wav','-af','highpass=f=70,afftdn=nf=-30',o+'_voc.wav'],check=True)
        else:
            subprocess.run(['python3','sep.py',o+'_mix.wav',o+'_voc.wav'],check=True)
        print(c,i,flush=True)

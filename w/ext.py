import json, subprocess, os
SRC={'ay':'/mnt/user-data/uploads/Downloads/vidssave.com Akhi Ayman Powerful Speech _ BG _ Halal Beats, Where you are 720P.mp4','h0':'/mnt/user-data/uploads/motiviman/_work/hoblos_0.mp4','h1':'/mnt/user-data/uploads/motiviman/_work/hoblos_1.mp4','h2':'/mnt/user-data/uploads/motiviman/_work/hoblos_2.mp4'}
P=json.load(open('pieces.json'))
for c,v in P.items():
    for i,(s,a,b) in enumerate(v):
        o=f'aud/{c}_{i}'
        if os.path.exists(o+'_voc.wav'): continue
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(a),'-t',str(b-a),'-i',SRC[s],'-ac','2','-ar','44100',o+'_mix.wav'],check=True)
        subprocess.run(['python3','sep.py',o+'_mix.wav',o+'_voc.wav'],check=True)
        print(c,i,flush=True)

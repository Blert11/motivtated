import sys, json, os, render
P = json.load(open('pieces2.json')); CFG = json.load(open('cfg2.json'))
for cid in sys.argv[1:]:
    c = CFG[cid]
    if not all(os.path.exists(f'aud/{cid}_{i}_voc.wav') for i in range(len(P[cid]))): print('== skip', cid); continue
    if not os.path.exists(f'out/{cid}/final.wav'):
        render.make_audio(cid, P[cid], c['music'], entry=c.get('entry'))
    w = render.asr_words(f'out/{cid}/voice16.wav')
    print(f'== {cid}:', ' '.join(x[2] for x in w), flush=True)

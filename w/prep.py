import sys, json, os, render
P = json.load(open('pieces.json')); CFG = json.load(open('cfg.json'))
for cid in sys.argv[1:]:
    if not os.path.exists(f'out/{cid}/final.wav'):
        render.make_audio(cid, P[cid], CFG[cid]['music'])
    w = render.asr_words(f'out/{cid}/voice16.wav')
    print(f'== {cid}:', ' '.join(x[2] for x in w), flush=True)

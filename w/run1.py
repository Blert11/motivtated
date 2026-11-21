import sys, json, render, caps, time
P = json.load(open('pieces.json'))
CFG = json.load(open('cfg.json'))
cid = sys.argv[1]; prev = len(sys.argv) > 2
c = CFG[cid]; c['pieces'] = P[cid]
import os
if not os.path.exists(f'out/{cid}/final.wav'):
    render.make_audio(cid, c['pieces'], c['music'])
w = render.asr_words(f'out/{cid}/voice16.wav')
fx = f'fix/{cid}.txt'
c['words'] = caps.align(w, open(fx).read()) if os.path.exists(fx) else w
t = time.time()
print(render.render(cid, c, preview=prev), round(time.time() - t))

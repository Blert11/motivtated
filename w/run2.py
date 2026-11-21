import sys, json, os, time, re, numpy as np
import render2, render, caps
P = json.load(open('pieces2.json')) if os.path.exists('pieces2.json') else {}
P.update({k: v for k, v in json.load(open('pieces.json')).items() if k not in P})
CFG = json.load(open('cfg2.json'))
LIB = json.load(open('broll_lib.json'))
cid = sys.argv[1]
c = CFG[cid]; c['pieces'] = P[cid]
if not os.path.exists(f'out/{cid}/final.wav') or c.get('remix'):
    render.make_audio(cid, c['pieces'], c['music'], entry=c.get('entry'))
w = render.asr_words(f'out/{cid}/voice16.wav')
fx = f'fix/{cid}.txt'
c['words'] = caps.align(w, open(fx).read()) if os.path.exists(fx) else w
dur = sum(b - a for _, a, b in c['pieces'])
rng = np.random.default_rng(abs(hash(cid)) % 2**32)
if 'broll' not in c and c['frame'] != 'comp':
    c['broll'] = render2.plan_broll(c['words'], dur, LIB, rng)
if c.get('autolock') and 'locks' not in c:
    # head lock on 1-2 strong moments: starts of sentences, away from b-roll and the opening
    starts = [words[i][0] for i in range(1, len(words)) if re.search(r'[.!?]$', words[i - 1][2])] if (words := c['words']) else []
    busy = [(t - 0.5, t + d + 0.5) for t, d, *_ in c.get('broll', [])]
    locks = []
    for t in starts:
        if t < 4 or t > dur - 5 or any(a < t + 3.4 and t < b for a, b in busy): continue
        if locks and t - locks[-1][0] < 12: continue
        locks.append([round(t, 2), 3.2])
    c['locks'] = locks[:1 if dur < 40 else 2]
if 'stars' not in c:
    n = 2 if dur < 45 else 3
    c['stars'] = [[round(float(dur * (i + 0.5) / n - 2), 2), 4.0] for i in range(n)]
t = time.time()
print(cid, render2.render(cid, c), round(time.time() - t), c.get('broll'), flush=True)

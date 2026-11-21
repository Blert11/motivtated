import json, numpy as np, track
P=json.load(open('pieces.json'))
for c,v in P.items():
    m=0
    for s,a,b in v:
        new=track.track(s,a,b)
        o=json.load(open(f'track/{s}_{a:.2f}_{b:.2f}.json'))
        k=min(len(o['x']),len(new['x']))
        m=max(m, float(np.max(np.abs(np.array(o['x'][:k])-np.array(new['x'][:k])))))
    print(c, round(m), flush=True)

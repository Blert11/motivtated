import json, render, caps, re, sys
P=json.load(open('pieces2.json'))
def words_abs(cid):
    w=render.asr_words(f'out/{cid}/voice16.wav')
    fx=f'fix/{cid}.txt'
    ww=caps.align(w,open(fx).read())
    # map clip time -> (src, abs)
    out=[]; off=0
    segs=[]
    for s,a,b in P[cid]: segs.append((off,off+b-a,s,a)); off+=b-a
    for t0,t1,txt in ww:
        for o0,o1,s,a in segs:
            if o0<=t0<o1: out.append((s,a+t0-o0,a+t1-o0,txt)); break
    return out
def find(cid, start, end):
    W=words_abs(cid); n=lambda x: re.sub(r"[^\w']","",x.lower())
    st=[n(x) for x in start.split()]; en=[n(x) for x in end.split()]
    for i in range(len(W)):
        if [n(w[3]) for w in W[i:i+len(st)]]==st:
            for j in range(i,len(W)):
                if [n(w[3]) for w in W[j:j+len(en)]]==en:
                    k=j+len(en)-1
                    return (W[i][0], round(W[i][1]-0.1,2), round(W[k][2]+0.3,2), ' '.join(w[3] for w in W[i:k+1]))
    return None
if __name__=='__main__':
    for q in [('U1','Death doesn\'t','you\'re poor.'),('U7','And I look','covered up.'),('U12','What are they','the heavens?'),('U14','Do it now.','asking for forgiveness.'),
              ('U8','You know, once','mum again.'),('R13','My mother came','about me already?')]:
        print(q[0], find(*q))

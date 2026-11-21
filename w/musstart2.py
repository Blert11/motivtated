import librosa, numpy as np, json
out={}
for i in range(1,6):
    y,sr=librosa.load(f'mus/m{i}.wav',sr=22050,mono=True); dur=len(y)/sr; hop=512
    rms=librosa.feature.rms(y=y,hop_length=hop)[0]; fps=sr/hop
    S=np.abs(librosa.stft(y,hop_length=hop)); f=librosa.fft_frequencies(sr=sr); low=S[f<150].sum(0)
    _,beats=librosa.beat.beat_track(y=y,sr=sr,hop_length=hop); bt=librosa.frames_to_time(beats,sr=sr,hop_length=hop)
    ref=np.percentile(rms[:int((dur-3)*fps)],75); lref=np.percentile(low,75)
    w=int(4*fps); c=[]
    for b in bt:
        k=int(b*fps)
        if k<w or b>dur-12: continue
        pre=rms[k-w:k].mean(); post=rms[k:k+w].mean(); lp=low[k-w:k].mean(); la=low[k:k+w].mean()
        jump=(post/(pre+1e-6))*0.5+(la/(lp+1e-6))*0.5
        if post>0.9*ref and jump>1.2: c.append((round(float(jump),2),round(float(b),2)))
    c.sort(reverse=True); picks=[]
    for j,b in c:
        if all(abs(b-p)>8 for p in picks): picks.append(b)
    out[f'm{i}']=sorted(picks[:3])
    print(i, round(dur,1), out[f'm{i}'], c[:5])
json.dump(out,open('mus_entries.json','w'))

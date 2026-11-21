import librosa, numpy as np, json
res={}
for i in range(1,6):
    y,sr=librosa.load(f'mus/m{i}.wav',sr=22050,mono=True)
    dur=len(y)/sr
    hop=512
    rms=librosa.feature.rms(y=y,hop_length=hop)[0]; t=librosa.times_like(rms,sr=sr,hop_length=hop)
    tempo,beats=librosa.beat.beat_track(y=y,sr=sr,hop_length=hop); bt=librosa.frames_to_time(beats,sr=sr,hop_length=hop)
    onset=librosa.onset.onset_strength(y=y,sr=sr,hop_length=hop)
    # low-end (kick) energy
    S=np.abs(librosa.stft(y,hop_length=hop)); f=librosa.fft_frequencies(sr=sr); low=S[f<150].sum(0)
    ref=np.percentile(rms[t<dur-3],75); lref=np.percentile(low,75)
    win=int(3/(hop/sr))
    cand=None
    for b in bt:
        k=int(b*sr/hop)
        if b>dur-20: break
        seg=rms[k:k+win]; lseg=low[k:k+win]
        if seg.mean()>=0.85*ref and lseg.mean()>=0.7*lref and onset[k:k+6].max()>np.percentile(onset,70):
            cand=b; break
    if cand is None: cand=0.0
    # snap a little before the beat so the hit lands cleanly
    res[f'm{i}']=dict(dur=round(dur,1),tempo=float(np.atleast_1d(tempo)[0]),start=round(max(0,cand-0.05),2),
                    rms_profile=[round(float(rms[(t>=s)&(t<s+5)].mean()/ref),2) for s in range(0,int(dur)-1,5)])
    print(i,res[f'm{i}'])
json.dump(res,open('mus_starts.json','w'))

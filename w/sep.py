import sys, numpy as np, onnxruntime as ort, soundfile as sf
N=6144; H=1024; T=256; F=3072
sess=ort.InferenceSession('/home/claude/models/UVR-MDX-NET-Voc_FT.onnx', providers=['CPUExecutionProvider'])
win=np.hanning(N+1)[:-1].astype(np.float32)
def stft(x):  # x: [L] -> [N//2+1, frames]
    xp=np.pad(x,(N//2,N//2),mode='reflect'); n=1+(len(xp)-N)//H
    idx=np.arange(N)[None,:]+H*np.arange(n)[:,None]
    return np.fft.rfft(xp[idx]*win,axis=1).T
def istft(S,L):
    fr=np.fft.irfft(S.T,n=N,axis=1)*win; n=fr.shape[0]; out=np.zeros(N+H*(n-1)); ws=np.zeros_like(out)
    for i in range(n): out[i*H:i*H+N]+=fr[i]; ws[i*H:i*H+N]+=win**2
    out/=np.maximum(ws,1e-8); return out[N//2:N//2+L]
a,sr=sf.read(sys.argv[1],dtype='float32',always_2d=True); a=a.T  # [2,L]
if a.shape[0]==1: a=np.repeat(a,2,0)
L=a.shape[1]; chunk=H*(T-1); trim=N//2; gen=chunk-2*trim
pad=gen-L%gen
mix=np.concatenate([np.zeros((2,trim)),a,np.zeros((2,pad)),np.zeros((2,trim))],1)
res=[]
for i in range(0, mix.shape[1]-2*trim-1, gen):
    w=mix[:,i:i+chunk]
    if w.shape[1]<chunk: w=np.pad(w,((0,0),(0,chunk-w.shape[1])))
    X=[stft(w[c])[:F] for c in range(2)]
    inp=np.stack([X[0].real,X[0].imag,X[1].real,X[1].imag])[None].astype(np.float32)
    o=sess.run(None,{'input':inp})[0][0]
    Y=[np.concatenate([o[0]+1j*o[1],np.zeros((1,T))],0), np.concatenate([o[2]+1j*o[3],np.zeros((1,T))],0)]
    y=np.stack([istft(Y[c],chunk) for c in range(2)])
    res.append(y[:,trim:-trim])
v=np.concatenate(res,1)[:,:L]*1.021
sf.write(sys.argv[2],v.T,sr)

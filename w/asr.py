import sys, json, time, wave, numpy as np, sherpa_onnx
M="/home/claude/models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/"
rec = sherpa_onnx.OfflineRecognizer.from_transducer(encoder=M+"encoder.int8.onnx",decoder=M+"decoder.int8.onnx",joiner=M+"joiner.int8.onnx",tokens=M+"tokens.txt",num_threads=int(sys.argv[3]) if len(sys.argv)>3 else 2,model_type="nemo_transducer")
cfg = sherpa_onnx.VadModelConfig(); cfg.silero_vad.model="/home/claude/models/silero_vad.onnx"; cfg.silero_vad.min_silence_duration=0.35; cfg.silero_vad.max_speech_duration=20; cfg.sample_rate=16000
vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)
w=wave.open(sys.argv[1]); a=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16).astype(np.float32)/32768
out=[]; t0=time.time()
def flush():
  while not vad.empty():
    seg=vad.front; st=seg.start/16000; s=rec.create_stream(); s.accept_waveform(16000, np.array(seg.samples)); rec.decode_stream(s); r=s.result
    toks=r.tokens; ts=r.timestamps
    words=[]
    for tk,tt in zip(toks,ts):
      if tk.startswith(" ") or not words: words.append([st+tt, st+tt, tk.strip()])
      else: words[-1][2]+=tk
      words[-1][1]=st+tt
    # set ends to next start
    for i in range(len(words)):
      words[i][1]= min(words[i+1][0], words[i][0]+0.8) if i+1<len(words) else words[i][0]+0.4
    out.append({"s":st,"e":st+len(seg.samples)/16000,"t":r.text,"w":words}); vad.pop()
for i in range(0,len(a),512):
  vad.accept_waveform(a[i:i+512])
  if i % (16000*60) < 512: print(i/16000, time.time()-t0, flush=True)
  flush()
vad.flush(); flush()
json.dump(out,open(sys.argv[2],"w")); print("done",time.time()-t0)

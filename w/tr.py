import sys, json, time
from faster_whisper import WhisperModel
m = WhisperModel(sys.argv[3] if len(sys.argv)>3 else "small.en", device="cpu", compute_type="int8", cpu_threads=2)
t=time.time()
segs, info = m.transcribe(sys.argv[1], language="en", word_timestamps=True, vad_filter=True, beam_size=1)
out=[]
with open(sys.argv[2]+".log","w") as lg:
  for s in segs:
    out.append({"s":s.start,"e":s.end,"t":s.text,"w":[[w.start,w.end,w.word] for w in s.words]})
    lg.write(f"{s.end:.0f} {time.time()-t:.0f}\n"); lg.flush()
json.dump(out, open(sys.argv[2],"w"))
print("done", time.time()-t)

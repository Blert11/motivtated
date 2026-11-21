import json, render, caps, render2, numpy as np
c=json.load(open('cfg2.json'))['W7'].copy()
c.update(style='halal', grade='halal', frame='rwin', locks=[[3.0,3.0]], broll=[], stars=[[6,3]])
c['pieces']=[['hr',1451.84,1461.84]]
w=render.asr_words('out/W7/voice16.wav'); w=caps.align(w, open('fix/W7.txt').read())
c['words']=[x for x in w if x[1]<10]
import shutil, os; os.makedirs('out/T3',exist_ok=True); shutil.copy('out/W7/final.wav','out/T3/final.wav')
print(render2.render('T3', c))

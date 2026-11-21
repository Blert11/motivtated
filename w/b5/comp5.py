"""Render one batch-5 YouTube compilation: python3 comp5.py yt1"""
import json, os, sys
sys.path.insert(0, '/home/claude/w'); sys.path.insert(0, '/home/claude/w/long1')
import longvid as L
S = json.load(open('/home/claude/w/b5/sources.json'))
for k, v in S.items():
    L.SRC[k] = os.environ.get('B5_SRC_DIR', '/mnt/user-data/uploads/Downloads') + '/' + v['file']
    L.ASR[k] = f'b5/asr/{k}.json'; L.NOSEP.add(k)
    if v.get('crop'): L.CROP[k] = tuple(v['crop'])
os.chdir('/home/claude/w')
L.main(f'/home/claude/w/b5/{sys.argv[1]}')

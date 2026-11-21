import json, os, subprocess, sys, shutil
import render
P = json.load(open('pieces.json')); CFG = json.load(open('cfg.json'))
ORDER = [
 ('A2', 'clip akhi ayman - start with your own household'),
 ('H1', 'clip mohamed hoblos - allah is in complete control'),
 ('A1', "clip akhi ayman - jannah only through allah's mercy"),
 ('H2', 'clip mohamed hoblos - islam means full submission'),
 ('A9', 'clip akhi ayman - everything the quran touches'),
 ('H13', 'clip mohamed hoblos - who are we to question allah'),
 ('C1', 'compilation - because allah said so'),
 ('A4', 'clip akhi ayman - this dunya will break your heart'),
 ('H3', "clip mohamed hoblos - it's haram because allah said so"),
 ('A6', 'clip akhi ayman - my dna is the quran and sunnah'),
 ('H5', 'clip mohamed hoblos - the red light at 3am'),
 ('A7', 'clip akhi ayman - be content, jannah awaits'),
 ('H11', "clip mohamed hoblos - he knows what we don't know"),
 ('C2', 'compilation - the first ones into jannah'),
 ('A3', 'clip akhi ayman - only complain to allah'),
 ('H7', "clip mohamed hoblos - the deen is perfect, i'm weak"),
 ('A8', 'clip akhi ayman - alhamdulillah i am a muslim'),
 ('H14', 'clip mohamed hoblos - put your logic aside'),
 ('H9', "clip mohamed hoblos - ibrahim's question"),
]
os.makedirs('deliver', exist_ok=True)
only = sys.argv[1:]
for i, (cid, name) in enumerate(ORDER, 1):
    if only and cid not in only: continue
    src = f'out/{cid}/{cid}.mp4'
    out = f'deliver/{i}. {name}.mp4'
    if not os.path.exists(src):
        print('MISSING', cid); continue
    if os.path.exists(out) and os.path.getmtime(out) > os.path.getmtime(src):
        continue
    render.make_audio(cid, P[cid], CFG[cid]['music'])
    dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', src], capture_output=True, text=True).stdout)
    vbr = min(9.0, 0.92 * 29 * 8 / dur - 0.2)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-i', f'out/{cid}/final.wav', '-map', '0:v', '-map', '1:a',
                    '-c:v', 'libx264', '-profile:v', 'high', '-preset', 'faster', '-crf', '18', '-maxrate', f'{vbr:.2f}M', '-bufsize', f'{vbr*2:.2f}M',
                    '-pix_fmt', 'yuv420p', '-r', '30', '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-movflags', '+faststart', '-shortest', out], check=True)
    print(cid, round(os.path.getsize(out) / 1e6, 1), 'MB', flush=True)

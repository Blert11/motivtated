import json, sys, render
C = json.load(open('cfg2.json'))
cids = sys.argv[1:]
STY = ['halal','kinetic','halal','overlayword','halal','helvmed','kinetic','halal','bebas','halal','coolv','kinetic','halal','montlight',
       'halal','accent','kinetic','halal','overlayword','typewriter','halal','boldital','kinetic','halal','podcast','halal','overlayword','kinetic']
FR = ['full','rwin','sq','fish','rect34','full','rsq','rwin','band169','full','sq','rect34','rwin','full','rsq','band169','sq','full','fish','rect34','rwin','full','sq','rsq','band169','full','fish','rwin']
OTHER_GR = ['orig','warm','moody','cool','orig','warm']
MUS = ['m1','m2','m3','m4','m5']
base = int(open('b3/cfg_counter').read()) if __import__('os').path.exists('b3/cfg_counter') else 0
for j, cid in enumerate(cids):
    i = base + j
    st = STY[i % len(STY)]; fr = FR[i % len(FR)]
    if st == 'overlayword': fr = 'fish' if i % 2 else 'full'
    gr = 'halal' if (st in ('halal',) or i % 3 == 0) and st != 'overlayword' else OTHER_GR[i % len(OTHER_GR)]
    m = MUS[i % 5]; ent = render.MUS_ENTRY[m][i % len(render.MUS_ENTRY[m])]
    C[cid] = {'style': st, 'grade': gr, 'frame': fr, 'music': m, 'entry': ent, 'autolock': gr == 'halal'}
    print(cid, C[cid])
open('b3/cfg_counter', 'w').write(str(base + len(cids)))
json.dump(C, open('cfg2.json', 'w'), indent=1)

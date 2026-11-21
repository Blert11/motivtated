import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quran3
i, s, e = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
j = json.load(open(f'job{i}.json'))
j['part'] = [int(s), int(s) + (e - s)] if e - s != 30 else [int(s), int(s) + 30]
quran3.render(j)

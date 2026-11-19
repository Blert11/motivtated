"""Read-only Buffer diagnostics: list Post fields, then show status/error of the post IDs in INPUT_DUE_AT (comma list)."""
import json, os
from .buffer import Buffer
from .common import env
b = Buffer(token=os.environ.get('BUFFER_API_KEY_2') or env('BUFFER_API_KEY'))
t = b.query('{ __type(name: "Post") { fields { name type { name kind ofType { name } } } } }')['__type']['fields']
names = [f['name'] for f in t]; print('Post fields:', names)
for t2 in ('PostError', 'Error', 'PostErrorDetails'):
    try:
        r = b.query('{ __type(name: "%s") { fields { name } } }' % t2)['__type']
        if r: print(t2, [f['name'] for f in r['fields']])
    except Exception as e: pass
want = [n for n in ('id', 'status', 'dueAt', 'sentAt', 'error', 'errorMessage', 'externalLink') if n in names]
for pid in [x.strip() for x in os.environ.get('INPUT_IDS', '').split(',') if x.strip()]:
    for sel in ('error { message supportUrl rawError }', 'error { message }', ''):
        fs = ' '.join(n for n in want if n != 'error') + (' ' + sel if sel and 'error' in names else '')
        try:
            print(pid, json.dumps(b.query('query($i: PostInput!) { post(input: $i) { %s } }' % fs, {'i': {'id': pid}})))
            break
        except Exception as e:
            print(pid, 'try failed:', str(e)[:200])

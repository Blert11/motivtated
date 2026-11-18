"""Print Buffer GraphQL mutation names and the fields of their input types (read-only)."""
import json
from .buffer import Buffer
from .common import env
q = '{ __schema { mutationType { fields { name args { name type { name kind ofType { name kind } } } } } } }'
b = Buffer(token=env('BUFFER_API_KEY'))
fields = b.query(q)['__schema']['mutationType']['fields']
for f in fields:
    print(f['name'], [(a['name'], a['type'].get('name') or a['type']['ofType']['name']) for a in f['args']])
for t in ('DeletePostInput',):
    try:
        r = b.query('{ __type(name: "%s") { inputFields { name type { name kind ofType { name } } } } }' % t)
        print(t, json.dumps(r))
    except Exception as e:
        print(t, 'n/a', e)

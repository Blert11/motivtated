"""Make queue room for an owner-requested clip: delete the named still-scheduled Buffer posts (latest ones) and drop
their ledger records, so the lanes simply schedule those clips again later when there is room."""
import json, os, re
from datetime import timedelta
from .buffer import Buffer
from .common import Stop, env, now, require
from .github import GitHub, GitHubLedger
from .scheduler import parse_time


class Lane2Ledger(GitHubLedger):
    PATH = 'lane2-state.json'


def main():
    keys = [k.strip() for k in env('INPUT_KEYS').split(',') if k.strip()]
    require(keys and len(keys) <= 12, 'Give 1-12 record keys.')
    gh = GitHub(env('GITHUB_REPOSITORY'), env('GITHUB_TOKEN'))
    groups = {'main': [k for k in keys if not k.startswith(('motivtated:', 'imanivated:'))],
              'lane2': [k for k in keys if k.startswith(('motivtated:', 'imanivated:'))]}
    out = {}
    for name, ks in groups.items():
        if not ks: continue
        L = GitHubLedger(gh) if name == 'main' else Lane2Ledger(gh); L.load()
        buf = Buffer() if name == 'main' else Buffer(token=env('BUFFER_API_KEY_2'))
        for k in ks:
            r = L.data['records'].get(k)
            if not r or r.get('state') != 'submitted' or not r.get('buffer_post_id'):
                out[k] = 'not a queued post'; continue
            due = parse_time(r.get('scheduled_at') or r.get('due_at'))
            if due < now_dt() + timedelta(hours=3):
                out[k] = 'too close to its time, kept'; continue
            res = buf.query('mutation($input: DeletePostInput!) { deletePost(input: $input) { __typename '
                            '... on MutationError { message } } }', {'input': {'id': r['buffer_post_id']}})['deletePost']
            if 'Error' in str(res.get('__typename')):
                out[k] = 'delete rejected: ' + str(res.get('message'))[:200]; continue
            L.data['records'].pop(k)
            L.data.setdefault('events', []).append({'action': 'owner_freed_slot', 'at': now(), 'record': k})
            out[k] = 'deleted from Buffer; will be scheduled again later'
        L.save()
    print(json.dumps(out, indent=1))


def now_dt():
    return parse_time(now())


if __name__ == '__main__':
    main()

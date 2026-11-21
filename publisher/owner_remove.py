"""Owner stop (2026-11-21): delete the named still-scheduled Buffer posts and record them as skipped
(skip_reason owner_removed), so no lane ever schedules them again. Used for the stopped Motivtated TikTok queue and
for clips the owner no longer wants posted."""
import json
from datetime import timedelta
from .buffer import Buffer
from .common import env, now
from .github import GitHub, GitHubLedger
from .scheduler import parse_time


class Lane2Ledger(GitHubLedger):
    PATH = 'lane2-state.json'


class Lane3Ledger(GitHubLedger):
    PATH = 'lane3-state.json'


def lane_of(key):
    parts = key.split(':')
    if len(parts) == 2:
        return 'main'
    return {'youtube': 'lane2', 'twitter': 'lane2', 'pinterest': 'lane3'}.get(parts[-1])


LEDGERS = {'main': (GitHubLedger, 'BUFFER_API_KEY'), 'lane2': (Lane2Ledger, 'BUFFER_API_KEY_2'),
           'lane3': (Lane3Ledger, 'BUFFER_API_KEY_3')}


def main():
    keys = [k.strip() for k in env('INPUT_KEYS').split(',') if k.strip()]
    gh = GitHub(env('GITHUB_REPOSITORY'), env('GITHUB_TOKEN'))
    out = {}
    groups = {}
    for k in keys:
        lane = lane_of(k)
        if lane is None:
            out[k] = 'unknown lane'
        else:
            groups.setdefault(lane, []).append(k)
    for lane, ks in groups.items():
        cls, secret = LEDGERS[lane]
        L = cls(gh); L.load()
        buf = Buffer(token=env(secret))
        for k in ks:
            r = L.data['records'].get(k)
            if not r or r.get('state') != 'submitted' or not r.get('buffer_post_id'):
                out[k] = 'not a queued post (' + str((r or {}).get('state')) + ')'; continue
            due = parse_time(r.get('scheduled_at') or r.get('due_at'))
            if due < parse_time(now()) + timedelta(minutes=10):
                out[k] = 'already due, kept'; continue
            res = buf.query('mutation($input: DeletePostInput!) { deletePost(input: $input) { __typename '
                            '... on MutationError { message } } }', {'input': {'id': r['buffer_post_id']}})['deletePost']
            if 'Error' in str(res.get('__typename')):
                out[k] = 'delete rejected: ' + str(res.get('message'))[:200]; continue
            r['state'] = 'skipped'
            r['skip_reason'] = 'owner_removed'
            r['skipped_at'] = now()
            L.data.setdefault('events', []).append({'action': 'owner_removed', 'at': now(), 'record': k})
            out[k] = 'deleted from Buffer, never scheduled again'
            L.save()
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()

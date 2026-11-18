"""Owner-requested edit of one clip's already-queued Buffer posts (all lanes): move the time and/or swap the video URL.
Used when Blert asks for a queued clip to be changed. Records are updated so the lanes keep tracking the same posts."""
import json, os, re
from .buffer import Buffer, payload, POST_FIELDS
from .common import Stop, env, now, require
from .github import GitHub, GitHubLedger
from . import lane2


class Lane2Ledger(GitHubLedger):
    PATH = 'lane2-state.json'


def edit(buf, post_id, data):
    data = {k: v for k, v in data.items() if k not in ('channelId', 'needsApproval')}
    data['id'] = post_id
    r = buf.query('mutation($input: EditPostInput!) { editPost(input: $input) { __typename '
                  '... on PostActionSuccess { post { id dueAt } } ... on MutationError { message } } }', {'input': data})['editPost']
    if r.get('__typename') != 'PostActionSuccess':
        raise Stop('edit rejected: ' + re.sub(r'https?://\S+', '[URL]', str(r.get('message')))[:300])
    return r['post']


def main():
    cid = env('INPUT_CLIP_ID'); due = env('INPUT_DUE_AT'); url = os.environ.get('INPUT_MEDIA_URL', '').strip()
    require(re.fullmatch(r'M\d{6}', cid), 'Bad clip id.')
    require(not url or url.startswith('https://'), 'Bad media URL.')
    gh = GitHub(env('GITHUB_REPOSITORY'), env('GITHUB_TOKEN')); bufs = {'main': Buffer(), 'lane2': Buffer(token=env('BUFFER_API_KEY_2'))}; out = []
    for L, prefix in ((GitHubLedger(gh), cid + ':'), (Lane2Ledger(gh), 'motivtated:' + cid + ':')):
        L.load(); changed = False
        for k, r in L.data['records'].items():
            if not k.startswith(prefix) or r.get('state') != 'submitted' or not r.get('buffer_post_id') or r.get('media', {}).get('url') == url:
                continue
            p = r['platform']; media = url or r['media']['url']
            if p in ('youtube', 'twitter'):
                data = lane2.build_payload(p, r['channel_id'], r['caption'], media, due, r.get('title'))
            else:
                data = payload(p, r['channel_id'], r['caption'], media, due)
            try:
                post = edit(bufs['lane2' if p in ('youtube', 'twitter') else 'main'], r['buffer_post_id'], data)
            except Exception as exc:
                out.append({k: 'FAILED ' + str(exc)[:200]}); continue
            for f in ('scheduled_at', 'due_at'):
                if f in r: r[f] = due
            if url:
                r['media'] = {**r['media'], 'url': url, 'replaced_by_owner_at': now()}
            r['owner_edit_at'] = now(); changed = True
            out.append({k: post.get('dueAt')})
        if changed and not (isinstance(L, GitHubLedger) and type(L) is GitHubLedger and os.environ.get('INPUT_KEEP_MAIN_LEDGER') == 'true'):
            L.data.setdefault('events', []).append({'action': 'owner_edit', 'at': now(), 'record': cid})
            L.save()
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()

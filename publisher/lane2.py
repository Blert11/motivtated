"""Lane 2: schedule YouTube Shorts and X posts through the SECOND Buffer account.

Completely separate from the TikTok/Instagram/Facebook scheduler (scheduler.py):
own Buffer key (BUFFER_API_KEY_2), own plan (lane2-schedule.json), own ledger
(lane2-state.json on the publisher-state branch) and its own hosted-media prefix
(media2/) in the shared Pages repo. Same safety rules: a Buffer create is never
retried automatically, every transition is saved before the next call.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .buffer import Buffer, SchemaRejected
from .bundles import MAX_VIDEO, probe, unpack
from .common import Stop, env, now, require, sha256
from .github import GitHub, GitHubLedger
from .media import verify_public

TZ = ZoneInfo('Europe/Budapest')
SLOTS = {'motivtated': [(10, 0), (12, 0), (14, 0), (16, 0), (18, 0), (20, 0), (21, 30)],   # 7 a day from Nov 14 (2026-11-13; was 6)
         'imanivated': [(10, 0), (12, 0), (14, 0), (18, 0), (20, 0), (21, 30)]}   # 5 a day from Nov 16 (2026-11-11); 20:00 only for the dhikr videos (2026-11-18)
PAGES = {'motivtated': ('youtube', 'twitter'), 'imanivated': ('youtube',)}
RELEASES = {'motivtated': 'posting-inputs', 'imanivated': 'imanivated-inputs'}
ID_RE = {'motivtated': r'M\d{6}', 'imanivated': r'I\d{6}'}
EMOJI = {'motivtated': ('👑', '🥇', '🏆'), 'imanivated': ('🤲', '🕋', '📿')}
YT_CATEGORY = '22'          # People & Blogs
MAX_NEW_PER_RUN = 4
PAGES_CAP = 900_000_000


class Lane2Ledger(GitHubLedger):
    PATH = 'lane2-state.json'


def parse_time(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(t.tzinfo is not None, 'Timestamps need a timezone.')
    return t


def validate_plan(plan):
    require(plan.get('version') == 1 and plan.get('enabled') in (True, False), 'Unsupported lane-2 plan.')
    require(plan.get('max_pending_per_channel', 6) <= 10, 'Buffer free holds at most 10 per channel.')
    seen, last, per_day = set(), {}, {}
    for row in plan['rows']:
        page = row['page']
        require(page in PAGES and re.fullmatch(ID_RE[page], row['clip_id']), 'Bad page/clip ID.')
        require(row['key'] == page+':'+row['clip_id'] and row['key'] not in seen, 'Duplicate or bad row key.')
        seen.add(row['key'])
        require(re.fullmatch(r'[0-9a-f]{64}', row['bundle_sha256']), 'Bad bundle digest.')
        require(re.fullmatch(re.escape(row['clip_id'])+r'(\.r[0-9]{1,2})?\.zip', row['asset_name']), 'Bad asset name.')
        require(set(row['platforms']) <= set(PAGES[page]) and row['platforms'], 'Bad platforms.')
        due = parse_time(row['due_at']).astimezone(TZ)
        require((due.hour, due.minute) in SLOTS[page] and due.second == 0, 'Unexpected slot.')
        require(page not in last or due > last[page], 'Times must increase per page.')
        last[page] = due
        per_day[(page, due.date())] = per_day.get((page, due.date()), 0)+1
        require(per_day[(page, due.date())] <= len(SLOTS[page]), 'Too many posts in one day for this page.')
        require(len(row.get('title') or '') <= 100, 'YouTube title too long.')
    return plan['rows']


def clean_text(caption):
    t = re.sub(r'#\w+', '', caption)
    for e in sum(EMOJI.values(), ()):
        t = t.replace(e, '')
    return re.sub(r'\s+', ' ', t).strip()


def youtube_title(row, caption):
    title = (row.get('title') or clean_text(caption)).replace('<', '').replace('>', '')
    return title[:100].rstrip()


def build_payload(platform, channel_id, caption, url, due_at, title=None):
    data = {'text': caption, 'channelId': channel_id, 'schedulingType': 'automatic',
            'mode': 'customScheduled', 'dueAt': due_at, 'saveToDraft': False,
            'assets': [{'video': {'url': url}}]}
    if platform == 'youtube':
        require(title, 'YouTube posts need a title.')
        data['metadata'] = {'youtube': {'title': title, 'categoryId': YT_CATEGORY, 'madeForKids': False}}
    else:
        require(platform == 'twitter', 'Unsupported lane-2 platform.')
    return data


def unpack_iman(bundle, expected_hash, directory):
    """Same checks as bundles.unpack, but for #imanivated captions."""
    require(sha256(bundle) == expected_hash, 'Bundle SHA256 does not match the plan.')
    names = {'video.mp4', 'caption.txt', 'metadata.json', 'manifest.json'}
    with zipfile.ZipFile(bundle) as z:
        require(set(z.namelist()) == names and len(z.namelist()) == 4, 'Unexpected bundle members.')
        for info in z.infolist():
            require(info.file_size <= (MAX_VIDEO if info.filename == 'video.mp4' else 1 << 20), 'Member too large.')
            (directory/info.filename).write_bytes(z.read(info))
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    for name, exp in manifest['files'].items():
        p = directory/name
        require(p.stat().st_size == exp['size'] and sha256(p) == exp['sha256'], f'{name} hash mismatch.')
    caption = (directory/'caption.txt').read_text(encoding='utf-8').strip()
    require(caption == manifest['caption'] and re.findall(r'#\w+', caption) == ['#imanivated'], 'Bad Imanivated caption.')
    probe(directory/'video.mp4', max_seconds=175)   # YouTube Shorts allow up to 3 min; the dhikr videos (2026-11-18) run 128 s
    return manifest


def download_asset(gh, release, name, destination, expected_hash):
    rel = gh.request('GET', f'/releases/tags/{release}')
    assets = [a for a in rel.get('assets', []) if a.get('name') == name]
    require(len(assets) == 1 and assets[0].get('state') == 'uploaded', f'Release asset {name} missing.')
    if assets[0].get('digest'):
        require(assets[0]['digest'] == 'sha256:'+expected_hash, f'{name} digest differs from the plan.')
    r = subprocess.run(['gh', 'release', 'download', release, '--repo', gh.repo, '--pattern', name,
                        '--output', str(destination)],
                       env={**os.environ, 'GH_TOKEN': env('GITHUB_TOKEN'), 'GH_PROMPT_DISABLED': '1'},
                       capture_output=True, timeout=300)
    require(r.returncode == 0 and destination.is_file() and sha256(destination) == expected_hash,
            f'Download of {name} failed or hash mismatch.')


class Media:
    """Hosts lane-2 clips as assets of a public release in the media repo.

    GitHub Pages deploys lagged (and have an hourly build limit), so lane 2 no
    longer pushes files to Pages: a release asset is public as soon as the
    upload returns. Older records hosted on Pages (media2/) are still cleaned.
    """
    TAG = 'lane2-media'

    def __init__(self, gh, base):
        self.gh, self.base = gh, base.rstrip('/')
        repo = gh.request('GET')
        require(repo.get('private') is False, 'Media repo must be public.')
        self.branch = repo['default_branch']
        self._release = None

    def release(self):
        if not self._release:
            rel = self.gh.request('GET', f'/releases/tags/{self.TAG}', missing_ok=True)
            if not rel:
                rel = self.gh.request('POST', '/releases', {'tag_name': self.TAG, 'target_commitish': self.branch,
                                      'name': 'Lane 2 media (temporary)', 'body': 'Clips waiting to post; removed after posting.',
                                      'draft': False, 'prerelease': True})
            self._release = rel
        return self._release

    def ensure(self, path, cid, digest):
        name = f'{cid}-{digest[:16]}.mp4'
        rel = self.release()
        assets = self.gh.request('GET', f"/releases/{rel['id']}/assets?per_page=100")
        found = [a for a in assets if a['name'] == name]
        if not found:
            raw = path.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == digest, 'Video changed before upload.')
            url = f"https://uploads.github.com/repos/{self.gh.repo}/releases/{rel['id']}/assets?name={name}"
            req = urllib.request.Request(url, data=raw, method='POST', headers={
                **self.gh.headers, 'Content-Type': 'video/mp4', 'Content-Length': str(len(raw))})
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    asset = json.loads(r.read())
            except Exception:
                raise Stop('Release asset upload failed; nothing was posted.') from None
        else:
            asset = found[0]
        require(asset.get('state') == 'uploaded' and asset.get('size') == path.stat().st_size, 'Uploaded asset incomplete.')
        if asset.get('digest'):
            require(asset['digest'] == 'sha256:'+digest, 'Uploaded asset digest mismatch.')
        return {'kind': 'release', 'asset_id': asset['id'], 'name': name, 'url': asset['browser_download_url']}

    def delete(self, media):
        if media.get('kind') == 'release':
            self.gh.request('DELETE', f"/releases/assets/{media['asset_id']}", missing_ok=True)
            return
        existing = self.gh.file(media['key'], self.branch, True)
        if existing and existing.get('sha') == media['git_sha']:
            self.gh.request('DELETE', '/contents/'+media['key'],
                            {'message': 'Remove posted lane-2 media', 'branch': self.branch, 'sha': existing['sha']})


def discover_channels(buffer, ledger):
    orgs = buffer.organizations()
    require(len(orgs) == 1, f'Expected one organization on the second Buffer account, found {len(orgs)}.')
    chans = [c for c in buffer.channels(orgs[0]['id']) if not c['isDisconnected'] and not c['isLocked']]
    ledger.data['channels_seen'] = [{'id': c['id'], 'name': c.get('name'), 'service': c['service']} for c in chans]
    yt = [c for c in chans if c['service'] == 'youtube']
    tw = [c for c in chans if c['service'] == 'twitter']
    iman = [c for c in yt if 'iman' in (c.get('name') or '').lower()]
    motiv = [c for c in yt if c not in iman]
    found = {}
    if len(motiv) == 1:
        found['motivtated:youtube'] = motiv[0]['id']
    if len(iman) == 1:
        found['imanivated:youtube'] = iman[0]['id']
    if len(tw) == 1:
        found['motivtated:twitter'] = tw[0]['id']
    ledger.data['organization_id'] = orgs[0]['id']
    ledger.data['channels'] = found
    return found


class Lane2:
    def __init__(self, plan, ledger, buffer, media, gh, clock=None):
        self.plan, self.rows = plan, validate_plan(plan)
        self.ledger, self.buffer, self.media, self.gh = ledger, buffer, media, gh
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.report = {'scheduled': [], 'posted': [], 'cleaned': [], 'skipped_missed': [], 'problems': []}

    @property
    def records(self):
        return self.ledger.data.setdefault('records', {})

    def event(self, key, action):
        self.ledger.data.setdefault('events', []).append({'at': now(), 'record': key, 'action': action})
        self.ledger.data['events'] = self.ledger.data['events'][-400:]
        self.ledger.save()

    def reconcile(self):
        for key, rec in self.records.items():
            if rec['state'] != 'submitted' or parse_time(rec['due_at']) > self.clock():
                continue
            try:
                post = self.buffer.post(rec['buffer_post_id'])
            except Stop as exc:
                self.report['problems'].append(f'{key}: lookup failed ({str(exc)[:120]})')
                continue
            rec['buffer_status'] = post['status']
            if post['status'] == 'sent':
                rec['state'], rec['sent_at'], rec['post_url'] = 'posted', post.get('sentAt') or now(), post.get('externalLink')
                self.report['posted'].append(key)
            elif post['status'] == 'error':
                rec['state'] = 'failed_at_buffer'
                self.report['problems'].append(f'{key}: Buffer reported an error')
            self.event(key, 'reconciled_'+post['status'])

    def cleanup(self):
        by_row = {}
        for key, rec in self.records.items():
            by_row.setdefault(rec['row'], []).append(rec)
        for row_key, recs in by_row.items():
            media = next((r['media'] for r in recs if r.get('media')), None)
            if not media or any(r.get('media_deleted_at') for r in recs):
                continue
            row = next((r for r in self.rows if r['key'] == row_key), None)
            done = row and all(any(r['platform'] == p and r['state'] in ('posted', 'failed_at_buffer', 'failed_before_submit', 'needs_attention', 'skipped_missed')
                                   for r in recs) for p in row['platforms'])
            sent = [parse_time(r['sent_at']) for r in recs if r.get('sent_at')]
            if done and all(self.clock()-s > timedelta(hours=2) for s in sent):
                self.media.delete(media)
                for r in recs:
                    r['media_deleted_at'] = now()
                self.event(row_key, 'media_cleaned')
                self.report['cleaned'].append(row_key)

    def pending(self, channel):
        return sum(1 for r in self.records.values() if r['channel_id'] == channel and r['state'] in ('submitted', 'preparing', 'submit_intent'))

    def load(self, row, directory):
        bundle = directory/'input.zip'
        download_asset(self.gh, RELEASES[row['page']], row['asset_name'], bundle, row['bundle_sha256'])
        content = directory/'content'
        content.mkdir()
        manifest = (unpack if row['page'] == 'motivtated' else unpack_iman)(bundle, row['bundle_sha256'], content)
        require(manifest['clip_id'] == row['clip_id'], 'Package clip ID differs from the plan.')
        return manifest, content

    def fill(self, channels):
        cap = self.plan.get('max_pending_per_channel', 6)
        counts = {cid: self.pending(cid) for cid in channels.values()}
        new = 0
        for row in self.rows:
            if new >= getattr(self, 'max_new', MAX_NEW_PER_RUN):
                break
            todo = []
            for p in row['platforms']:
                ch = channels.get(row['page']+':'+p)
                if not ch:
                    continue
                key = row['key']+':'+p
                old = self.records.get(key)
                if old and not (old['state'] == 'failed_before_submit' and old.get('attempts', 1) < 3):
                    continue   # one post's failure is retried up to 3 times, then left alone; others carry on
                if parse_time(row['due_at']) <= self.clock()+timedelta(minutes=15):
                    # Never post a backlog in a burst: a missed slot is skipped and recorded.
                    self.records[key] = {'row': row['key'], 'platform': p, 'channel_id': ch, 'state': 'skipped_missed',
                                         'due_at': row['due_at']}
                    self.report['skipped_missed'].append(key)
                    continue
                if counts[ch] >= cap:
                    continue
                todo.append((p, ch, key))
            if not todo:
                continue
            try:
                self.fill_row(row, todo, counts)
            except Exception as exc:
                # Owner rule (2026-11-14): one failing post never stops the others, on any platform or page.
                if self.report.get('deferred_for_storage') == row['key']:
                    break                    # media host full: not a failure, refill next hour
                msg = str(exc)[:300] if isinstance(exc, Stop) else type(exc).__name__
                for p, ch, key in todo:
                    rec = self.records.get(key)
                    if rec and rec.get('state') not in ('failed_before_submit', None):
                        continue
                    prev = (rec or {}).get('attempts', 0)
                    self.records[key] = {'row': row['key'], 'clip_id': row['clip_id'], 'page': row['page'], 'platform': p,
                                         'channel_id': ch, 'due_at': row['due_at'], 'state': 'failed_before_submit',
                                         'attempts': prev + 1, 'error': msg, 'created_at': now()}
                    self.event(key, 'failed_before_submit')
                self.report['problems'].append(f"{row['key']}: {msg[:200]}")
            new += 1

    def fill_row(self, row, todo, counts):
        with tempfile.TemporaryDirectory(prefix='lane2-') as scratch:
            manifest, content = self.load(row, Path(scratch))
            vid = manifest['files']['video.mp4']
            media = next((r['media'] for r in self.records.values() if r['row'] == row['key'] and r.get('media')
                          and not r.get('media_deleted_at')), None)
            if not media:
                media = self.media.ensure(content/'video.mp4', row['clip_id'], vid['sha256'])
                if media is None:
                    self.report['deferred_for_storage'] = row['key']
                    raise Stop('Media host full; deferred.')
                verify_wait(media, manifest, content)
            caption = manifest['caption']
            for p, ch, key in todo:
                title = youtube_title(row, caption) if p == 'youtube' else None
                rec = {'row': row['key'], 'clip_id': row['clip_id'], 'page': row['page'], 'platform': p,
                       'channel_id': ch, 'due_at': row['due_at'], 'caption': caption, 'title': title,
                       'media': media, 'state': 'submit_intent', 'created_at': now()}
                self.records[key] = rec
                self.event(key, 'before_buffer_createPost')
                try:
                    post = create_post(self.buffer, build_payload(p, ch, caption, media['url'], row['due_at'], title))
                except SchemaRejected as exc:
                    rec['state'], rec['error'] = 'failed_before_submit', str(exc)[:600]
                    self.event(key, 'buffer_rejected_before_execution')
                    self.report['problems'].append(f'{key}: {str(exc)[:200]}')
                    continue
                except Stop as exc:
                    # Outcome unknown: never resubmitted (no duplicates), but the queue keeps going.
                    rec['state'], rec['error'] = 'needs_attention', str(exc)[:600]
                    self.event(key, 'uncertain_create_outcome')
                    self.report['problems'].append(f'{key}: uncertain create, left for review')
                    continue
                rec['buffer_post_id'], rec['buffer_status'] = post['id'], post['status']
                rec['state'] = 'submitted' if post['status'] in ('scheduled', 'sending') else 'needs_attention'
                self.event(key, 'buffer_post_id_received')
                counts[ch] += 1
                self.report['scheduled'].append({'key': key, 'due_at': row['due_at'], 'post_id': post['id']})

    def retitle(self):
        """Bring pending YouTube titles in line with the plan (2026-11-12: the owner asked that one speaker's
        name never appears in anything posted). Edits only scheduled posts due later than 20 minutes from now,
        resending the recorded caption and video with the new title; a refusal is recorded and never retried."""
        rows = {r['key']: r for r in self.rows}
        self.report['retitled'] = []
        for key, rec in self.records.items():
            row = rows.get(rec.get('row'))
            if not row or rec.get('platform') != 'youtube' or rec.get('state') != 'submitted' or rec.get('retitle_error'):
                continue
            want = youtube_title(row, rec.get('caption') or '')
            if not rec.get('buffer_post_id') or not rec.get('media') or want == rec.get('title'):
                continue
            if parse_time(rec['due_at']) <= self.clock() + timedelta(minutes=20):
                continue
            edit = build_payload('youtube', rec['channel_id'], rec['caption'], rec['media']['url'], rec['due_at'], want)
            edit.pop('channelId'); edit['id'] = rec['buffer_post_id']
            try:
                res = self.buffer.query('mutation($input: EditPostInput!) { editPost(input: $input) { __typename '
                                        '... on PostActionSuccess { post { id status dueAt } } '
                                        '... on MutationError { message } } }', {'input': edit})['editPost']
            except Exception as exc:
                rec['retitle_error'] = type(exc).__name__ + ': ' + str(exc)[:300]
                self.report['problems'].append(f'{key}: retitle failed')
                continue
            if res.get('__typename') == 'PostActionSuccess':
                rec['previous_title'], rec['title'] = rec.get('title'), want
                self.event(key, 'youtube_title_edited')
                self.report['retitled'].append(key)
            else:
                rec['retitle_error'] = str(res.get('message'))[:300]
                self.report['problems'].append(f'{key}: retitle refused')

    def run(self):
        self.report = {'scheduled': [], 'posted': [], 'cleaned': [], 'skipped_missed': [], 'problems': []}
        if not self.plan.get('enabled'):
            return {'enabled': False}
        channels = self.ledger.data.get('channels') or {}
        if set(channels) != {'motivtated:youtube', 'motivtated:twitter', 'imanivated:youtube'}:
            channels = discover_channels(self.buffer, self.ledger)
            self.ledger.save()
        self.report['channels'] = channels
        self.reconcile()
        self.retitle()
        self.cleanup()
        self.fill(channels)
        return self.report


class MutationRejected(SchemaRejected):
    """Buffer answered with a MutationError: the post was not created."""


def create_post(buffer, payload):
    result = buffer.query('mutation($input: CreatePostInput!) { createPost(input: $input) { __typename '
                          '... on PostActionSuccess { post { id status dueAt channelId } } '
                          '... on MutationError { message } } }', {'input': payload})['createPost']
    if result.get('__typename') == 'PostActionSuccess' and (result.get('post') or {}).get('id'):
        return result['post']
    if result.get('message'):
        raise MutationRejected('Buffer refused: '+re.sub(r'https?://\S+', '[URL]', str(result['message']))[:400])
    raise Stop('Buffer did not confirm a post ID; inspect Buffer before any retry.')


def verify_wait(media, manifest, directory):
    import time
    for attempt in range(49):
        try:
            return verify_public({'url': media['url']}, manifest, directory)
        except Stop as exc:
            if attempt == 48 or not str(exc).startswith('Download failed;'):
                raise
            time.sleep(15)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--plan', type=Path, default=Path('lane2-schedule.json'))
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    rows = validate_plan(plan)
    if args.dry_run:
        print(json.dumps({'validation': 'passed', 'rows': len(rows)}))
        return
    gh = GitHub(env('GITHUB_REPOSITORY'), env('GITHUB_TOKEN'))
    ledger = Lane2Ledger(gh)
    ledger.initialize()
    media = Media(GitHub(env('MEDIA_GITHUB_REPOSITORY'), env('MEDIA_GITHUB_TOKEN')), env('MEDIA_PUBLIC_BASE_URL'))
    lane = Lane2(plan, ledger, Buffer(token=env('BUFFER_API_KEY_2')), media, gh)
    try:
        report = lane.run()
        status = 'ok'
    except Exception as exc:
        report = {**lane.report, 'error': str(exc)[:600] if isinstance(exc, Stop) else type(exc).__name__}
        status = 'stopped'
    ledger.data['last_run'] = {'at': now(), 'status': status, 'report': report}
    ledger.save()
    print(json.dumps(report, ensure_ascii=False))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('Lane 2 (YouTube/X)\n\n```json\n'+json.dumps(report, indent=2, ensure_ascii=False)+'\n```\n')
    if status != 'ok':
        raise SystemExit(2)


if __name__ == '__main__':
    main()

"""Lane 5: @motivtated and @imanivated YouTube Shorts through Zernio (authorized by Blert on 2026-11-21).

Buffer's free plan only allows 2 YouTube posts per channel a day, so YouTube moved to Zernio (free for 2 connected
accounts, no post cap, API key in the ZERNIO_API_KEY secret). Lane 2 keeps posting to X only.

- Plan: lane5-schedule.json holds the clip ORDER only. Each clip gets the next free slot of its page when it is
  scheduled (never earlier than 40 minutes from now), so a late start or a pause never loses clips and never
  posts a backlog in a burst.
- Slots: 6 a day per page (lane5-schedule.json `slots`), Europe/Budapest.
- Safety, same as the Buffer lanes: a create is never retried after an unclear answer, every transition is saved
  before the next call, one failing post never stops the others, and a clip already posted or still queued on
  Buffer YouTube (lane2-state.json) is never sent again.
- Media: public release `lane5-media` in the media repo, deleted 2 h after the post is published.
"""
import argparse
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import lane2
from .common import Stop, env, now, require
from .github import GitHub, GitHubLedger

TZ = lane2.TZ
API = 'https://zernio.com/api/v1'
MAX_NEW_PER_RUN = 24   # fill ~2 days per page in one run: runs are kept rare to save Actions minutes
LEAD = timedelta(minutes=40)
STORY_RELEASE = 'animated-inputs'
STORY_ID = {'motivtated': r'MA\d{4}', 'imanivated': r'IA\d{4}'}
STORY_HORIZON = timedelta(hours=36)   # fixed-time rows are created at most this far ahead


class Lane5Ledger(GitHubLedger):
    PATH = 'lane5-state.json'


class Lane2Ledger(GitHubLedger):
    PATH = 'lane2-state.json'


class Media(lane2.Media):
    TAG = 'lane5-media'

    def release(self):
        if not self._release:
            rel = self.gh.request('GET', f'/releases/tags/{self.TAG}', missing_ok=True)
            if not rel:
                rel = self.gh.request('POST', '/releases', {'tag_name': self.TAG, 'target_commitish': self.branch,
                                      'name': 'Lane 5 media (temporary)', 'body': 'Shorts waiting to post; removed after posting.',
                                      'draft': False, 'prerelease': True})
            self._release = rel
        return self._release


class Zernio:
    def __init__(self, key, opener=None):
        self.key = key
        self.opener = opener or urllib.request.urlopen

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(API+path, data=data, method=method, headers={
            'Authorization': 'Bearer '+self.key, 'Content-Type': 'application/json', 'Accept': 'application/json',
            'User-Agent': 'motivtated-lane5'})
        try:
            with self.opener(req, timeout=120) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read() or b'{}')
            except Exception:
                payload = {}
            return e.code, payload

    def accounts(self):
        code, j = self.call('GET', '/accounts')
        require(code == 200, f'Zernio accounts lookup failed ({code}).')
        return j.get('accounts', [])

    def post(self, post_id):
        code, j = self.call('GET', '/posts/'+post_id)
        require(code == 200, f'Zernio post lookup failed ({code}).')
        return j.get('post', j)


def post_id(answer):
    p = answer.get('post', answer)
    return p.get('_id') or p.get('id')


def validate_plan(plan):
    require(plan.get('version') == 1 and plan.get('enabled') in (True, False), 'Unsupported lane-5 plan.')
    slots = plan['slots']
    require(set(slots) == {'motivtated', 'imanivated'}, 'Slots needed for both pages.')
    for page, s in slots.items():
        require(1 <= len(s) <= 10 and all(re.fullmatch(r'\d{2}:\d{2}', t) for t in s) and s == sorted(set(s)), 'Bad slots.')
    seen = set()
    for row in plan['rows']:
        page = row['page']
        story = row.get('release') == STORY_RELEASE   # animated stories (2026-11-28): fixed time, own release
        require(page in slots and re.fullmatch(STORY_ID[page] if story else lane2.ID_RE[page], row['clip_id']), 'Bad page/clip ID.')
        require(story == ('due_at' in row), 'Fixed times only for animated story rows.')
        if story:
            due = lane2.parse_time(row['due_at'])
            require(due.second == 0, 'Bad fixed time.')
        require(row['key'] == page+':'+row['clip_id'] and row['key'] not in seen, 'Duplicate or bad row key.')
        seen.add(row['key'])
        require(re.fullmatch(r'[0-9a-f]{64}', row['bundle_sha256']), 'Bad bundle digest.')
        require(re.fullmatch(re.escape(row['clip_id'])+r'(\.r[0-9]{1,2})?\.zip', row['asset_name']), 'Bad asset name.')
        require(len(row.get('title') or '') <= 100, 'YouTube title too long.')
        row.setdefault('platforms', ['youtube'])
    return plan['rows']


def next_slot(slots, after, taken=()):
    """First slot (Europe/Budapest) strictly after `after`, skipping times held by fixed-time rows."""
    local = after.astimezone(TZ)
    for d in range(0, 30):
        day = (local + timedelta(days=d)).date()
        for t in slots:
            h, m = map(int, t.split(':'))
            cand = datetime(day.year, day.month, day.day, h, m, tzinfo=TZ)
            if cand > local and cand not in taken:
                return cand
    raise Stop('No free slot found.')


def build_payload(account_id, caption, url, due, title):
    require(title, 'YouTube posts need a title.')
    return {'content': caption, 'mediaItems': [{'type': 'video', 'url': url}],
            'platforms': [{'platform': 'youtube', 'accountId': account_id, 'platformSpecificData': {
                'title': title, 'visibility': 'public', 'categoryId': lane2.YT_CATEGORY, 'madeForKids': False}}],
            'scheduledFor': due.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}


class Lane5(lane2.Lane2):
    def __init__(self, plan, ledger, zernio, media, gh, buffer_ledger=None, clock=None):
        removed = set(plan.get('removed_ids', []))
        self.plan, self.rows = plan, [r for r in validate_plan(plan) if not (r['page'] == 'motivtated' and r['clip_id'] in removed)]
        self.ledger, self.zernio, self.media, self.gh = ledger, zernio, media, gh
        self.buffer_ledger = buffer_ledger
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.report = {'scheduled': [], 'posted': [], 'cleaned': [], 'skipped_missed': [], 'problems': []}

    def on_buffer(self):
        """Clips Buffer YouTube already posted or still holds: never sent again through Zernio."""
        result = set()
        for key, rec in ((self.buffer_ledger.data or {}).get('records') or {}).items() if self.buffer_ledger else ():
            if rec.get('platform') == 'youtube' and rec.get('state') in ('posted', 'submitted', 'submit_intent', 'needs_attention'):
                result.add(key.split(':')[0]+':'+(rec.get('clip_id') or key.split(':')[1].split('-')[0]))
        return result

    def discover(self):
        found = {}
        for a in self.zernio.accounts():
            if a.get('platform') == 'youtube' and a.get('isActive', True):
                name = (a.get('username') or '').lower()
                if name in ('motivtated', 'imanivated'):
                    found[name] = a['_id']
        self.ledger.data['accounts'] = found
        return found

    def reconcile(self):
        for key, rec in self.records.items():
            if rec['state'] != 'submitted' or lane2.parse_time(rec['due_at']) > self.clock():
                continue
            try:
                post = self.zernio.post(rec['zernio_post_id'])
            except Stop as exc:
                self.report['problems'].append(f'{key}: lookup failed ({str(exc)[:120]})')
                continue
            status = post.get('status')
            rec['zernio_status'] = status
            if status == 'published':
                plat = (post.get('platforms') or [{}])[0]
                rec['state'], rec['sent_at'] = 'posted', plat.get('publishedAt') or now()
                rec['post_url'] = plat.get('platformPostUrl')
                self.report['posted'].append(key)
                self.event(key, 'reconciled_published')
            elif status in ('failed', 'partial', 'cancelled'):
                plat = (post.get('platforms') or [{}])[0]
                rec['state'], rec['error'] = 'failed_at_zernio', str(plat.get('errorMessage') or status)[:400]
                self.report['problems'].append(f'{key}: {rec["error"][:150]}')
                self.event(key, 'reconciled_'+status)

    def load(self, row, directory):
        if row.get('release') != STORY_RELEASE:
            return super().load(row, directory)
        from .lane6 import unpack_story
        bundle = directory/'input.zip'
        lane2.download_asset(self.gh, STORY_RELEASE, row['asset_name'], bundle, row['bundle_sha256'])
        content = directory/'content'
        content.mkdir()
        manifest = unpack_story(bundle, row['bundle_sha256'], content, row['page'], max_seconds=180)   # Shorts: 3 min
        require(manifest['clip_id'] == row['clip_id'], 'Package clip ID differs from the plan.')
        return manifest, content

    def taken(self, page):
        return {lane2.parse_time(r['due_at']) for r in self.rows if r['page'] == page and r.get('due_at')}

    def last_due(self, page):
        times = [lane2.parse_time(r['due_at']) for r in self.records.values()
                 if r.get('page') == page and not r.get('fixed') and r['state'] in ('submitted', 'posted', 'submit_intent', 'needs_attention')]
        return max(times) if times else None

    def pending(self, page):
        return sum(1 for r in self.records.values() if r.get('page') == page and r['state'] in ('submitted', 'submit_intent'))

    def fill(self, accounts):
        cap = self.plan.get('max_pending_per_channel', 12)
        skip = self.on_buffer()
        new = 0
        for row in self.rows:
            if new >= MAX_NEW_PER_RUN:
                break
            page, key = row['page'], row['key']+':youtube'
            acc = accounts.get(page)
            if not acc or row['key'] in skip:
                continue
            old = self.records.get(key)
            if old and not (old['state'] == 'failed_before_submit' and old.get('attempts', 1) < 3):
                continue
            if row.get('due_at'):
                due = lane2.parse_time(row['due_at'])
                if due <= self.clock()+LEAD:
                    self.records[key] = {'row': row['key'], 'clip_id': row['clip_id'], 'page': page, 'platform': 'youtube',
                                         'channel_id': acc, 'due_at': row['due_at'], 'state': 'skipped_missed', 'fixed': True}
                    self.report['skipped_missed'].append(key)
                    continue
                if due > self.clock()+STORY_HORIZON:
                    continue
            else:
                if self.pending(page) >= cap:
                    continue
                base = max([t for t in (self.last_due(page), self.clock()+LEAD) if t])
                due = next_slot(self.plan['slots'][page], base, self.taken(page))
            try:
                self.fill_one(row, key, acc, due)
            except Exception as exc:
                if self.report.get('deferred_for_storage') == row['key']:
                    break
                msg = str(exc)[:300] if isinstance(exc, Stop) else type(exc).__name__
                prev = (old or {}).get('attempts', 0)
                self.records[key] = {'row': row['key'], 'clip_id': row['clip_id'], 'page': page, 'platform': 'youtube',
                                     'channel_id': acc, 'due_at': due.isoformat(), 'state': 'failed_before_submit',
                                     'attempts': prev+1, 'error': msg, 'created_at': now()}
                if row.get('due_at'):
                    self.records[key]['fixed'] = True
                if prev+1 >= 3:
                    self.records[key]['state'] = 'skipped'
                self.event(key, 'failed_before_submit')
                self.report['problems'].append(f"{row['key']}: {msg[:200]}")
            new += 1

    def fill_one(self, row, key, acc, due):
        with tempfile.TemporaryDirectory(prefix='lane5-') as scratch:
            manifest, content = self.load(row, Path(scratch))
            vid = manifest['files']['video.mp4']
            media = self.media.ensure(content/'video.mp4', row['clip_id'], vid['sha256'])
            lane2.verify_wait(media, manifest, content)
            caption = manifest['caption']
            title = lane2.youtube_title(row, caption)
            rec = {'row': row['key'], 'clip_id': row['clip_id'], 'page': row['page'], 'platform': 'youtube',
                   'channel_id': acc, 'due_at': due.isoformat(), 'caption': caption, 'title': title,
                   'media': media, 'state': 'submit_intent', 'created_at': now()}
            if row.get('due_at'):
                rec['fixed'] = True
            self.records[key] = rec
            self.event(key, 'before_zernio_create')
            try:
                code, answer = self.zernio.call('POST', '/posts', build_payload(acc, caption, media['url'], due, title))
            except Exception as exc:
                rec['state'], rec['error'] = 'needs_attention', type(exc).__name__   # outcome unknown: never resent
                self.event(key, 'uncertain_create_outcome')
                self.report['problems'].append(f'{key}: uncertain create, left for review')
                return
            pid = post_id(answer) if isinstance(answer, dict) else None
            if code in (200, 201) and pid:
                rec['zernio_post_id'], rec['state'] = pid, 'submitted'
                rec['zernio_status'] = answer.get('post', answer).get('status')
                self.event(key, 'zernio_post_id_received')
                self.report['scheduled'].append({'key': key, 'due_at': rec['due_at'], 'post_id': pid})
            elif 400 <= code < 500 and code != 409:
                rec['state'], rec['error'] = 'failed_before_submit', (str(answer.get('error') or answer.get('message') or answer))[:400]
                rec['attempts'] = 1
                self.event(key, 'zernio_rejected')
                self.report['problems'].append(f'{key}: Zernio refused ({code}): {rec["error"][:150]}')
            else:
                rec['state'], rec['error'] = 'needs_attention', f'HTTP {code}: {str(answer)[:300]}'
                self.event(key, 'uncertain_create_outcome')
                self.report['problems'].append(f'{key}: unclear answer ({code}), left for review')

    def run(self):
        self.report = {'scheduled': [], 'posted': [], 'cleaned': [], 'skipped_missed': [], 'problems': []}
        if not self.plan.get('enabled'):
            return {'enabled': False}
        accounts = self.ledger.data.get('accounts') or {}
        if set(accounts) != {'motivtated', 'imanivated'}:
            accounts = self.discover()
            self.ledger.save()
        self.report['accounts'] = accounts
        self.reconcile()
        self.cleanup()
        self.fill(accounts)
        return self.report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--plan', type=Path, default=Path('lane5-schedule.json'))
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    rows = validate_plan(plan)
    if args.dry_run:
        print(json.dumps({'validation': 'passed', 'rows': len(rows)}))
        return
    if not os.environ.get('ZERNIO_API_KEY'):
        print(json.dumps({'waiting': 'ZERNIO_API_KEY secret is not set yet; nothing done.'}))
        return
    gh = GitHub(env('GITHUB_REPOSITORY'), env('GITHUB_TOKEN'))
    ledger = Lane5Ledger(gh)
    ledger.initialize()
    buffer_ledger = Lane2Ledger(gh)
    buffer_ledger.load()
    media = Media(GitHub(env('MEDIA_GITHUB_REPOSITORY'), env('MEDIA_GITHUB_TOKEN')), env('MEDIA_PUBLIC_BASE_URL'))
    lane = Lane5(plan, ledger, Zernio(env('ZERNIO_API_KEY')), media, gh, buffer_ledger)
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
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('Lane 5 (YouTube via Zernio)\n\n```json\n'+json.dumps(report, indent=2, ensure_ascii=False)+'\n```\n')
    if status != 'ok':
        raise SystemExit(2)


if __name__ == '__main__':
    main()

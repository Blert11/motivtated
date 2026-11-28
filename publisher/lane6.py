"""Lane 6: animated story videos on TikTok, Instagram and Facebook (authorized by Blert on 2026-11-28).

One video a day per page at 18:00 Europe/Budapest, with fixed times from lane6-schedule.json.
- @motivtated posts through the FIRST Buffer account (BUFFER_API_KEY), the same channels as the main lane.
- @imanivated posts through the FOURTH Buffer account (BUFFER_API_KEY_4), the same channels as lane 4.

Each page has its own ledger (lane6-<page>-state.json on publisher-state). Packages are `MA####.zip` /
`IA####.zip` assets of the `animated-inputs` release. Media go to the public `lane6-media` release in the
media repo and are deleted 2 h after posting.

The other lanes share these Buffer channels, so before every create the live Buffer queue of that channel is
counted (Buffer free holds 10 per channel); a full queue only defers the post to the next run. Posts are created
at most HORIZON ahead so this lane never hogs the queue. Same safety rules as lanes 2-4: a create is never
retried after an unclear answer, every transition is saved before the next call, one failing post never stops
the others, a missed time is skipped (never posted late).
"""
import argparse
import json
import os
import re
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import lane2, lane4
from .lane3 import pick_cover_ms
from .buffer import Buffer
from .bundles import MAX_VIDEO, probe
from .common import Stop, env, now, require, sha256
from .github import GitHub, GitHubLedger

TZ = lane2.TZ
PLATFORMS = lane4.PLATFORMS
RELEASE = 'animated-inputs'
ID_RE = {'motivtated': r'MA\d{4}', 'imanivated': r'IA\d{4}'}
TAGS = {'motivtated': '#motivtated', 'imanivated': '#imanivated'}
KEYS = {'motivtated': 'BUFFER_API_KEY', 'imanivated': 'BUFFER_API_KEY_4'}
SLOTS = [(18, 0)]
BUFFER_CAP = 10              # Buffer free: at most 10 waiting posts per channel, across all lanes
HORIZON = timedelta(hours=36)
MAX_SECONDS = 600            # TikTok via Buffer takes up to 10 min; Facebook over 90 s goes up as a normal video


def ledger_for(page):
    return type('Lane6Ledger', (GitHubLedger,), {'PATH': f'lane6-{page}-state.json'})


class Media(lane2.Media):
    TAG = 'lane6-media'

    def release(self):
        if not self._release:
            rel = self.gh.request('GET', f'/releases/tags/{self.TAG}', missing_ok=True)
            if not rel:
                rel = self.gh.request('POST', '/releases', {'tag_name': self.TAG, 'target_commitish': self.branch,
                                      'name': 'Lane 6 media (temporary)', 'body': 'Animated stories waiting to post; removed after posting.',
                                      'draft': False, 'prerelease': True})
            self._release = rel
        return self._release


def unpack_story(bundle, expected_hash, directory, page, max_seconds=MAX_SECONDS):
    """Same checks as lane2.unpack_iman, with the page's hashtag and a longer limit for story videos."""
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
    require(caption == manifest['caption'] and re.findall(r'#\w+', caption) == [TAGS[page]], 'Bad caption hashtag.')
    probe(directory/'video.mp4', max_seconds=max_seconds)
    return manifest


def validate_plan(plan):
    require(plan.get('version') == 1 and plan.get('enabled') in (True, False), 'Unsupported lane-6 plan.')
    seen, last, per_day = set(), {}, {}
    for row in plan['rows']:
        page = row['page']
        require(page in ID_RE and re.fullmatch(ID_RE[page], row['clip_id']), 'Bad page/clip ID.')
        require(row['key'] == page+':'+row['clip_id'] and row['key'] not in seen, 'Duplicate or bad row key.')
        seen.add(row['key'])
        require(re.fullmatch(r'[0-9a-f]{64}', row['bundle_sha256']), 'Bad bundle digest.')
        require(row['asset_name'] == row['clip_id']+'.zip', 'Bad asset name.')
        require(row['platforms'] and set(row['platforms']) <= set(PLATFORMS), 'Bad platforms.')
        due = lane2.parse_time(row['due_at']).astimezone(TZ)
        require((due.hour, due.minute) in SLOTS and due.second == 0, 'Unexpected slot.')
        require(page not in last or due > last[page], 'Times must increase per page.')
        last[page] = due
        per_day[(page, due.date())] = per_day.get((page, due.date()), 0)+1
        require(per_day[(page, due.date())] <= len(SLOTS), 'Too many posts in one day for this page.')
    return plan['rows']


def discover_channels(buffer, ledger, page):
    orgs = buffer.organizations()
    require(len(orgs) == 1, f'Expected one Buffer organization for {page}, found {len(orgs)}.')
    chans = [c for c in buffer.channels(orgs[0]['id']) if not c['isDisconnected'] and not c['isLocked']]
    found = {}
    for p in PLATFORMS:
        match = [c for c in chans if c['service'] == p]
        if len(match) == 1:
            found[page+':'+p] = match[0]['id']
    ledger.data['organization_id'] = orgs[0]['id']
    ledger.data['channels'] = found
    return found


class Lane6(lane4.Lane4):
    def __init__(self, plan, page, ledger, buffer, media, gh, clock=None):
        self.page = page
        self.plan, self.rows = plan, [r for r in validate_plan(plan) if r['page'] == page]
        self.ledger, self.buffer, self.media, self.gh = ledger, buffer, media, gh
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_new = 4
        self.live = None
        self.report = {'scheduled': [], 'posted': [], 'cleaned': [], 'skipped_missed': [], 'problems': []}

    def load(self, row, directory):
        bundle = directory/'input.zip'
        lane2.download_asset(self.gh, RELEASE, row['asset_name'], bundle, row['bundle_sha256'])
        content = directory/'content'
        content.mkdir()
        manifest = unpack_story(bundle, row['bundle_sha256'], content, row['page'])
        require(manifest['clip_id'] == row['clip_id'], 'Package clip ID differs from the plan.')
        return manifest, content

    def live_counts(self, channels):
        """Waiting posts per channel in Buffer itself (every lane's posts, not only ours)."""
        posts = self.buffer.pending(self.ledger.data['organization_id'], list(channels.values()))
        return {cid: sum(1 for p in posts if p['channelId'] == cid) for cid in channels.values()}

    def fill(self, channels):
        live = self.live_counts(channels)
        new = 0
        for row in self.rows:
            if new >= self.max_new:
                break
            due = lane2.parse_time(row['due_at'])
            todo = []
            for p in row['platforms']:
                if p in self.plan.get('stopped_platforms', {}).get(self.page, []):
                    continue
                ch = channels.get(self.page+':'+p)
                if not ch:
                    continue
                key = row['key']+':'+p
                old = self.records.get(key)
                if old and not (old['state'] == 'failed_before_submit' and old.get('attempts', 1) < 3):
                    continue
                if due <= self.clock()+timedelta(minutes=15):
                    self.records[key] = {'row': row['key'], 'platform': p, 'channel_id': ch, 'state': 'skipped_missed',
                                         'due_at': row['due_at']}
                    self.report['skipped_missed'].append(key)
                    continue
                if due > self.clock()+HORIZON or live[ch] >= BUFFER_CAP:
                    continue      # not yet, or that Buffer queue is full: next run
                todo.append((p, ch, key))
            if not todo:
                continue
            try:
                self.fill_row(row, todo, live)
            except Exception as exc:
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
        with tempfile.TemporaryDirectory(prefix='lane6-') as scratch:
            manifest, content = self.load(row, Path(scratch))
            vid = manifest['files']['video.mp4']
            media = next((r['media'] for r in self.records.values() if r['row'] == row['key'] and r.get('media')
                          and not r.get('media_deleted_at')), None)
            if not media:
                media = self.media.ensure(content/'video.mp4', row['clip_id'], vid['sha256'])
                lane2.verify_wait(media, manifest, content)
            caption = manifest['caption']
            cover = pick_cover_ms(content/'video.mp4')
            seconds = probe(content/'video.mp4', max_seconds=MAX_SECONDS)['duration_seconds']
            for p, ch, key in todo:
                rec = {'row': row['key'], 'clip_id': row['clip_id'], 'page': row['page'], 'platform': p,
                       'channel_id': ch, 'due_at': row['due_at'], 'caption': caption, 'cover_ms': cover,
                       'media': media, 'state': 'submit_intent', 'created_at': now()}
                self.records[key] = rec
                self.event(key, 'before_buffer_createPost')
                try:
                    post = lane2.create_post(self.buffer, lane4.build_payload(p, ch, caption, media['url'], row['due_at'], cover, seconds))
                except lane2.SchemaRejected as exc:
                    rec['state'], rec['error'] = 'failed_before_submit', str(exc)[:600]
                    rec['attempts'] = rec.get('attempts', 0) + 1
                    self.event(key, 'buffer_rejected_before_execution')
                    self.report['problems'].append(f'{key}: {str(exc)[:200]}')
                    continue
                except Stop as exc:
                    rec['state'], rec['error'] = 'needs_attention', str(exc)[:600]
                    self.event(key, 'uncertain_create_outcome')
                    self.report['problems'].append(f'{key}: uncertain create, left for review')
                    continue
                rec['buffer_post_id'], rec['buffer_status'] = post['id'], post['status']
                rec['state'] = 'submitted' if post['status'] in ('scheduled', 'sending') else 'needs_attention'
                self.event(key, 'buffer_post_id_received')
                counts[ch] += 1
                self.report['scheduled'].append({'key': key, 'due_at': row['due_at'], 'post_id': post['id']})

    def run(self):
        self.report = {'scheduled': [], 'posted': [], 'cleaned': [], 'skipped_missed': [], 'problems': []}
        if not self.plan.get('enabled'):
            return {'enabled': False}
        channels = self.ledger.data.get('channels') or {}
        if set(channels) != {self.page+':'+p for p in PLATFORMS} or not self.ledger.data.get('organization_id'):
            channels = discover_channels(self.buffer, self.ledger, self.page)
            self.ledger.save()
        self.report['channels'] = channels
        missing = [p for p in PLATFORMS if self.page+':'+p not in channels]
        if missing:
            self.report['problems'].append(f'{self.page}: not connected (or more than one): '+', '.join(missing))
        self.reconcile()
        self.cleanup()
        self.fill(channels)
        return self.report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--plan', type=Path, default=Path('lane6-schedule.json'))
    ap.add_argument('--page', choices=sorted(ID_RE), required=False)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    rows = validate_plan(plan)
    if args.dry_run:
        print(json.dumps({'validation': 'passed', 'rows': len(rows)}))
        return
    require(args.page, '--page is required.')
    if not os.environ.get(KEYS[args.page]):
        print(f'{KEYS[args.page]} is not set; nothing to do.')
        return
    gh = GitHub(env('GITHUB_REPOSITORY'), env('GITHUB_TOKEN'))
    ledger = ledger_for(args.page)(gh)
    ledger.initialize()
    media = Media(GitHub(env('MEDIA_GITHUB_REPOSITORY'), env('MEDIA_GITHUB_TOKEN')), env('MEDIA_PUBLIC_BASE_URL'))
    lane = Lane6(plan, args.page, ledger, Buffer(token=env(KEYS[args.page])), media, gh)
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
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(f'Lane 6 ({args.page} animated stories)\n\n```json\n'+json.dumps(report, indent=2, ensure_ascii=False)+'\n```\n')
    if status != 'ok':
        raise SystemExit(2)


if __name__ == '__main__':
    main()

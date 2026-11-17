"""Lane 4: @imanivated TikTok, Instagram (Reels) and Facebook (Reels) through the FOURTH Buffer account.

Authorized by Blert on 2026-11-18: post the same Imanivated clips as the YouTube lane (lane 2), at the same
times, starting after the last clip he had already posted by hand (I000045), so nothing repeats.

Own key (BUFFER_API_KEY_4), plan (lane4-schedule.json), ledger (lane4-state.json on publisher-state) and
media release (lane4-media). Same safety rules as lanes 2 and 3: a Buffer create is never retried
automatically, every transition is saved before the next call, one failing post never stops the others.
"""
import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import lane2
from .lane3 import pick_cover_ms
from .buffer import Buffer
from .common import Stop, env, now, require
from .github import GitHub, GitHubLedger

TZ = lane2.TZ
SLOTS = lane2.SLOTS['imanivated']
PLATFORMS = ('tiktok', 'instagram', 'facebook')


class Lane4Ledger(GitHubLedger):
    PATH = 'lane4-state.json'


class Media(lane2.Media):
    TAG = 'lane4-media'

    def release(self):
        if not self._release:
            rel = self.gh.request('GET', f'/releases/tags/{self.TAG}', missing_ok=True)
            if not rel:
                rel = self.gh.request('POST', '/releases', {'tag_name': self.TAG, 'target_commitish': self.branch,
                                      'name': 'Lane 4 media (temporary)', 'body': 'Imanivated clips waiting to post; removed after posting.',
                                      'draft': False, 'prerelease': True})
            self._release = rel
        return self._release


def validate_plan(plan):
    require(plan.get('version') == 1 and plan.get('enabled') in (True, False), 'Unsupported lane-4 plan.')
    require(plan.get('max_pending_per_channel', 10) <= 10, 'Buffer free holds at most 10 per channel.')
    seen, last, per_day = set(), None, {}
    for row in plan['rows']:
        require(row['page'] == 'imanivated' and re.fullmatch(lane2.ID_RE['imanivated'], row['clip_id']), 'Bad page/clip ID.')
        require(row['key'] == 'imanivated:'+row['clip_id'] and row['key'] not in seen, 'Duplicate or bad row key.')
        seen.add(row['key'])
        require(re.fullmatch(r'[0-9a-f]{64}', row['bundle_sha256']), 'Bad bundle digest.')
        require(re.fullmatch(re.escape(row['clip_id'])+r'(\.r[0-9]{1,2})?\.zip', row['asset_name']), 'Bad asset name.')
        require(row['platforms'] and set(row['platforms']) <= set(PLATFORMS), 'Bad platforms.')
        due = lane2.parse_time(row['due_at']).astimezone(TZ)
        require((due.hour, due.minute) in SLOTS and due.second == 0, 'Unexpected slot.')
        require(last is None or due > last, 'Times must increase.')
        last = due
        per_day[due.date()] = per_day.get(due.date(), 0)+1
        require(per_day[due.date()] <= len(SLOTS), 'Too many posts in one day.')
    return plan['rows']


def build_payload(platform, channel_id, caption, url, due_at, cover_ms, seconds=0):
    require(platform in PLATFORMS, 'Unsupported lane-4 platform.')
    data = {'text': caption, 'channelId': channel_id, 'schedulingType': 'automatic',
            'mode': 'customScheduled', 'dueAt': due_at, 'saveToDraft': False,
            'assets': [{'video': {'url': url, 'metadata': {'thumbnailOffset': cover_ms}}}]}
    if platform == 'instagram':
        data['metadata'] = {'instagram': {'type': 'reel', 'shouldShareToFeed': True}}
    if platform == 'facebook':
        # Facebook Reels are limited to 90 s; the longer dhikr videos go up as a normal video post.
        data['metadata'] = {'facebook': {'type': 'reel' if seconds <= 90 else 'post'}}
    return data


def discover_channels(buffer, ledger):
    orgs = buffer.organizations()
    require(len(orgs) == 1, f'Expected one organization on the fourth Buffer account, found {len(orgs)}.')
    chans = [c for c in buffer.channels(orgs[0]['id']) if not c['isDisconnected'] and not c['isLocked']]
    ledger.data['channels_seen'] = [{'id': c['id'], 'name': c.get('name'), 'service': c['service']} for c in chans]
    found = {}
    for p in PLATFORMS:
        match = [c for c in chans if c['service'] == p]
        if len(match) == 1:
            found['imanivated:'+p] = match[0]['id']
    ledger.data['organization_id'] = orgs[0]['id']
    ledger.data['channels'] = found
    return found


class Lane4(lane2.Lane2):
    def __init__(self, plan, ledger, buffer, media, gh, clock=None):
        self.plan, self.rows = plan, validate_plan(plan)
        self.ledger, self.buffer, self.media, self.gh = ledger, buffer, media, gh
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_new = 12   # scheduled workflows can be hours apart: fill the queue well ahead
        self.report = {'scheduled': [], 'posted': [], 'cleaned': [], 'skipped_missed': [], 'problems': []}

    def fill_row(self, row, todo, counts):
        with tempfile.TemporaryDirectory(prefix='lane4-') as scratch:
            manifest, content = self.load(row, Path(scratch))
            vid = manifest['files']['video.mp4']
            media = next((r['media'] for r in self.records.values() if r['row'] == row['key'] and r.get('media')
                          and not r.get('media_deleted_at')), None)
            if not media:
                media = self.media.ensure(content/'video.mp4', row['clip_id'], vid['sha256'])
                lane2.verify_wait(media, manifest, content)
            caption = manifest['caption']
            cover = pick_cover_ms(content/'video.mp4')
            seconds = lane2.probe(content/'video.mp4', max_seconds=175)['duration_seconds']
            for p, ch, key in todo:
                rec = {'row': row['key'], 'clip_id': row['clip_id'], 'page': row['page'], 'platform': p,
                       'channel_id': ch, 'due_at': row['due_at'], 'caption': caption, 'cover_ms': cover,
                       'media': media, 'state': 'submit_intent', 'created_at': now()}
                self.records[key] = rec
                self.event(key, 'before_buffer_createPost')
                try:
                    post = lane2.create_post(self.buffer, build_payload(p, ch, caption, media['url'], row['due_at'], cover, seconds))
                except lane2.SchemaRejected as exc:
                    rec['state'], rec['error'] = 'failed_before_submit', str(exc)[:600]
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
        if set(channels) != {'imanivated:'+p for p in PLATFORMS}:
            channels = discover_channels(self.buffer, self.ledger)
            self.ledger.save()
        self.report['channels'] = channels
        missing = [p for p in PLATFORMS if 'imanivated:'+p not in channels]
        if missing:
            self.report['problems'].append('Not connected (or more than one) on the fourth Buffer account: '+', '.join(missing))
        self.reconcile()
        self.cleanup()
        self.fill(channels)
        return self.report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--plan', type=Path, default=Path('lane4-schedule.json'))
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    rows = validate_plan(plan)
    if args.dry_run:
        print(json.dumps({'validation': 'passed', 'rows': len(rows)}))
        return
    if not os.environ.get('BUFFER_API_KEY_4'):
        print('BUFFER_API_KEY_4 is not set yet; nothing to do.')
        return
    gh = GitHub(env('GITHUB_REPOSITORY'), env('GITHUB_TOKEN'))
    ledger = Lane4Ledger(gh)
    ledger.initialize()
    media = Media(GitHub(env('MEDIA_GITHUB_REPOSITORY'), env('MEDIA_GITHUB_TOKEN')), env('MEDIA_PUBLIC_BASE_URL'))
    lane = Lane4(plan, ledger, Buffer(token=env('BUFFER_API_KEY_4')), media, gh)
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
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('Lane 4 (Imanivated TikTok/Instagram/Facebook)\n\n```json\n'+json.dumps(report, indent=2, ensure_ascii=False)+'\n```\n')
    if status != 'ok':
        raise SystemExit(2)


if __name__ == '__main__':
    main()

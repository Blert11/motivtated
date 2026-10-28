"""Fill a bounded Buffer queue from the user's explicit, dated clip plan."""
import argparse
import json
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .buffer import Buffer
from .bundles import download_github_release, unpack
from .common import Stop, env, require
from .engine import Engine
from .github import GitHubLedger
from .media import host_from_env, verify_public

PLATFORMS = ('tiktok', 'instagram')


def parse_time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None, 'Schedule timestamps require a timezone.')
    return result


def validate_plan(plan):
    require(plan.get('version') == 1 and plan.get('timezone') == 'Europe/Budapest', 'Unsupported schedule plan.')
    require(plan.get('max_pending_per_channel') in [6,10], 'Queue capacity must be six or ten per channel.')
    daily = plan.get('posts_per_day', 5)
    require(daily in [5,10], 'Unsupported daily posting count.')
    slots = [(9,0),(12,0),(15,0),(18,0),(21,0)] if daily == 5 else [
        (9+90*n//60,90*n%60) for n in range(10)]
    rows = plan['clips']
    require([r['clip_id'] for r in rows] == [f'M{n:06d}' for n in range(10,32)],
            'This approved queue must contain Tate videos 10-31 in order, exactly once.')
    previous = None
    days = {}
    for row in rows:
        require(re.fullmatch('[0-9a-f]{64}', row['bundle_sha256']), 'Invalid package digest.')
        due = parse_time(row['due_at'])
        require(previous is None or due > previous, 'Clip times must strictly increase.')
        local = due.astimezone(ZoneInfo(plan['timezone']))
        require((local.hour,local.minute) in slots and local.second == local.microsecond == 0, 'Unexpected posting slot.')
        days[local.date()] = days.get(local.date(), 0)+1
        require(days[local.date()] <= daily, 'The plan exceeds its approved posts per local day.')
        previous = due
    return rows


def wait_for_public(media, manifest, directory):
    # Retry only the read-only availability check, never a Buffer create mutation.
    for attempt in range(13):
        try:
            return verify_public(media, manifest, directory)
        except Stop as exc:
            if attempt == 12 or not str(exc).startswith('Download failed;'):
                raise
            time.sleep(15)


def load_package(row, directory):
    bundle = directory/'input.zip'
    download_github_release(row['clip_id'], bundle, row['bundle_sha256'])
    content = directory/'content'
    content.mkdir()
    manifest = unpack(bundle, row['bundle_sha256'], content)
    require(manifest['clip_id'] == row['clip_id'], 'Scheduled clip ID differs from package.')
    return manifest, content


class Scheduler:
    def __init__(self, plan, engine, channels, loader=load_package, clock=None):
        self.plan = plan
        self.rows = validate_plan(plan)
        self.engine = engine
        self.channels = channels
        self.loader = loader
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.report = {'scheduled': [], 'reconciled': [], 'cleaned': [], 'errors': []}

    @property
    def records(self):
        return self.engine.ledger.data['records']

    def reconcile_due(self):
        for row in self.rows:
            for platform in PLATFORMS:
                record = self.records.get(row['clip_id']+':'+platform)
                if not record or record['state'] == 'posted':
                    continue
                require(record['state'] not in ['submit_intent','failed_at_buffer','needs_attention'],
                        f"{row['clip_id']} {platform} needs investigation; no automatic resubmission.")
                if record.get('buffer_post_id') and parse_time(row['due_at']) <= self.clock():
                    refreshed = self.engine.reconcile(row['clip_id'], platform)
                    require(refreshed['state'] in ['submitted','posted'], 'Buffer post failed; inspect its existing ID.')
                    self.report['reconciled'].append(row['clip_id']+':'+platform)

    def apply_schedule_changes(self):
        for row in self.rows:
            for platform in PLATFORMS:
                record = self.records.get(row['clip_id']+':'+platform)
                if not record or record.get('scheduled_at') == row['due_at']:
                    continue
                require(row.get('previous_due_at') == record.get('scheduled_at'),
                        'Changing an existing schedule requires its explicit previous time.')
                self.engine.reschedule(row['clip_id'], platform, row['previous_due_at'], row['due_at'])

    def cleanup(self):
        if not self.plan.get('cleanup_after_both_sent'):
            return
        # Only the approved queue; originals and private bundles are always retained.
        for row in self.rows:
            records = [self.records.get(row['clip_id']+':'+p) for p in PLATFORMS]
            if not all(r and r['state'] == 'posted' and r.get('post_url') and r.get('sent_at') for r in records):
                continue
            if all(r.get('media_deleted_at') for r in records):
                continue
            if any(self.clock()-parse_time(r['sent_at']) < timedelta(hours=48) for r in records):
                continue
            for platform in PLATFORMS:
                self.engine.reconcile(row['clip_id'], platform)
            self.engine.cleanup(row['clip_id'], provider_confirmed=True)
            self.report['cleaned'].append(row['clip_id'])
            if len(self.report['cleaned']) >= 2:
                break

    def candidates(self):
        pending = {p:sum(r['platform'] == p and r['state'] != 'posted'
                         for r in self.records.values()) for p in PLATFORMS}
        result = []
        for row in self.rows:
            missing = []
            for platform in PLATFORMS:
                record = self.records.get(row['clip_id']+':'+platform)
                if record and record['state'] not in ['preparing','failed_before_submit']:
                    continue
                # Pre-submit reservations already occupy one local queue slot.
                if not record and pending[platform] >= self.plan['max_pending_per_channel']:
                    continue
                require(parse_time(row['due_at']) > self.clock()+timedelta(minutes=5),
                        f"Missed scheduling window for {row['clip_id']}; stop rather than publish a backlog in a burst.")
                missing.append(platform)
                if not record:
                    pending[platform] += 1
            if missing:
                result.append((row, missing))
        return result[:6]

    def pending_counts(self):
        self.engine.event(None, 'before_buffer_scheduler_organizations')
        organizations = self.engine.buffer.organizations()
        require(len(organizations) == 1, 'Choose the publishing organization explicitly if more than one is connected.')
        self.engine.event(None, 'before_buffer_scheduler_pending_query')
        posts = self.engine.buffer.pending(organizations[0]['id'], list(self.channels.values()))
        return {platform:sum(p['channelId'] == channel for p in posts)
                for platform, channel in self.channels.items()}

    def run(self):
        self.report = {'scheduled': [], 'reconciled': [], 'cleaned': [], 'errors': []}
        if not self.plan.get('enabled'):
            return {'enabled': False}
        self.apply_schedule_changes()
        self.reconcile_due()
        self.cleanup()
        candidates = self.candidates()
        if candidates:
            counts = self.pending_counts()
            for row, platforms in candidates:
                require(all(counts[p] < self.plan['max_pending_per_channel'] for p in platforms),
                        'Buffer has reached the configured pending limit; wait for capacity or inspect external posts.')
                with tempfile.TemporaryDirectory(prefix='motivtated-scheduler-') as scratch:
                    manifest, content = self.loader(row, Path(scratch))
                    for platform in platforms:
                        record = self.records.get(row['clip_id']+':'+platform)
                        posted = self.engine.publish(manifest, content, platform, self.channels[platform],
                            resume=bool(record), confirmed_unposted=True, due_at=row['due_at'])
                        require(posted['state'] == 'submitted' and posted['buffer_status'] == 'scheduled',
                                'Expected a scheduled Buffer post; inspect the saved post ID.')
                        self.report['scheduled'].append({'clip_id':row['clip_id'], 'platform':platform,
                            'due_at':row['due_at'], 'buffer_post_id':posted['buffer_post_id']})
                        counts[platform] += 1
        self.report['complete'] = all(self.records.get(row['clip_id']+':'+p, {}).get('state') == 'posted'
                                      for row in self.rows for p in PLATFORMS)
        self.report['finished'] = self.report['complete'] and all(
            self.records[row['clip_id']+':'+p].get('media_deleted_at') for row in self.rows for p in PLATFORMS)
        return self.report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=Path('posting-schedule.json'))
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    rows = validate_plan(plan)
    if args.dry_run:
        print(json.dumps({'validation':'passed', 'clips':len(rows), 'first':rows[0]['due_at'], 'last':rows[-1]['due_at']}))
        return
    ledger = GitHubLedger.from_env()
    ledger.load()
    engine = Engine(ledger, Buffer(), host_from_env(), verify=wait_for_public)
    scheduler = Scheduler(plan, engine, {p:env('BUFFER_'+p.upper()+'_CHANNEL_ID') for p in PLATFORMS})
    try:
        report = scheduler.run()
    except Exception as exc:
        # Deliberate Stop messages are sanitized. Never log arbitrary SDK exceptions.
        report = {**scheduler.report, 'error':str(exc) if isinstance(exc, Stop) else type(exc).__name__}
        print(json.dumps(report))
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('Publisher stopped. Inspect the existing ledger before retrying.\n\n'+json.dumps(report,indent=2))
        raise SystemExit(2) from None
    print(json.dumps(report))
    if report.get('finished'):
        engine.event(None, 'queue_finished_disabling_scheduler')
        ledger.gh.request('PUT', '/actions/workflows/scheduled-publisher.yml/disable')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('MOTIVTATED queue refill\n\n```json\n'+json.dumps(report,indent=2)+'\n```\n')


if __name__ == '__main__':
    main()

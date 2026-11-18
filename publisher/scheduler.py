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
OPTIONAL = ('facebook',)   # added 2026-11-06; isolated: a Facebook problem pauses only Facebook


def parse_time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None, 'Schedule timestamps require a timezone.')
    return result


SLOTS = {5: [(9,0),(12,0),(15,0),(18,0),(21,0)],
         7: [(9,0),(11,0),(13,30),(16,0),(18,30),(20,30),(22,30)],
         10: [(9+90*n//60,90*n%60) for n in range(10)]}


def pace_for(plan, day):
    """Posts per day for a local date: the plan default, changed from a date onward by explicit pace entries."""
    daily = plan.get('posts_per_day', 5)
    for change in sorted(plan.get('pace_changes', []), key=lambda c: c['from']):
        if day >= datetime.fromisoformat(change['from']).date():
            daily = change['posts_per_day']
    require(daily in SLOTS, 'Unsupported daily posting count.')
    return daily


def validate_plan(plan):
    require(plan.get('version') == 1 and plan.get('timezone') == 'Europe/Budapest', 'Unsupported schedule plan.')
    require(plan.get('max_pending_per_channel') in [6,10], 'Queue capacity must be six or ten per channel.')
    require(plan.get('cleanup_grace_hours',48) in [2,48], 'Unsupported cleanup retention period.')
    pace_for(plan, datetime(2000, 1, 1).date())
    for change in plan.get('pace_changes', []):
        require(re.fullmatch(r'\d{4}-\d{2}-\d{2}', change.get('from', '')) and change.get('posts_per_day') in SLOTS,
                'Invalid pace change.')
    rows = plan['clips']
    original = [f'M{n:06d}' for n in range(10,32)]
    extended = original + [f'M{n:06d}' for n in range(66,108)]
    ids = [r['clip_id'] for r in rows]
    require(ids == original or ids[:len(extended)] == extended,
            'Approved order: Tate videos 10-31, then batch 5 IDs M000066-M000107, then any further approved IDs.')
    more = ids[len(extended):] if len(ids) > len(original) else []
    require(len(set(ids)) == len(ids) and all(re.fullmatch(r'M\d{6}', i) for i in more)
            and not set(more) & set(plan.get('excluded_ids', [])),
            'Additional clips must be unique, valid IDs that are not excluded.')
    require(not more or plan.get('additional_authorized_on'), 'Additional clips need an explicit authorization date.')
    previous = None
    days = {}
    for row in rows:
        require(re.fullmatch('[0-9a-f]{64}', row['bundle_sha256']), 'Invalid package digest.')
        due = parse_time(row['due_at'])
        require(previous is None or due > previous, 'Clip times must strictly increase.')
        local = due.astimezone(ZoneInfo(plan['timezone']))
        daily = pace_for(plan, local.date())
        if row.get('extra_post'):   # one-off "post it now" clip Blert asked for: any minute, outside the daily count
            require(local.second == local.microsecond == 0 and row.get('extra_note'), 'Extra posts need a whole-minute time and a note.')
        else:
            require((local.hour,local.minute) in SLOTS[daily] and local.second == local.microsecond == 0, 'Unexpected posting slot.')
            days[local.date()] = days.get(local.date(), 0)+1
            require(days[local.date()] <= daily, 'The plan exceeds its approved posts per local day.')
        previous = due
    return rows


def wait_for_public(media, manifest, directory):
    # Retry only the read-only availability check, never a Buffer create mutation.
    # Pages deploys can queue for several minutes, so allow about 12 minutes.
    for attempt in range(49):
        try:
            return verify_public(media, manifest, directory)
        except Stop as exc:
            if attempt == 48 or not str(exc).startswith('Download failed;'):
                raise
            time.sleep(15)


def load_package(row, directory):
    bundle = directory/'input.zip'
    download_github_release(row['clip_id'], bundle, row['bundle_sha256'], asset_name=row.get('asset_name'))
    content = directory/'content'
    content.mkdir()
    manifest = unpack(bundle, row['bundle_sha256'], content)
    require(manifest['clip_id'] == row['clip_id'], 'Scheduled clip ID differs from package.')
    return manifest, content


class Scheduler:
    def __init__(self, plan, engine, channels, loader=load_package, clock=None, retry_edit=None):
        self.plan = plan
        self.rows = validate_plan(plan)
        self.engine = engine
        self.channels = channels
        self.loader = loader
        self.retry_edit = retry_edit
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.report = {'scheduled': [], 'reconciled': [], 'cleaned': [], 'errors': []}

    @property
    def records(self):
        return self.engine.ledger.data['records']

    def fb_paused(self):
        return False   # 2026-11-14: a Facebook failure skips only that post; the channel keeps posting

    def platforms_for(self, row, include_paused=False):
        result = list(PLATFORMS)
        start = self.plan.get('facebook_from')
        if 'facebook' in self.channels and start and parse_time(row['due_at']) >= parse_time(start):
            if include_paused or not self.fb_paused():
                result.append('facebook')
        return result

    def pause_facebook(self, row, exc):
        self.engine.ledger.data['facebook_paused'] = {'at': datetime.now(timezone.utc).isoformat(), 'clip_id': row['clip_id'],
                                                      'error': str(exc)[:600] if isinstance(exc, Stop) else type(exc).__name__}
        self.engine.event(row['clip_id']+':facebook', 'facebook_paused_after_failure')
        self.report['facebook_paused'] = self.engine.ledger.data['facebook_paused']

    MAX_ATTEMPTS = 3

    def auto_skip(self, row, platform, record=None, reason='buffer_reported_error'):
        """Owner rule (2026-11-14): one failing post never stops the queue -- not on other platforms and not on
        the same platform. The failing post is recorded as skipped (never resubmitted) and everything else goes on."""
        key = row['clip_id']+':'+platform
        if record is None:
            record = self.records.setdefault(key, {'clip_id': row['clip_id'], 'platform': platform,
                                                   'channel_id': self.channels.get(platform), 'created_at': datetime.now(timezone.utc).isoformat()})
        record['state'] = 'skipped'
        record['skip_reason'] = reason
        record['skipped_at'] = datetime.now(timezone.utc).isoformat()
        record.setdefault('scheduled_at', row['due_at'])
        self.engine.event(key, 'auto_skipped_'+reason)
        self.engine.ledger.save()
        self.report.setdefault('auto_skipped', []).append(f'{key} ({reason})')

    def note_error(self, where, exc):
        msg = str(exc)[:300] if isinstance(exc, Stop) else type(exc).__name__+': '+str(exc)[:200]
        self.report['errors'].append(f'{where}: {msg}')

    def reconcile_due(self):
        for row in self.rows:
            for platform in self.platforms_for(row, include_paused=True):
                record = self.records.get(row['clip_id']+':'+platform)
                if not record or record['state'] in ('posted', 'skipped'):
                    continue   # 'skipped' = owner-approved permanent skip of a rejected post
                if platform == 'facebook' and record['state'] in ['submit_intent','failed_at_buffer','needs_attention','failed_before_submit']:
                    self.report.setdefault('facebook_attention', []).append(row['clip_id'])
                    continue
                if record['state'] == 'failed_at_buffer':
                    # Buffer accepted the post but the network rejected it (nothing was published). Never resubmitted.
                    self.auto_skip(row, platform, record)
                    continue
                if record['state'] in ['submit_intent','needs_attention']:
                    # Outcome unknown or not scheduled: never resubmit (no duplicates), but don't hold the queue either.
                    self.auto_skip(row, platform, record, 'uncertain_'+record['state'])
                    continue
                if record.get('buffer_post_id') and parse_time(row['due_at']) <= self.clock():
                    if platform == 'facebook':
                        try:
                            refreshed = self.engine.reconcile(row['clip_id'], platform)
                        except Stop:
                            self.report.setdefault('facebook_attention', []).append(row['clip_id']); continue
                        if refreshed['state'] not in ['submitted','posted']:
                            self.report.setdefault('facebook_attention', []).append(row['clip_id']); continue
                    else:
                        try:
                            refreshed = self.engine.reconcile(row['clip_id'], platform)
                        except Exception as exc:          # lookup trouble: try again next run
                            self.note_error(row['clip_id']+':'+platform+' reconcile', exc); continue
                        if refreshed['state'] == 'failed_at_buffer':
                            self.auto_skip(row, platform, refreshed)
                            continue
                        if refreshed['state'] not in ['submitted','posted']:
                            self.auto_skip(row, platform, refreshed, 'buffer_status_'+str(refreshed.get('buffer_status')))
                            continue
                    self.report['reconciled'].append(row['clip_id']+':'+platform)

    def apply_schedule_changes(self):
        for row in self.rows:
            for platform in PLATFORMS:
                record = self.records.get(row['clip_id']+':'+platform)
                if not record or record.get('scheduled_at') == row['due_at']:
                    continue
                if record.get('state') == 'skipped':
                    continue
                # Deliberate manual re-times keep their strict checks (they only run when the plan is edited by hand).
                require(row.get('previous_due_at') == record.get('scheduled_at'),
                        'Changing an existing schedule requires its explicit previous time.')
                self.engine.reschedule(row['clip_id'], platform, row['previous_due_at'], row['due_at'],
                    allow_reviewed_retry=self.retry_edit == row['clip_id']+':'+platform)

    def cleanup(self):
        if not self.plan.get('cleanup_after_both_sent'):
            return
        # Only the approved queue; originals and private bundles are always retained.
        for row in self.rows:
            plats = list(PLATFORMS)
            fb = self.records.get(row['clip_id']+':facebook')
            if fb and fb['state'] in ('submitted', 'posted', 'preparing') and fb.get('media'):
                plats.append('facebook')   # keep the hosted video until Facebook has it too
            records = [self.records.get(row['clip_id']+':'+p) for p in plats]
            if not all(r and r['state'] == 'posted' and r.get('post_url') and r.get('sent_at') for r in records):
                continue
            if all(r.get('media_deleted_at') for r in records):
                continue
            grace = self.plan.get('cleanup_grace_hours',48)
            if any(self.clock()-parse_time(r['sent_at']) < timedelta(hours=grace) for r in records):
                continue
            try:
                for platform in plats:
                    self.engine.reconcile(row['clip_id'], platform)
                self.engine.cleanup(row['clip_id'], provider_confirmed=True,grace_hours=grace, platforms=tuple(plats))
            except Exception as exc:
                self.note_error(row['clip_id']+' cleanup', exc); continue
            self.report['cleaned'].append(row['clip_id'])
            if len(self.report['cleaned']) >= 4:
                break

    def candidates(self):
        pending = {p:sum(r['platform'] == p and r['state'] not in ('posted', 'skipped') and not (p == 'facebook' and r['state'] == 'failed_before_submit')
                         for r in self.records.values()) for p in list(PLATFORMS) + list(OPTIONAL)}
        result = []
        for row in self.rows:
            missing = []
            for platform in self.platforms_for(row):
                record = self.records.get(row['clip_id']+':'+platform)
                if record and record['state'] not in ['preparing','failed_before_submit']:
                    continue
                if record and record.get('attempts', 1) >= self.MAX_ATTEMPTS:
                    self.auto_skip(row, platform, record, 'failed_3_attempts')
                    continue
                if platform == 'facebook' and record:
                    continue   # never auto-retry a failed Facebook attempt
                # Pre-submit reservations already occupy one local queue slot.
                if not record and pending[platform] >= self.plan['max_pending_per_channel']:
                    continue
                if parse_time(row['due_at']) <= self.clock()+timedelta(minutes=5):
                    # Never publish a backlog in a burst, and never stop the queue: record the missed slot and go on.
                    self.auto_skip(row, platform, record, 'missed_slot')
                    continue
                missing.append(platform)
                if not record:
                    pending[platform] += 1
            if missing:
                result.append((row, missing))
        return result[:6]

    def publish_one(self, row, platform, manifest, content, counts):
        key = row['clip_id']+':'+platform
        record = self.records.get(key)
        try:
            posted = self.engine.publish(manifest, content, platform, self.channels[platform],
                resume=bool(record), confirmed_unposted=True, due_at=row['due_at'])
        except Exception as exc:
            self.note_error(key, exc)
            rec = self.records.get(key)
            if rec is not None:
                if rec.get('state') == 'failed_before_submit':
                    rec['attempts'] = rec.get('attempts', 0) + 1     # retried next run, skipped after 3 tries
                    if platform == 'facebook' or rec['attempts'] >= self.MAX_ATTEMPTS:
                        self.auto_skip(row, platform, rec, 'failed_before_submit')
                elif rec.get('state') in ('submit_intent', 'needs_attention', 'preparing'):
                    self.auto_skip(row, platform, rec, 'uncertain_'+rec['state'])   # never resubmitted
            self.engine.ledger.save()
            return
        if posted['state'] != 'submitted' or posted.get('buffer_status') != 'scheduled':
            self.auto_skip(row, platform, posted, 'buffer_status_'+str(posted.get('buffer_status')))
            return
        self.report['scheduled'].append({'clip_id':row['clip_id'], 'platform':platform,
            'due_at':row['due_at'], 'buffer_post_id':posted['buffer_post_id']})
        counts[platform] = counts.get(platform, 0) + 1

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
                # A full Buffer queue only defers that platform to a later run; it never stops the others.
                platforms = [p for p in platforms if counts.get(p, 0) < self.plan['max_pending_per_channel']]
                if not platforms:
                    continue
                try:
                    with tempfile.TemporaryDirectory(prefix='motivtated-scheduler-') as scratch:
                        manifest, content = self.loader(row, Path(scratch))
                        host = self.engine.host
                        if hasattr(host,'can_fit') and not host.can_fit(row['clip_id'],
                                manifest['files']['video.mp4']['sha256'],manifest['files']['video.mp4']['size']):
                            # Leave no reservation/Buffer intent; refill next hour after safe cleanup.
                            self.report['deferred_for_storage'] = row['clip_id']
                            break
                        for platform in platforms:
                            self.publish_one(row, platform, manifest, content, counts)
                except Exception as exc:     # package/download trouble for this clip: retried next run, others go on
                    self.note_error(row['clip_id']+' package', exc)
                    for platform in platforms:
                        rec = self.records.get(row['clip_id']+':'+platform)
                        if rec and rec.get('state') in ('preparing', 'failed_before_submit'):
                            rec['state'] = 'failed_before_submit'
                    self.engine.ledger.save()
        self.report['complete'] = all(self.records.get(row['clip_id']+':'+p, {}).get('state') in ('posted', 'skipped')
                                      for row in self.rows for p in self.platforms_for(row))
        self.report['finished'] = self.report['complete'] and all(
            self.records[row['clip_id']+':'+p].get('media_deleted_at') or self.records[row['clip_id']+':'+p]['state'] == 'skipped'
            for row in self.rows for p in PLATFORMS)
        return self.report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=Path('posting-schedule.json'))
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    retry_edit = os.environ.get('REVIEWED_SCHEDULE_EDIT','').strip()
    if retry_edit:
        require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
                and re.fullmatch(r'M\d{6}:(tiktok|instagram)',retry_edit),
                'Reviewed schedule retries require a manual dispatch for one exact record.')
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    rows = validate_plan(plan)
    if args.dry_run:
        print(json.dumps({'validation':'passed', 'clips':len(rows), 'first':rows[0]['due_at'], 'last':rows[-1]['due_at']}))
        return
    ledger = GitHubLedger.from_env()
    ledger.load()
    engine = Engine(ledger, Buffer(), host_from_env(), verify=wait_for_public)
    channels = {p:env('BUFFER_'+p.upper()+'_CHANNEL_ID') for p in PLATFORMS}
    if plan.get('facebook_from'):
        fb = os.environ.get('BUFFER_FACEBOOK_CHANNEL_ID','').strip() or ledger.data.get('facebook_channel_id')
        if not fb:
            try:
                engine.event(None, 'before_buffer_facebook_channel_discovery')
                found = [c for o in engine.buffer.organizations() for c in engine.buffer.channels(o['id'])
                         if c['service'] == 'facebook' and not c['isDisconnected'] and not c['isLocked']]
                if len(found) == 1:
                    fb = found[0]['id']; ledger.data['facebook_channel_id'] = fb
                    ledger.data['facebook_channel_name'] = found[0].get('name')
                    engine.event(None, 'facebook_channel_discovered')
                else:
                    ledger.data['facebook_discovery'] = f'{len(found)} usable Facebook channels found'
                    ledger.save()
            except Stop:
                fb = None
        if fb:
            channels['facebook'] = fb
    scheduler = Scheduler(plan, engine, channels,retry_edit=retry_edit)
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

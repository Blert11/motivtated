import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_publisher as fixtures
from publisher.buffer import payload
from publisher.common import Stop
from publisher.engine import Engine
from publisher.scheduler import Scheduler, validate_plan, wait_for_public


def plan():
    slots=[]
    for day in range(1,6):
        for hour in [9,12,15,18,21]:
            slots.append(datetime(2099,1,day,hour,tzinfo=ZoneInfo('Europe/Budapest')).isoformat())
    return {'version':1,'enabled':True,'timezone':'Europe/Budapest','max_pending_per_channel':6,
        'cleanup_after_both_sent':False,
        'clips':[{'clip_id':f'M{n:06d}','bundle_sha256':'a'*64,'due_at':slots[n-10]} for n in range(10,32)]}


class ScheduledBuffer(fixtures.FakeBuffer):
    def organizations(self): return [{'id':'org'}]
    def pending(self, org, channels):
        return [p for p in self.posts.values() if p['status']=='scheduled']
    def create(self, p):
        post = super().create(p)
        del self.posts[post['id']]
        post.update(id='scheduled-'+str(len(self.calls)), status='scheduled', dueAt=p['dueAt'], sentAt=None, externalLink=None)
        self.posts[post['id']] = post
        return post


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.plan=plan();self.ledger=fixtures.MemoryLedger()
        self.buffer=ScheduledBuffer(self.ledger);self.host=fixtures.FakeHost()
        self.engine=Engine(self.ledger,self.buffer,self.host,verify=lambda *a:None)
        # The initial public integration check has been completed on both channels.
        for platform in ['tiktok','instagram']:
            self.ledger.data['records']['M000032:'+platform]={'clip_id':'M000032','platform':platform,
                'channel_id':platform,'state':'posted','public_verified_at':'2026-01-01T00:00:00+00:00',
                'video_sha256':'f'*64}
        self.now=datetime(2098,12,31,12,tzinfo=timezone.utc)
        def loader(row, directory):
            m=fixtures.manifest(row['clip_id']);m['files']['video.mp4']['sha256']=row['clip_id'].zfill(64)
            return m,directory
        self.scheduler=Scheduler(self.plan,self.engine,{'tiktok':'tiktok','instagram':'instagram'},loader,lambda:self.now)

    def run_scheduler(self):
        original=tempfile.TemporaryDirectory
        with patch('publisher.scheduler.tempfile.TemporaryDirectory',side_effect=lambda **kw:original(dir=Path(__file__).resolve().parent,**kw)):
            return self.scheduler.run()

    def test_first_refill_schedules_six_per_channel_at_explicit_times(self):
        result=self.run_scheduler()
        self.assertEqual(len(result['scheduled']),12)
        self.assertTrue(all(p['mode']=='customScheduled' for p in self.buffer.calls))
        self.assertEqual(self.buffer.calls[0]['dueAt'],self.plan['clips'][0]['due_at'])
        self.assertEqual({r['clip_id'] for r in result['scheduled']},{f'M{n:06d}' for n in range(10,16)})

    def test_repeated_run_does_not_duplicate_or_refill_full_queue(self):
        self.run_scheduler();self.run_scheduler()
        self.assertEqual(len(self.buffer.calls),12)

    def test_one_platform_failure_does_not_resubmit_success(self):
        original=self.buffer.create
        def create(p):
            if p['channelId']=='instagram': raise Stop('ambiguous submission')
            return original(p)
        self.buffer.create=create
        with self.assertRaises(Stop): self.run_scheduler()
        self.assertEqual(self.ledger.data['records']['M000010:tiktok']['state'],'submitted')
        self.assertEqual(self.ledger.data['records']['M000010:instagram']['state'],'submit_intent')
        with self.assertRaises(Stop): self.run_scheduler()
        self.assertEqual(len(self.buffer.calls),1)

    def test_refill_only_after_saved_posts_finish(self):
        self.run_scheduler()
        for platform in ['tiktok','instagram']:
            record=self.ledger.data['records']['M000010:'+platform]
            post=self.buffer.posts[record['buffer_post_id']]
            post.update(status='sent',sentAt='2099-01-01T08:00:01+00:00',externalLink=f'https://{platform}.com/post')
        self.now=datetime(2099,1,1,9,tzinfo=timezone.utc)
        result=self.run_scheduler()
        self.assertEqual([r['clip_id'] for r in result['scheduled']],['M000016','M000016'])
        self.assertEqual(len(self.buffer.calls),14)

    def test_external_queue_capacity_blocks_new_submissions(self):
        self.buffer.pending=lambda *args:[{'id':str(i),'channelId':p,'status':'scheduled'} for i in range(6) for p in ['tiktok','instagram']]
        with self.assertRaisesRegex(Stop,'six pending'): self.run_scheduler()
        self.assertEqual(self.buffer.calls,[])

    def test_missed_slot_stops_without_bursting(self):
        self.now=datetime(2099,1,2,tzinfo=timezone.utc)
        with self.assertRaisesRegex(Stop,'Missed scheduling'): self.run_scheduler()
        self.assertEqual(self.buffer.calls,[])

    def test_modified_schedule_cannot_resume_existing_intent(self):
        self.buffer.disconnected=True
        with self.assertRaises(Stop): self.run_scheduler()
        self.buffer.disconnected=False
        self.scheduler.rows[0]['due_at']='2099-01-01T10:00:00+01:00'
        with self.assertRaisesRegex(Stop,'scheduled time'): self.run_scheduler()

    def test_disabled_plan_makes_no_calls(self):
        self.plan['enabled']=False
        self.assertEqual(self.run_scheduler(),{'enabled':False})
        self.assertEqual(self.buffer.calls,[])

    def test_plan_rejects_previously_used_ids_and_duplicate_times(self):
        bad=plan();bad['clips'][0]['clip_id']='M000009'
        with self.assertRaises(Stop): validate_plan(bad)
        bad=plan();bad['clips'][1]['due_at']=bad['clips'][0]['due_at']
        with self.assertRaises(Stop): validate_plan(bad)

    def test_budapest_offsets_change_with_daylight_saving(self):
        zone=ZoneInfo('Europe/Budapest')
        self.assertEqual(datetime(2026,10,24,9,tzinfo=zone).utcoffset(),timedelta(hours=2))
        self.assertEqual(datetime(2026,10,28,9,tzinfo=zone).utcoffset(),timedelta(hours=1))

    def test_read_only_pages_availability_can_retry(self):
        with patch('publisher.scheduler.verify_public',side_effect=[Stop('Download failed; deployment pending'),None]) as verify,patch('publisher.scheduler.time.sleep'):
            wait_for_public({}, {}, Path('.'))
        self.assertEqual(verify.call_count,2)

    def test_hash_failure_does_not_retry_as_availability(self):
        with patch('publisher.scheduler.verify_public',side_effect=Stop('Downloaded content hash mismatch')) as verify,patch('publisher.scheduler.time.sleep') as sleep:
            with self.assertRaises(Stop): wait_for_public({}, {}, Path('.'))
        verify.assert_called_once();sleep.assert_not_called()

    def test_scheduled_payload_never_uses_share_now(self):
        p=payload('tiktok','id','text','https://example.com/v.mp4','2099-01-01T09:00:00+01:00')
        self.assertEqual(p['mode'],'customScheduled')
        self.assertEqual(p['dueAt'],'2099-01-01T09:00:00+01:00')
        with self.assertRaises(Stop): payload('tiktok','id','text','https://example.com/v.mp4','2020-01-01T09:00:00+01:00')


class ScheduledCleanupTests(unittest.TestCase):
    def test_provider_confirmed_cleanup_requires_both_sent_and_grace(self):
        fixture=fixtures.EngineTests();fixture.setUp()
        fixture.publish();fixture.engine.confirm_public('M000032','tiktok','https://www.tiktok.com/test-post')
        fixture.publish('instagram')
        with self.assertRaises(Stop): fixture.engine.cleanup('M000032',provider_confirmed=True)
        for r in fixture.ledger.data['records'].values():
            r['sent_at']=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat()
        fixture.engine.cleanup('M000032',provider_confirmed=True)
        self.assertEqual(len(fixture.host.deletes),1)
        self.assertNotIn('public_verified_at',fixture.ledger.data['records']['M000032:instagram'])
        self.assertEqual(fixture.ledger.data['records']['M000032:instagram']['cleanup_basis'],'buffer_sent_both_platforms')

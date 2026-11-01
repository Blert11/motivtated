import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_publisher as fixtures
from publisher.buffer import Buffer, payload
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
    def reschedule(self, post_id, due_at, record=None):
        assert self.ledger.snapshots[-1]['events'][-1]['action'] == 'before_buffer_editPost'
        assert any(r.get('reschedule_intent',{}).get('post_id') == post_id
                   for r in self.ledger.snapshots[-1]['records'].values())
        self.posts[post_id]['dueAt'] = due_at
        return self.post(post_id)

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
        with self.assertRaisesRegex(Stop,'pending limit'): self.run_scheduler()
        self.assertEqual(self.buffer.calls,[])

    def test_storage_deferral_leaves_no_new_intent_and_resumes_later(self):
        before=set(self.ledger.data['records'])
        self.host.can_fit=lambda *args:False
        result=self.run_scheduler()
        self.assertEqual(result['deferred_for_storage'],'M000010')
        self.assertEqual(set(self.ledger.data['records']),before)
        self.assertEqual(self.buffer.calls,[])
        self.host.can_fit=lambda *args:True
        self.run_scheduler()
        self.assertEqual(len(self.buffer.calls),12)

    def test_missed_slot_stops_without_bursting(self):
        self.now=datetime(2099,1,2,tzinfo=timezone.utc)
        with self.assertRaisesRegex(Stop,'Missed scheduling'): self.run_scheduler()
        self.assertEqual(self.buffer.calls,[])

    def test_modified_schedule_cannot_resume_existing_intent(self):
        self.buffer.disconnected=True
        with self.assertRaises(Stop): self.run_scheduler()
        self.buffer.disconnected=False
        self.scheduler.rows[0]['due_at']='2099-01-01T10:00:00+01:00'
        with self.assertRaisesRegex(Stop,'previous time'): self.run_scheduler()

    def test_ten_daily_slots_and_ten_pending_after_two_bounded_refills(self):
        self.plan.update(posts_per_day=10,max_pending_per_channel=10)
        for n,row in enumerate(self.plan['clips']):
            row['due_at']=(datetime(2099,1,1+n//10,9,tzinfo=ZoneInfo('Europe/Budapest'))
                           +timedelta(minutes=90*(n%10))).isoformat()
        validate_plan(self.plan)
        self.run_scheduler(); self.run_scheduler(); self.run_scheduler()
        self.assertEqual(len(self.buffer.calls),20)
        for p in ['tiktok','instagram']:
            self.assertEqual(sum(r['channelId']==p for r in self.buffer.posts.values()),10)

    def change_second_slot(self):
        row=self.plan['clips'][1]
        row['previous_due_at']=row['due_at']
        row['due_at']='2099-01-01T10:30:00+01:00'
        return row

    def test_batch5_extension_keeps_order_and_pending_limit(self):
        self.plan.update(posts_per_day=10,max_pending_per_channel=10)
        self.plan['clips'].extend({'clip_id':f'M{n:06d}','bundle_sha256':'b'*64} for n in range(66,108))
        for n,row in enumerate(self.plan['clips']):
            row['due_at']=(datetime(2099,1,1+n//10,9,tzinfo=ZoneInfo('Europe/Budapest'))
                           +timedelta(minutes=90*(n%10))).isoformat()
        self.assertEqual(len(validate_plan(self.plan)),64)
        # Existing batch has finished; only new IDs should be submitted.
        for row in self.plan['clips'][:22]:
            for platform in ['tiktok','instagram']:
                self.ledger.data['records'][row['clip_id']+':'+platform]={
                    'clip_id':row['clip_id'],'platform':platform,'state':'posted',
                    'channel_id':platform,'scheduled_at':row['due_at'],
                    'video_sha256':row['clip_id'].zfill(64)}
        self.run_scheduler();self.run_scheduler();self.run_scheduler()
        self.assertEqual(len(self.buffer.calls),20)
        self.assertEqual({r['clip_id'] for r in self.ledger.data['records'].values() if r['state']=='submitted'},
                         {f'M{n:06d}' for n in range(66,76)})

    def test_batch5_extension_rejects_duplicate_or_unapproved_ids(self):
        self.plan['clips'].extend({'clip_id':f'M{n:06d}','bundle_sha256':'b'*64,
                                  'due_at':'2099-02-01T09:00:00+01:00'} for n in range(66,108))
        for wrong in ['M000032','M000066']:
            self.plan['clips'][-1]['clip_id']=wrong
            with self.assertRaisesRegex(Stop,'Approved order'): validate_plan(self.plan)

    def test_schedule_edit_preserves_ids_and_does_not_create_posts(self):
        self.run_scheduler(); ids=set(self.buffer.posts)
        row=self.change_second_slot()
        self.run_scheduler(); self.run_scheduler()
        self.assertEqual(set(self.buffer.posts),ids)
        self.assertEqual(len(self.buffer.calls),12)
        for p in ['tiktok','instagram']:
            r=self.ledger.data['records']['M000011:'+p]
            self.assertEqual(r['scheduled_at'],row['due_at'])
            self.assertEqual(len(r['schedule_history']),1)

    def test_lost_edit_response_recovers_by_readback_without_another_edit(self):
        self.run_scheduler(); self.change_second_slot()
        original=self.buffer.reschedule; edits=[]
        def lost(pid,due,record):
            edits.append(pid); original(pid,due,record); raise Stop('lost response')
        self.buffer.reschedule=lost
        with self.assertRaisesRegex(Stop,'lost response'): self.run_scheduler()
        self.buffer.reschedule=original
        self.run_scheduler()
        self.assertEqual(len(edits),1)
        self.assertEqual(len(self.buffer.calls),12)
        self.assertNotIn('reschedule_intent',self.ledger.data['records']['M000011:tiktok'])

    def test_unresolved_edit_is_not_blindly_retried(self):
        self.run_scheduler(); self.change_second_slot(); edits=[]
        def lost(pid,due,record): edits.append(pid); raise Stop('lost response')
        self.buffer.reschedule=lost
        with self.assertRaises(Stop): self.run_scheduler()
        with self.assertRaisesRegex(Stop,'no automatic edit retry'): self.run_scheduler()
        self.assertEqual(len(edits),1)

    def test_failed_intent_save_prevents_schedule_edit(self):
        self.run_scheduler(); row=self.change_second_slot()
        self.ledger.fail_action='before_buffer_editPost'
        with self.assertRaises(Stop): self.run_scheduler()
        r=self.ledger.data['records']['M000011:tiktok']
        self.assertEqual(self.buffer.posts[r['buffer_post_id']]['dueAt'],row['previous_due_at'])

    def test_reviewed_retry_only_edits_after_confirming_previous_time(self):
        self.run_scheduler(); self.change_second_slot()
        original=self.buffer.reschedule
        self.buffer.reschedule=lambda *a:(_ for _ in ()).throw(Stop('rejected'))
        with self.assertRaises(Stop): self.run_scheduler()
        self.buffer.reschedule=original
        self.scheduler.retry_edit='M000011:tiktok'
        self.run_scheduler()
        r=self.ledger.data['records']['M000011:tiktok']
        self.assertEqual(len(r['schedule_retry_history']),1)
        self.assertEqual(len(self.buffer.calls),12)

    def test_edit_error_redacts_key_and_url(self):
        b=Buffer(token='private-test-key')
        b.query=lambda *a:{'editPost':{'__typename':'InvalidInputError',
            'message':'bad private-test-key https://example.com/?private=value'}}
        record={'platform':'tiktok','channel_id':'tiktok','caption':'Keep moving','media':{'url':'https://media.example/video.mp4'}}
        with self.assertRaises(Stop) as error: b.reschedule('known','2099-01-01T09:00:00+01:00',record)
        self.assertNotIn('private-test-key',str(error.exception))
        self.assertNotIn('example.com',str(error.exception))
        self.assertIn('InvalidInputError',str(error.exception))

    def test_cannot_reschedule_a_sent_post(self):
        self.run_scheduler(); self.change_second_slot()
        r=self.ledger.data['records']['M000011:tiktok']
        self.buffer.posts[r['buffer_post_id']]['status']='sent'
        with self.assertRaisesRegex(Stop,'no longer scheduled'): self.run_scheduler()
        self.assertNotIn('reschedule_intent',r)

    def test_queue_capacity_over_free_limit_rejected(self):
        self.plan['max_pending_per_channel']=11
        with self.assertRaises(Stop): validate_plan(self.plan)

    def test_edit_payload_preserves_content_and_existing_id(self):
        b=Buffer(token='fake'); captured=[]
        def query(q,v):
            captured.append(v['input'])
            return {'editPost':{'__typename':'PostActionSuccess','post':{'id':'known'}}}
        b.query=query
        record={'platform':'instagram','channel_id':'instagram','caption':'Keep moving','media':{'url':'https://media.example/video.mp4'}}
        b.reschedule('known','2099-01-01T10:30:00+01:00',record)
        self.assertEqual(captured[0]['id'],'known')
        self.assertEqual(captured[0]['text'],record['caption'])
        self.assertEqual(captured[0]['assets'],[{'video':{'url':record['media']['url'],
            'metadata':{'thumbnailOffset':1000}}}])
        self.assertEqual(captured[0]['metadata']['instagram']['type'],'reel')
        self.assertEqual(captured[0]['dueAt'],'2099-01-01T10:30:00+01:00')
        self.assertEqual(captured[0]['mode'],'customScheduled')
        self.assertNotIn('channelId',captured[0])

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
    def test_short_retention_never_deletes_recent_or_partial_publication(self):
        fixture=fixtures.EngineTests();fixture.setUp()
        fixture.publish();fixture.engine.confirm_public('M000032','tiktok','https://www.tiktok.com/test-post')
        with self.assertRaises(Stop): fixture.engine.cleanup('M000032',provider_confirmed=True,grace_hours=2)
        fixture.publish('instagram')
        with self.assertRaises(Stop): fixture.engine.cleanup('M000032',provider_confirmed=True,grace_hours=2)
        for r in fixture.ledger.data['records'].values():
            r['sent_at']=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
        with self.assertRaises(Stop): fixture.engine.cleanup('M000032',grace_hours=2)
        ig=fixture.ledger.data['records']['M000032:instagram'];ig['state']='failed_at_buffer'
        with self.assertRaises(Stop): fixture.engine.cleanup('M000032',provider_confirmed=True,grace_hours=2)
        self.assertEqual(fixture.host.deletes,[])
        ig['state']='posted'
        fixture.engine.cleanup('M000032',provider_confirmed=True,grace_hours=2)
        self.assertEqual(len(fixture.host.deletes),1)

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


class PaceChangeTests(unittest.TestCase):
    def plan(self):
        import json
        from pathlib import Path
        return json.loads((Path(__file__).resolve().parents[1]/'posting-schedule.json').read_text(encoding='utf-8'))

    def test_committed_plan_switches_to_seven_daily_from_november_2(self):
        from publisher.scheduler import validate_plan, pace_for
        from datetime import date
        plan = self.plan()
        validate_plan(plan)
        self.assertEqual(pace_for(plan, date(2026, 11, 1)), 10)
        self.assertEqual(pace_for(plan, date(2026, 11, 2)), 7)

    def test_eighth_post_on_a_seven_post_day_is_rejected(self):
        from publisher.scheduler import validate_plan
        from publisher.common import Stop
        plan = self.plan()
        rows = {r['clip_id']: r for r in plan['clips']}
        rows['M000092']['due_at'] = '2026-11-02T22:45:00+01:00'
        with self.assertRaises(Stop):
            validate_plan(plan)

    def test_old_ten_slot_rejected_after_pace_change(self):
        from publisher.scheduler import validate_plan
        from publisher.common import Stop
        plan = self.plan()
        rows = {r['clip_id']: r for r in plan['clips']}
        rows['M000086']['due_at'] = '2026-11-02T10:30:00+01:00'
        with self.assertRaises(Stop):
            validate_plan(plan)

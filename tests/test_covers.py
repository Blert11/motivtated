import copy
import unittest
from datetime import datetime, timedelta, timezone
from publisher.buffer import payload
from publisher.common import Stop
from publisher.engine import Engine
from publisher.repair_covers import repair
from test_publisher import MemoryLedger


class CoverTests(unittest.TestCase):
    def setUp(self):
        self.ledger = MemoryLedger()
        self.due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        self.key = 'M000020:instagram'
        self.record = {'state':'submitted','platform':'instagram','buffer_post_id':'same-id',
                       'scheduled_at':self.due,'channel_id':'ig','caption':'Keep going. #motivtated 👑',
                       'media':{'url':'https://media.example/same.mp4'}}
        self.ledger.data['records'][self.key] = self.record
        self.post = {'id':'same-id','channelId':'ig','channelService':'instagram','status':'scheduled',
                     'text':self.record['caption'],'schedulingType':'automatic','dueAt':self.due,
                     'assets':[{'source':self.record['media']['url'],'video':{'thumbnailOffset':0}}],
                     'metadata':{'type':'reel'}}
        self.calls = []
        self.fail = False
        outer = self
        class Fake:
            def post(self, post_id): return copy.deepcopy(outer.post)
            def reschedule(self, post_id, due_at, record):
                saved = outer.ledger.snapshots[-1]
                assert saved['events'][-1]['action'] == 'before_buffer_cover_edit'
                assert saved['records'][outer.key]['cover_intent']['post_id'] == post_id
                outer.calls.append((post_id, due_at, copy.deepcopy(record)))
                if outer.fail: raise Stop('uncertain request')
                outer.post['assets'][0]['video']['thumbnailOffset'] = 1000
        self.engine = Engine(self.ledger, Fake())

    def test_payload_selects_frame_for_both_services_without_custom_image(self):
        for platform in ['instagram','tiktok']:
            p = payload(platform,'channel','Caption','https://media.example/a.mp4',self.due)
            self.assertEqual(p['assets'],[{'video':{'url':'https://media.example/a.mp4',
                                                  'metadata':{'thumbnailOffset':1000}}}])
            self.assertEqual(p['dueAt'],self.due)
            self.assertEqual(p['schedulingType'],'automatic')

    def test_same_id_same_due_and_no_second_edit(self):
        self.assertEqual(repair(self.engine,self.key),'confirmed')
        self.assertEqual(self.calls[0][:2],('same-id',self.due))
        self.assertEqual(repair(self.engine,self.key),'confirmed')
        self.assertEqual(len(self.calls),1)

    def test_ambiguous_result_blocks_retry_but_can_reconcile(self):
        self.fail = True
        with self.assertRaises(Stop): repair(self.engine,self.key)
        with self.assertRaises(Stop): repair(self.engine,self.key)
        self.assertEqual(len(self.calls),1)
        self.post['assets'][0]['video']['thumbnailOffset'] = 1000
        self.assertEqual(repair(self.engine,self.key),'confirmed')
        self.assertEqual(len(self.calls),1)

    def test_failed_durable_intent_prevents_edit(self):
        self.ledger.fail_action = 'before_buffer_cover_edit'
        with self.assertRaises(Stop): repair(self.engine,self.key)
        self.assertEqual(self.calls,[])

    def test_changed_caption_or_due_blocks_edit(self):
        for field,value in [('text','changed'),('dueAt',(datetime.now(timezone.utc)+timedelta(days=3)).isoformat())]:
            original = self.post[field]
            self.post[field] = value
            with self.assertRaises(Stop): repair(self.engine,self.key)
            self.post[field] = original
        self.assertEqual(self.calls,[])

    def test_sent_posts_and_imminent_posts_never_edited(self):
        self.post['status'] = 'sent'
        self.assertEqual(repair(self.engine,self.key),'skipped_no_longer_scheduled')
        self.assertEqual(repair(self.engine,self.key),'skipped_not_scheduled')
        self.record['state'] = 'submitted'
        self.record['scheduled_at'] = datetime.now(timezone.utc).isoformat()
        self.assertEqual(repair(self.engine,self.key),'skipped_due_soon_or_past')
        self.assertEqual(self.calls,[])

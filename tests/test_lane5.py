import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from publisher import lane5


class FakeLedger:
    def __init__(self, records=None):
        self.data = {'records': records or {}}
        self.saves = 0

    def save(self):
        self.saves += 1


class FakeZernio:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self.answers.pop(0)

    def accounts(self):
        return [{'_id': 'accM', 'platform': 'youtube', 'username': 'motivtated', 'isActive': True},
                {'_id': 'accI', 'platform': 'youtube', 'username': 'imanivated', 'isActive': True}]


def plan(n=3):
    rows = [{'key': f'imanivated:I{900+i:06d}', 'page': 'imanivated', 'clip_id': f'I{900+i:06d}',
             'asset_name': f'I{900+i:06d}.zip', 'bundle_sha256': 'a'*64} for i in range(n)]
    s = ['10:00', '12:00', '14:00', '16:00', '18:00', '20:00']
    return {'version': 1, 'enabled': True, 'slots': {'motivtated': s, 'imanivated': s}, 'rows': rows}


class Lane5Tests(unittest.TestCase):
    def make(self, answers, records=None, buffer_records=None, clock=datetime(2026, 11, 22, 8, 0, tzinfo=timezone.utc)):
        lane = lane5.Lane5(plan(), FakeLedger(records), FakeZernio(answers), None, None,
                           FakeLedger(buffer_records), clock=lambda: clock)
        lane.fill_one_real = lane.fill_one
        return lane

    def test_committed_plan_validates_and_has_no_removed_clips(self):
        p = json.loads(Path('lane5-schedule.json').read_text(encoding='utf-8'))
        rows = lane5.validate_plan(p)
        self.assertTrue(rows)
        self.assertFalse({r['clip_id'] for r in rows if r['page'] == 'motivtated'} & set(p['removed_ids']))
        self.assertEqual(len(p['slots']['motivtated']), 6)

    def test_next_slot_and_payload(self):
        due = lane5.next_slot(['10:00', '12:00'], datetime(2026, 11, 22, 10, 30, tzinfo=lane5.TZ))
        self.assertEqual((due.hour, due.minute), (12, 0))
        due = lane5.next_slot(['10:00', '12:00'], datetime(2026, 11, 22, 12, 0, tzinfo=lane5.TZ))
        self.assertEqual((due.day, due.hour), (23, 10))
        body = lane5.build_payload('acc', 'cap #imanivated', 'https://x/v.mp4', due, 'Title')
        self.assertEqual(body['scheduledFor'], '2026-11-23T09:00:00Z')
        self.assertEqual(body['platforms'][0]['platformSpecificData']['title'], 'Title')

    def run_fill(self, lane):
        def fake_one(row, key, acc, due):
            code, answer = lane.zernio.call('POST', '/posts', {'due': due.isoformat()})
            lane.records[key] = {'row': row['key'], 'clip_id': row['clip_id'], 'page': row['page'], 'platform': 'youtube',
                                 'channel_id': acc, 'due_at': due.isoformat(),
                                 'state': 'submitted' if code == 201 else 'needs_attention', 'zernio_post_id': lane5.post_id(answer)}
        with patch.object(lane, 'fill_one', side_effect=fake_one):
            lane.fill({'imanivated': 'accI', 'motivtated': 'accM'})

    def test_clips_get_consecutive_slots_and_skip_buffer_queue(self):
        lane = self.make([(201, {'post': {'_id': 'p1', 'status': 'scheduled'}}), (201, {'post': {'_id': 'p2'}})],
                         buffer_records={'imanivated:I000900-yt2:youtube': {'platform': 'youtube', 'state': 'submitted', 'clip_id': 'I000900'}})
        self.run_fill(lane)
        recs = lane.records
        self.assertNotIn('imanivated:I000900:youtube', recs)        # still queued on Buffer: never sent again
        self.assertEqual(recs['imanivated:I000901:youtube']['due_at'], '2026-11-22T10:00:00+01:00')
        self.assertEqual(recs['imanivated:I000902:youtube']['due_at'], '2026-11-22T12:00:00+01:00')

    def test_real_fill_one_rejection_and_unclear_answer(self):
        lane = self.make([(400, {'error': 'bad video'})])
        row = plan()['rows'][0]
        with patch.object(lane, 'load', return_value=({'files': {'video.mp4': {'sha256': 'b'*64}}, 'caption': 'c #imanivated'}, Path('.'))), \
             patch.object(lane5.lane2, 'verify_wait'):
            lane.media = type('M', (), {'ensure': lambda *a: {'url': 'https://x/v.mp4'}})()
            lane.fill_one(row, row['key']+':youtube', 'accI', datetime(2026, 11, 22, 10, tzinfo=lane5.TZ))
            self.assertEqual(lane.records[row['key']+':youtube']['state'], 'failed_before_submit')
            lane.zernio.answers = [(502, {})]
            lane.fill_one(row, row['key']+':youtube', 'accI', datetime(2026, 11, 22, 12, tzinfo=lane5.TZ))
            self.assertEqual(lane.records[row['key']+':youtube']['state'], 'needs_attention')

    def test_reconcile_marks_published(self):
        rec = {'row': 'imanivated:I000900', 'page': 'imanivated', 'platform': 'youtube', 'state': 'submitted',
               'due_at': '2026-11-22T07:00:00+00:00', 'zernio_post_id': 'p1'}
        lane = self.make([], records={'imanivated:I000900:youtube': rec})
        lane.zernio.post = lambda pid: {'status': 'published', 'platforms': [{'platformPostUrl': 'https://youtu.be/x'}]}
        lane.reconcile()
        self.assertEqual(rec['state'], 'posted')
        self.assertEqual(rec['post_url'], 'https://youtu.be/x')


if __name__ == '__main__':
    unittest.main()

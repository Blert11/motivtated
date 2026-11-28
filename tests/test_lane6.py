import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from publisher import lane5, lane6


class FakeLedger:
    def __init__(self):
        self.data = {'organization_id': 'org'}

    def save(self):
        pass


class FakeBuffer:
    def __init__(self, waiting):
        self.waiting = waiting

    def pending(self, org, channel_ids):
        return [{'channelId': c} for c, n in self.waiting.items() for _ in range(n)]


class Lane6Tests(unittest.TestCase):
    def plan(self):
        return json.loads(Path('lane6-schedule.json').read_text(encoding='utf-8'))

    def test_plan_validates(self):
        rows = lane6.validate_plan(self.plan())
        self.assertEqual(rows[0]['clip_id'], 'MA0001')
        for page in ('motivtated', 'imanivated'):
            times = [r['due_at'] for r in rows if r['page'] == page]
            self.assertTrue(all(t.endswith('T18:00:00+01:00') for t in times))
            self.assertEqual(len(times), len(set(t[:10] for t in times)))   # one a day

    def test_rejects_second_post_same_day(self):
        plan = self.plan()
        extra = dict(plan['rows'][0], key='motivtated:MA0099', clip_id='MA0099', asset_name='MA0099.zip')
        plan['rows'].insert(1, extra)
        with self.assertRaises(Exception):
            lane6.validate_plan(plan)

    def test_fill_waits_for_horizon_and_full_queue(self):
        plan = self.plan()
        first = datetime.fromisoformat(plan['rows'][0]['due_at'])
        channels = {'motivtated:tiktok': 't', 'motivtated:instagram': 'i', 'motivtated:facebook': 'f'}
        calls = []
        lane = lane6.Lane6(plan, 'motivtated', FakeLedger(), FakeBuffer({'t': 10, 'i': 3, 'f': 0}), None, None,
                           clock=lambda: first - timedelta(hours=20))
        lane.fill_row = lambda row, todo, counts: calls.append((row['clip_id'], [p for p, _, _ in todo]))
        lane.fill(channels)
        self.assertEqual(calls, [('MA0001', ['instagram', 'facebook'])])   # TikTok queue full; next day too far ahead

    def test_missed_time_is_skipped(self):
        plan = self.plan()
        first = datetime.fromisoformat(plan['rows'][0]['due_at'])
        lane = lane6.Lane6(plan, 'motivtated', FakeLedger(), FakeBuffer({}), None, None, clock=lambda: first)
        lane.fill_row = lambda *a: self.fail('nothing should be created')
        lane.fill({'motivtated:tiktok': 't'})
        self.assertEqual(lane.records['motivtated:MA0001:tiktok']['state'], 'skipped_missed')

    def test_lane5_story_rows(self):
        plan = json.loads(Path('lane5-schedule.json').read_text(encoding='utf-8'))
        rows = lane5.validate_plan(plan)
        story = [r for r in rows if r.get('release') == lane5.STORY_RELEASE]
        self.assertTrue(story and all(r['due_at'].endswith('T18:00:00+01:00') for r in story))
        self.assertNotIn('motivtated:MA0006', [r['key'] for r in story])   # 5-minute video is not a Short

    def test_lane5_regular_clip_skips_story_slot(self):
        slots = ['10:00', '18:00', '20:00']
        taken = {datetime(2026, 11, 29, 18, 0, tzinfo=lane5.TZ)}
        after = datetime(2026, 11, 29, 11, 0, tzinfo=lane5.TZ)
        self.assertEqual(lane5.next_slot(slots, after, taken).hour, 20)


if __name__ == '__main__':
    unittest.main()

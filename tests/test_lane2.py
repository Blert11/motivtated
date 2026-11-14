import json, unittest
from pathlib import Path
from publisher import lane2
from publisher.common import Stop


class Lane2Tests(unittest.TestCase):
    def test_plan_validates(self):
        plan = json.loads(Path('lane2-schedule.json').read_text(encoding='utf-8'))
        self.assertTrue(lane2.validate_plan(plan))

    def test_youtube_payload_has_title_and_category(self):
        p = lane2.build_payload('youtube', 'c1', 'Line #motivtated 👑', 'https://x/y.mp4', '2030-01-01T10:00:00+01:00', 'Line')
        self.assertEqual(p['metadata']['youtube']['title'], 'Line')
        self.assertEqual(p['metadata']['youtube']['categoryId'], '22')
        self.assertFalse(p['metadata']['youtube']['madeForKids'])
        self.assertEqual(p['mode'], 'customScheduled')

    def test_twitter_payload_plain(self):
        p = lane2.build_payload('twitter', 'c2', 'Line #motivtated 👑', 'https://x/y.mp4', '2030-01-01T10:00:00+01:00')
        self.assertNotIn('metadata', p)

    def test_youtube_needs_title(self):
        with self.assertRaises(Stop):
            lane2.build_payload('youtube', 'c1', 'x', 'https://x/y.mp4', '2030-01-01T10:00:00+01:00', None)

    def test_title_from_caption(self):
        self.assertEqual(lane2.youtube_title({'title': None}, 'Work hard. #motivtated 🏆'), 'Work hard.')

    def test_rejects_five_a_day(self):
        plan = json.loads(Path('lane2-schedule.json').read_text(encoding='utf-8'))
        rows = [r for r in plan['rows'] if r['page'] == 'imanivated'][:5]
        rows[4] = dict(rows[4], due_at=rows[0]['due_at'].replace('10:00', '12:00'))
        with self.assertRaises(Stop):
            lane2.validate_plan({**plan, 'rows': rows})


if __name__ == '__main__':
    unittest.main()


class Lane2KeepGoingTests(unittest.TestCase):
    """Owner rule 2026-11-14: one failing post never stops the others (other platforms or the same one)."""
    def setUp(self):
        from datetime import datetime, timezone
        self.plan = {'version': 1, 'enabled': True, 'max_pending_per_channel': 10, 'note': '', 'rows': [
            {'key': f'motivtated:M{n:06d}', 'page': 'motivtated', 'clip_id': f'M{n:06d}', 'asset_name': f'M{n:06d}.zip',
             'bundle_sha256': '0' * 64, 'platforms': ['youtube', 'twitter'], 'title': f'Clip {n}',
             'due_at': f'2099-01-0{1 + (n - 300) // 7}T{[10, 12, 14, 16, 18, 20, 21][(n - 300) % 7]:02d}:{"30" if (n - 300) % 7 == 6 else "00"}:00+01:00'}
            for n in range(300, 304)]}

        class Ledger:
            data = {}
            def save(self): pass
        class Buffer:
            def __init__(s): s.made = []
            def query(s, q, v):
                p = v['input']
                if 'M000301' in json.dumps(p): raise Stop('network dropped during createPost')
                s.made.append(p); return {'createPost': {'__typename': 'PostActionSuccess', 'post': {'id': str(len(s.made)), 'status': 'scheduled'}}}
        class Media:
            def ensure(s, path, cid, sha):
                if cid == 'M000302': raise Stop('Pages upload failed')
                return {'url': f'https://example.invalid/{cid}.mp4'}
        self.buffer = Buffer()
        self.lane = lane2.Lane2(self.plan, Ledger(), self.buffer, Media(), None,
                                clock=lambda: datetime(2098, 12, 31, tzinfo=timezone.utc))
        self.lane.load = lambda row, d: ({'clip_id': row['clip_id'], 'caption': 'x #motivtated 👑',
                                          'files': {'video.mp4': {'sha256': '1' * 64}}}, d)
        self._vw = lane2.verify_wait
        lane2.verify_wait = lambda *a: None

    def tearDown(self):
        lane2.verify_wait = self._vw

    def test_failures_stay_with_their_post(self):
        ch = {'motivtated:youtube': 'yt', 'motivtated:twitter': 'tw'}
        self.lane.fill(ch)
        r = self.lane.records
        self.assertEqual(r['motivtated:M000300:youtube']['state'], 'submitted')
        self.assertEqual(r['motivtated:M000301:youtube']['state'], 'needs_attention')     # never resubmitted
        self.assertEqual(r['motivtated:M000302:youtube']['state'], 'failed_before_submit')
        self.assertEqual(r['motivtated:M000303:youtube']['state'], 'submitted')           # same platform carries on
        self.assertEqual(r['motivtated:M000303:twitter']['state'], 'submitted')
        for _ in range(3):
            self.lane.fill(ch)
        self.assertEqual(r['motivtated:M000302:youtube']['attempts'], 3)                  # retried, then left alone
        made = len(self.buffer.made); self.lane.fill(ch)
        self.assertEqual(len(self.buffer.made), made)

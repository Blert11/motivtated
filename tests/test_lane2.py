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
        rows[4] = dict(rows[4], due_at=rows[0]['due_at'].replace('10:00', '11:00'))
        with self.assertRaises(Stop):
            lane2.validate_plan({**plan, 'rows': rows})


if __name__ == '__main__':
    unittest.main()

import json
import unittest
from pathlib import Path

from publisher import lane4


class Lane4Tests(unittest.TestCase):
    def test_plan_validates(self):
        plan = json.loads(Path('lane4-schedule.json').read_text(encoding='utf-8'))
        rows = lane4.validate_plan(plan)
        self.assertTrue(rows)
        self.assertEqual(rows[0]['clip_id'], 'I000046')

    def test_matches_youtube_lane(self):
        yt = {r['clip_id']: r for r in json.loads(Path('lane2-schedule.json').read_text(encoding='utf-8'))['rows']
              if r['page'] == 'imanivated'}
        for r in json.loads(Path('lane4-schedule.json').read_text(encoding='utf-8'))['rows']:
            pass  # YouTube moved to 2 a day (2026-11-19); TikTok/IG/FB keep their own times
            self.assertEqual(r['bundle_sha256'], yt[r['clip_id']]['bundle_sha256'])

    def test_payloads(self):
        ig = lane4.build_payload('instagram', 'c', 'cap', 'u', '2026-12-01T10:00:00+01:00', 3000)
        self.assertEqual(ig['metadata'], {'instagram': {'type': 'reel', 'shouldShareToFeed': True}})
        fb = lane4.build_payload('facebook', 'c', 'cap', 'u', '2026-12-01T10:00:00+01:00', 3000)
        self.assertEqual(fb['metadata'], {'facebook': {'type': 'reel'}})
        tt = lane4.build_payload('tiktok', 'c', 'cap', 'u', '2026-12-01T10:00:00+01:00', 3000)
        self.assertNotIn('metadata', tt)
        self.assertEqual(tt['assets'][0]['video']['metadata']['thumbnailOffset'], 3000)

    def test_rejects_duplicates(self):
        plan = json.loads(Path('lane4-schedule.json').read_text(encoding='utf-8'))
        plan['rows'].append(dict(plan['rows'][-1]))
        with self.assertRaises(Exception):
            lane4.validate_plan(plan)


if __name__ == '__main__':
    unittest.main()

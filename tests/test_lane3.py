import json, unittest
from datetime import datetime, timezone
from pathlib import Path
from publisher import lane2, lane3
from publisher.common import Stop


class Lane3Tests(unittest.TestCase):
    def test_plan_validates(self):
        plan = json.loads(Path('lane3-schedule.json').read_text(encoding='utf-8'))
        rows = lane3.validate_plan(plan)
        self.assertEqual(len({r['key'] for r in rows}), len(rows))

    def test_rejects_eight_a_day(self):
        plan = json.loads(Path('lane3-schedule.json').read_text(encoding='utf-8'))
        rows = [r for r in plan['rows'] if r['page'] == 'imanivated'][:8]
        rows[7] = dict(rows[7], due_at=rows[6]['due_at'].replace('21:00', '21:30'))
        with self.assertRaises(Stop):
            lane3.validate_plan({**plan, 'rows': rows})

    def test_payload_has_board_title_link(self):
        p = lane3.build_payload('c', 'Line #motivtated 👑', 'https://x/y.mp4', '2030-01-01T09:00:00+01:00', 'Line', 'b1',
                                'https://www.tiktok.com/@motivtated')
        self.assertEqual(p['metadata']['pinterest'], {'title': 'Line', 'url': 'https://www.tiktok.com/@motivtated', 'boardServiceId': 'b1'})

    def test_board_keyword_then_rotation(self):
        boards = {'gym motivation': 'g', 'success quotes': 's', 'stop being lazy': 'l'}
        c = {}
        self.assertEqual(lane3.pick_board({'page': 'motivtated', 'title': 'Train when it hurts'}, '', boards, c), 'g')
        got = {lane3.pick_board({'page': 'motivtated', 'title': 'Nothing special'}, '', boards, c) for _ in range(3)}
        self.assertEqual(got, {'g', 's', 'l'})
        with self.assertRaises(Stop):
            lane3.pick_board({'page': 'imanivated', 'title': 'x'}, '', {}, c)

    def test_fill_schedules_pins_and_isolates_failures(self):
        plan = {'version': 1, 'enabled': True, 'max_pending_per_channel': 10, 'rows': [
            {'key': f'imanivated:I{n:06d}', 'page': 'imanivated', 'clip_id': f'I{n:06d}', 'asset_name': f'I{n:06d}.zip',
             'bundle_sha256': '0' * 64, 'platforms': ['pinterest'], 'title': f'Clip {n}',
             'due_at': f'2099-01-01T{[9, 11, 13][n - 1]:02d}:00:00+01:00'} for n in (1, 2, 3)]}

        class Ledger:
            data = {}
            def save(self): pass

        class Buffer:
            made = []
            def query(s, q, v):
                if 'boards' in q:
                    return {'channel': {'metadata': {'boards': [{'serviceId': 'B1', 'name': 'Islamic Reminders'}]}}}
                if 'I000002' in json.dumps(v):
                    raise Stop('network dropped during createPost')
                s.made.append(v['input'])
                return {'createPost': {'__typename': 'PostActionSuccess', 'post': {'id': str(len(s.made)), 'status': 'scheduled'}}}

        class Media:
            def ensure(s, path, cid, sha): return {'url': f'https://example.invalid/{cid}.mp4'}

        lane = lane3.Lane3(plan, Ledger(), Buffer(), Media(), None, clock=lambda: datetime(2098, 12, 31, tzinfo=timezone.utc))
        lane.load = lambda row, d: ({'clip_id': row['clip_id'], 'caption': 'x #imanivated 🤲',
                                     'files': {'video.mp4': {'sha256': '1' * 64}}}, d)
        vw, lane2.verify_wait = lane2.verify_wait, (lambda *a: None)
        try:
            lane.fill({'imanivated:pinterest': 'P'})
        finally:
            lane2.verify_wait = vw
        r = lane.records
        self.assertEqual(r['imanivated:I000001:pinterest']['state'], 'submitted')
        self.assertEqual(r['imanivated:I000002:pinterest']['state'], 'needs_attention')
        self.assertEqual(r['imanivated:I000003:pinterest']['state'], 'submitted')
        self.assertEqual(Buffer.made[0]['metadata']['pinterest']['boardServiceId'], 'B1')
        self.assertEqual(Buffer.made[0]['metadata']['pinterest']['url'], 'https://www.tiktok.com/@imanivated')

    def test_waits_without_boards_and_clears_board_failures(self):
        plan = {'version': 1, 'enabled': True, 'max_pending_per_channel': 10, 'rows': [
            {'key': 'imanivated:I000001', 'page': 'imanivated', 'clip_id': 'I000001', 'asset_name': 'I000001.zip',
             'bundle_sha256': '0' * 64, 'platforms': ['pinterest'], 'title': 'x', 'due_at': '2099-01-01T09:00:00+01:00'}]}

        class Ledger:
            data = {'channels': {'imanivated:pinterest': 'P', 'motivtated:pinterest': 'Q'}, 'records': {
                'imanivated:I000001:pinterest': {'state': 'failed_before_submit', 'attempts': 1,
                                                 'error': 'No Pinterest boards on the imanivated channel.', 'channel_id': 'P'}}}
            def save(self): pass

        class Buffer:
            def query(s, q, v):
                return {'channel': {'metadata': {'boards': []}}}
        lane = lane3.Lane3(plan, Ledger(), Buffer(), None, None, clock=lambda: datetime(2098, 12, 31, tzinfo=timezone.utc))
        rep = lane.run()
        self.assertEqual(lane.records, {})
        self.assertEqual(rep['boards'], {'imanivated:pinterest': 0, 'motivtated:pinterest': 0})

    def test_fix_covers_edits_waiting_pins_once(self):
        plan = {'version': 1, 'enabled': True, 'rows': []}
        rec = {'state': 'submitted', 'buffer_post_id': 'B1', 'channel_id': 'P', 'page': 'imanivated',
               'due_at': '2099-01-01T09:00:00+01:00', 'caption': 'c', 'title': 't', 'board': 'b',
               'media': {'url': 'https://example.invalid/v.mp4'}}

        class Ledger:
            data = {'records': {'imanivated:I000001:pinterest': rec}}
            def save(self): pass

        class Buffer:
            edits = []
            def query(s, q, v):
                s.edits.append(v['input'])
                return {'editPost': {'__typename': 'PostActionSuccess', 'post': {'id': 'B1'}}}

        class Resp:
            def __enter__(s): return s
            def __exit__(s, *a): pass
            def read(s): return b''
        lane = lane3.Lane3(plan, Ledger(), Buffer(), None, None, clock=lambda: datetime(2098, 12, 31, tzinfo=timezone.utc))
        uo, pc = lane3.urllib.request.urlopen, lane3.pick_cover_ms
        lane3.urllib.request.urlopen, lane3.pick_cover_ms = (lambda *a, **k: Resp()), (lambda v: 4500)
        try:
            lane.fix_covers(); lane.fix_covers()
        finally:
            lane3.urllib.request.urlopen, lane3.pick_cover_ms = uo, pc
        self.assertEqual(len(Buffer.edits), 1)
        self.assertEqual(Buffer.edits[0]['id'], 'B1')
        self.assertEqual(Buffer.edits[0]['assets'][0]['video']['metadata']['thumbnailOffset'], 4500)
        self.assertEqual(rec['cover_ms'], 4500)


if __name__ == '__main__':
    unittest.main()

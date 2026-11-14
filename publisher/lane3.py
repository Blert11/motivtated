"""Lane 3: schedule Pinterest video pins through the THIRD Buffer account.

Separate from lane 1 (TikTok/Instagram/Facebook) and lane 2 (YouTube/X): own Buffer key
(BUFFER_API_KEY_3), own plan (lane3-schedule.json), own ledger (lane3-state.json on the
publisher-state branch) and its own media release (lane3-media), so another lane's cleanup
never removes a video a pin still needs. Same safety rules as lane 2 (it reuses its code):
a Buffer create is never retried automatically, every transition is saved before the next call,
one failing pin never stops the others, a missed slot is skipped instead of posted late.

Owner request 2026-11-14: every Motivtated and Imanivated clip as a Pinterest video pin, 7 a day
per page, with a title, the caption as description, a board on that page and its TikTok link.
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import lane2
from .buffer import Buffer
from .common import Stop, env, now, require
from .github import GitHub, GitHubLedger

TZ = lane2.TZ
SLOTS = [(9, 0), (11, 0), (13, 0), (15, 0), (17, 0), (19, 0), (21, 0)]
PAGES = ('motivtated', 'imanivated')
LINKS = {'motivtated': 'https://www.tiktok.com/@motivtated', 'imanivated': 'https://www.tiktok.com/@imanivated'}
# Board picked by keywords in the pin's title/caption; first match wins, otherwise boards rotate.
BOARD_RULES = {
    'motivtated': [
        (r'\bgym|train|workout|body|pain|lift|run\b', 'Gym Motivation'),
        (r'\bmorning|wake|4 ?am|sleep|routine|early\b', 'Morning Routine Mindset'),
        (r'\blazy|excuse|comfort|soft|procrastinat|scroll|phone\b', 'Stop Being Lazy'),
        (r'\bdisciplin|consisten|habit|focus|lock in|grind|work ethic\b', 'Discipline Motivation'),
        (r'\bmoney|rich|success|million|business|wealth|win\b', 'Success Quotes'),
        (r'\bchange|better|grow|improv|mindset|become|learn|read\b', 'Self Improvement Tips'),
    ],
    'imanivated': [
        (r'\banxi|worr|stress|heart|sad|hard time|test|patien|sabr|tawakkul|trust\b', 'Duas for Anxiety'),
        (r'\bquran|qur.an|ayah|surah\b', 'Quran Quotes'),
        (r'\bramadan|fast\b', 'Ramadan Motivation'),
        (r'\bpray|salah|salat|fajr|sujood|masjid|mosque|dua\b', 'Salah Prayer Motivation'),
        (r'\bdeath|grave|jannah|akhirah|hereafter|judg|angel\b', 'Islamic Reminders'),
    ],
}


class Lane3Ledger(GitHubLedger):
    PATH = 'lane3-state.json'


class Media(lane2.Media):
    TAG = 'lane3-media'

    def release(self):
        if not self._release:
            rel = self.gh.request('GET', f'/releases/tags/{self.TAG}', missing_ok=True)
            if not rel:
                rel = self.gh.request('POST', '/releases', {'tag_name': self.TAG, 'target_commitish': self.branch,
                                      'name': 'Lane 3 media (temporary)', 'body': 'Pinterest clips waiting to post; removed after posting.',
                                      'draft': False, 'prerelease': True})
            self._release = rel
        return self._release


def validate_plan(plan):
    require(plan.get('version') == 1 and plan.get('enabled') in (True, False), 'Unsupported lane-3 plan.')
    require(plan.get('max_pending_per_channel', 10) <= 10, 'Buffer free holds at most 10 per channel.')
    seen, last, per_day = set(), {}, {}
    for row in plan['rows']:
        page = row['page']
        require(page in PAGES and re.fullmatch(lane2.ID_RE[page], row['clip_id']), 'Bad page/clip ID.')
        require(row['key'] == page+':'+row['clip_id'] and row['key'] not in seen, 'Duplicate or bad row key.')
        seen.add(row['key'])
        require(re.fullmatch(r'[0-9a-f]{64}', row['bundle_sha256']), 'Bad bundle digest.')
        require(re.fullmatch(re.escape(row['clip_id'])+r'(\.r[0-9]{1,2})?\.zip', row['asset_name']), 'Bad asset name.')
        require(row['platforms'] == ['pinterest'], 'Lane 3 posts only to Pinterest.')
        due = lane2.parse_time(row['due_at']).astimezone(TZ)
        require((due.hour, due.minute) in SLOTS and due.second == 0, 'Unexpected slot.')
        require(page not in last or due > last[page], 'Times must increase per page.')
        last[page] = due
        per_day[(page, due.date())] = per_day.get((page, due.date()), 0)+1
        require(per_day[(page, due.date())] <= len(SLOTS), 'Too many pins in one day for this page.')
        require(len(row.get('title') or '') <= 100, 'Pin title too long.')
    return plan['rows']


def pick_board(row, caption, boards, counter):
    """boards: {name_lower: serviceId}. Keyword rule first, otherwise rotate through all boards."""
    require(boards, f"No Pinterest boards on the {row['page']} channel.")
    text = ((row.get('title') or '')+' '+caption).lower()
    for pattern, name in BOARD_RULES[row['page']]:
        if re.search(pattern, text) and name.lower() in boards:
            return boards[name.lower()]
    names = sorted(boards)
    counter[row['page']] = counter.get(row['page'], -1)+1
    return boards[names[counter[row['page']] % len(names)]]


COVER_TIMES = (2.0, 3.0, 4.5, 6.0, 8.0, 10.0, 13.0)   # seconds; many clips open with a fade from black


def frame_luma(video, t):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(t), '-i', str(video), '-frames:v', '1',
                        '-vf', 'scale=48:-2,format=gray', '-f', 'rawvideo', '-'], capture_output=True, timeout=60)
    return sum(r.stdout)/len(r.stdout) if r.returncode == 0 and r.stdout else -1


def pick_cover_ms(video):
    """Earliest frame at least 2 s in that is about as bright as the clip gets (the graded clips are dark
    overall, so brightness is judged against the clip itself, never a fixed level). Falls back to 3 s."""
    lumas = [(t, frame_luma(video, t)) for t in COVER_TIMES]
    top = max(l for _, l in lumas)
    if top < 0:
        return 3000
    for t, l in lumas:
        if l >= max(0.75*top, 8):
            return int(t*1000)
    return 3000


def build_payload(channel_id, caption, url, due_at, title, board, link, cover_ms=3000):
    return {'text': caption, 'channelId': channel_id, 'schedulingType': 'automatic',
            'mode': 'customScheduled', 'dueAt': due_at, 'saveToDraft': False,
            'assets': [{'video': {'url': url, 'metadata': {'thumbnailOffset': cover_ms}}}],
            'metadata': {'pinterest': {'title': title, 'url': link, 'boardServiceId': board}}}


def fetch_boards(buffer, channel_id):
    q = ('query($input: ChannelInput!) { channel(input: $input) { metadata { ... on PinterestMetadata '
         '{ boards { serviceId name } } } } }')
    boards = ((buffer.query(q, {'input': {'id': channel_id}})['channel'] or {}).get('metadata') or {}).get('boards') or []
    return {(b.get('name') or b['serviceId']).strip().lower(): b['serviceId'] for b in boards if b.get('serviceId')}


def discover_channels(buffer, ledger):
    orgs = buffer.organizations()
    require(len(orgs) == 1, f'Expected one organization on the third Buffer account, found {len(orgs)}.')
    chans = [c for c in buffer.channels(orgs[0]['id']) if not c['isDisconnected'] and not c['isLocked']]
    ledger.data['channels_seen'] = [{'id': c['id'], 'name': c.get('name'), 'service': c['service']} for c in chans]
    pins = [c for c in chans if c['service'] == 'pinterest']
    found = {}
    for page, word in (('imanivated', 'iman'), ('motivtated', 'moti')):
        match = [c for c in pins if word in (c.get('name') or '').lower()]
        if len(match) == 1:
            found[page+':pinterest'] = match[0]['id']
    ledger.data['organization_id'] = orgs[0]['id']
    ledger.data['channels'] = found
    return found


class Lane3(lane2.Lane2):
    def __init__(self, plan, ledger, buffer, media, gh, clock=None):
        self.plan, self.rows = plan, validate_plan(plan)
        self.ledger, self.buffer, self.media, self.gh = ledger, buffer, media, gh
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.boards, self.counter = {}, {}
        # GitHub runs scheduled workflows only every few hours, so each run fills the queue up to Buffer's 10 per page.
        self.max_new = 20
        self.report = {'scheduled': [], 'posted': [], 'cleaned': [], 'skipped_missed': [], 'problems': []}

    def fill_row(self, row, todo, counts):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='lane3-') as scratch:
            manifest, content = self.load(row, Path(scratch))
            vid = manifest['files']['video.mp4']
            media = next((r['media'] for r in self.records.values() if r['row'] == row['key'] and r.get('media')
                          and not r.get('media_deleted_at')), None)
            if not media:
                media = self.media.ensure(content/'video.mp4', row['clip_id'], vid['sha256'])
                lane2.verify_wait(media, manifest, content)
            caption = manifest['caption']
            title = lane2.youtube_title(row, caption)
            cover = pick_cover_ms(content/'video.mp4')
            for p, ch, key in todo:
                if ch not in self.boards:
                    self.boards[ch] = fetch_boards(self.buffer, ch)
                board = pick_board(row, caption, self.boards[ch], self.counter)
                rec = {'row': row['key'], 'clip_id': row['clip_id'], 'page': row['page'], 'platform': p,
                       'channel_id': ch, 'due_at': row['due_at'], 'caption': caption, 'title': title, 'board': board,
                       'cover_ms': cover, 'media': media, 'state': 'submit_intent', 'created_at': now()}
                self.records[key] = rec
                self.event(key, 'before_buffer_createPost')
                try:
                    post = lane2.create_post(self.buffer, build_payload(ch, caption, media['url'], row['due_at'],
                                                                        title, board, LINKS[row['page']], cover))
                except lane2.SchemaRejected as exc:
                    rec['state'], rec['error'] = 'failed_before_submit', str(exc)[:600]
                    self.event(key, 'buffer_rejected_before_execution')
                    self.report['problems'].append(f'{key}: {str(exc)[:200]}')
                    continue
                except Stop as exc:
                    rec['state'], rec['error'] = 'needs_attention', str(exc)[:600]
                    self.event(key, 'uncertain_create_outcome')
                    self.report['problems'].append(f'{key}: uncertain create, left for review')
                    continue
                rec['buffer_post_id'], rec['buffer_status'] = post['id'], post['status']
                rec['state'] = 'submitted' if post['status'] in ('scheduled', 'sending') else 'needs_attention'
                self.event(key, 'buffer_post_id_received')
                counts[ch] += 1
                self.report['scheduled'].append({'key': key, 'due_at': row['due_at'], 'post_id': post['id']})

    def fix_covers(self):
        """Pins queued before covers were chosen (2026-11-14) showed the black first frame on Pinterest: set the
        cover on those still waiting more than 20 minutes ahead. Same post ID, caption, video, board and time;
        a refusal is recorded and never retried."""
        self.report['covers_fixed'] = []
        for key, rec in self.records.items():
            if rec.get('state') != 'submitted' or rec.get('cover_ms') or rec.get('cover_error') or not rec.get('buffer_post_id'):
                continue
            if lane2.parse_time(rec['due_at']) <= self.clock() + timedelta(minutes=20):
                continue
            try:
                with tempfile.TemporaryDirectory(prefix='cover-') as d:
                    video = Path(d)/'v.mp4'
                    with urllib.request.urlopen(rec['media']['url'], timeout=300) as r:
                        video.write_bytes(r.read())
                    cover = pick_cover_ms(video)
                edit = build_payload(rec['channel_id'], rec['caption'], rec['media']['url'], rec['due_at'], rec['title'],
                                     rec['board'], LINKS[rec['page']], cover)
                edit.pop('channelId'); edit['id'] = rec['buffer_post_id']
                res = self.buffer.query('mutation($input: EditPostInput!) { editPost(input: $input) { __typename '
                                        '... on PostActionSuccess { post { id status dueAt } } '
                                        '... on MutationError { message } } }', {'input': edit})['editPost']
            except Exception as exc:
                rec['cover_error'] = type(exc).__name__ + ': ' + str(exc)[:300]
                self.report['problems'].append(f'{key}: cover fix failed')
                continue
            if res.get('__typename') == 'PostActionSuccess':
                rec['cover_ms'] = cover
                self.event(key, 'cover_set')
                self.report['covers_fixed'].append(key)
            else:
                rec['cover_error'] = str(res.get('message'))[:300]
                self.report['problems'].append(f'{key}: cover fix refused')

    def run(self):
        self.report = {'scheduled': [], 'posted': [], 'cleaned': [], 'skipped_missed': [], 'problems': []}
        if not self.plan.get('enabled'):
            return {'enabled': False}
        channels = self.ledger.data.get('channels') or {}
        if set(channels) != {'motivtated:pinterest', 'imanivated:pinterest'}:
            channels = discover_channels(self.buffer, self.ledger)
            self.ledger.save()
        self.report['channels'] = channels
        # A pin that failed only because Buffer had no boards yet never reached Buffer: clear it so it is not
        # counted against its 3 attempts.
        for key in [k for k, r in self.records.items() if r.get('state') == 'failed_before_submit'
                    and str(r.get('error', '')).startswith('No Pinterest boards')]:
            del self.records[key]
        self.reconcile()
        self.fix_covers()
        self.cleanup()
        ready = {}
        for name, ch in channels.items():
            self.boards[ch] = fetch_boards(self.buffer, ch)
            if self.boards[ch]:
                ready[name] = ch
            else:
                self.report['problems'].append(f'{name}: Buffer has no boards for this channel yet; waiting.')
        self.report['boards'] = {name: len(self.boards[ch]) for name, ch in channels.items()}
        self.fill(ready)
        return self.report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--plan', type=Path, default=Path('lane3-schedule.json'))
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    rows = validate_plan(plan)
    if args.dry_run:
        print(json.dumps({'validation': 'passed', 'rows': len(rows)}))
        return
    if not os.environ.get('BUFFER_API_KEY_3'):
        print('BUFFER_API_KEY_3 is not set yet; nothing to do.')
        return
    gh = GitHub(env('GITHUB_REPOSITORY'), env('GITHUB_TOKEN'))
    ledger = Lane3Ledger(gh)
    ledger.initialize()
    media = Media(GitHub(env('MEDIA_GITHUB_REPOSITORY'), env('MEDIA_GITHUB_TOKEN')), env('MEDIA_PUBLIC_BASE_URL'))
    lane = Lane3(plan, ledger, Buffer(token=env('BUFFER_API_KEY_3')), media, gh)
    try:
        report = lane.run()
        status = 'ok'
    except Exception as exc:
        report = {**lane.report, 'error': str(exc)[:600] if isinstance(exc, Stop) else type(exc).__name__}
        status = 'stopped'
    ledger.data['last_run'] = {'at': now(), 'status': status, 'report': report}
    ledger.save()
    print(json.dumps(report, ensure_ascii=False))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('Lane 3 (Pinterest)\n\n```json\n'+json.dumps(report, indent=2, ensure_ascii=False)+'\n```\n')
    if status != 'ok':
        raise SystemExit(2)


if __name__ == '__main__':
    main()

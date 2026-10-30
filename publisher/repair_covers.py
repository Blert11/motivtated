"""Repair only existing future scheduled posts; never creates or republishes posts."""
import json
from datetime import datetime, timedelta, timezone
from .buffer import Buffer, COVER_OFFSET_MS
from .common import Stop, now, require
from .engine import Engine
from .github import GitHubLedger


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def offset(post):
    assets = post.get('assets') or []
    return assets[0].get('video', {}).get('thumbnailOffset') if len(assets) == 1 else None


def repair(engine, key):
    record = engine.ledger.data['records'][key]
    if record.get('state') != 'submitted' or not record.get('scheduled_at'):
        return 'skipped_not_scheduled'
    require(not record.get('reschedule_intent'), 'Resolve existing schedule edit before editing cover.')
    due = timestamp(record['scheduled_at'])
    if due <= datetime.now(timezone.utc) + timedelta(minutes=10):
        return 'skipped_due_soon_or_past'
    post_id = record['buffer_post_id']
    engine.event(key, 'before_cover_lookup')
    post = engine.buffer.post(post_id)
    require(post['id'] == post_id, 'Buffer returned a different post ID.')
    if post['status'] != 'scheduled':
        engine.accept_post(key, record, post, strict_source=False)
        return 'skipped_no_longer_scheduled'

    def check(post):
        require(post['id'] == post_id and post['channelId'] == record['channel_id']
                and post['channelService'] == record['platform']
                and post['status'] == 'scheduled' and post['schedulingType'] == 'automatic'
                and post['text'].strip() == record['caption']
                and timestamp(post['dueAt']) == due,
                'Post identity, content, or schedule changed; cover edit stopped.')
        require(len(post.get('assets', [])) == 1, 'Only a single-video post can receive a cover repair.')
        if record['platform'] == 'instagram':
            require((post.get('metadata') or {}).get('type') == 'reel', 'Instagram post is not a Reel.')

    check(post)
    change = {'post_id': post_id, 'due_at': record['scheduled_at'], 'thumbnail_offset_ms': COVER_OFFSET_MS}
    intent = record.get('cover_intent')
    require(not intent or intent == change, 'Unresolved different cover edit; inspect first.')
    if offset(post) != COVER_OFFSET_MS:
        require(not intent, 'Cover edit outcome is unresolved; no automatic retry.')
        require(not record.get('media_deleted_at') and record.get('media', {}).get('url'), 'Original hosted video is unavailable.')
        record['cover_intent'] = change
        engine.event(key, 'before_buffer_cover_edit')
        # Existing edit path preserves ID, caption, media, layout, and exact due time.
        engine.buffer.reschedule(post_id, record['scheduled_at'], record)
        engine.event(key, 'before_cover_readback')
        post = engine.buffer.post(post_id)
    check(post)
    require(offset(post) == COVER_OFFSET_MS, 'Cover offset was not confirmed; preserve intent for reconciliation.')
    record['thumbnail_offset_ms'] = COVER_OFFSET_MS
    record['cover_verified_at'] = now()
    record.pop('cover_intent', None)
    engine.event(key, 'cover_confirmed_by_readback')
    return 'confirmed'


def main():
    ledger = GitHubLedger.from_env()
    ledger.load()
    engine = Engine(ledger, Buffer())
    results = {}
    for key, record in list(ledger.data['records'].items()):
        if record.get('platform') in ['instagram', 'tiktok']:
            results[key] = repair(engine, key)
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Stop as exc:
        raise SystemExit('STOP: ' + str(exc))

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .buffer import payload
from .common import Stop, clip_id, json_bytes, now, require
from .media import verify_public


class Engine:
    def __init__(self, ledger, buffer, host=None, verify=verify_public):
        self.ledger, self.buffer, self.host, self.verify = ledger, buffer, host, verify

    def event(self, key, action):
        self.ledger.data['events'].append({'at': now(), 'record': key, 'action': action})
        self.ledger.save()

    def discover(self):
        self.event(None, 'before_buffer_organizations_query')
        organizations = self.buffer.organizations()
        result = []
        for org in organizations:
            self.event(None, 'before_buffer_channels_query')
            result.extend(self.buffer.channels(org['id']))
        return result

    def publish(self, manifest, directory, platform, channel_id, resume=False, confirmed_unposted=False):
        require(platform in ['tiktok','instagram'], 'Invalid platform.')
        identifier = clip_id(manifest['clip_id'])
        require(confirmed_unposted, 'Confirm this clip has not already been posted manually on this platform.')
        # M000001 was supplied for the previous manual tests. Do not risk reusing it.
        require(identifier not in {f'M{n:06d}' for n in range(1,6)},
                'Tate videos 1-5 are excluded by the user; start from M000006.')
        records = self.ledger.data['records']
        key = identifier+':'+platform
        if platform == 'instagram':
            tiktok = records.get(identifier+':tiktok', {})
            # The public-visibility gate is the initial integration milestone, not a per-clip chore.
            established = any(r.get('platform') == 'instagram' and r.get('channel_id') == channel_id
                and r.get('state') == 'posted' and r.get('public_verified_at')
                and records.get(r['clip_id']+':tiktok', {}).get('state') == 'posted'
                and records.get(r['clip_id']+':tiktok', {}).get('public_verified_at')
                for r in records.values())
            require(established or (tiktok.get('state') == 'posted' and tiktok.get('public_verified_at') and not tiktok.get('media_deleted_at')),
                    'First verify this clip publicly on TikTok and run confirm-public before the Instagram milestone.')
        video_hash = manifest['files']['video.mp4']['sha256']
        for other_key, other in records.items():
            if other_key != key and other['platform'] == platform and other['video_sha256'] == video_hash:
                raise Stop('This exact video already has a ledger entry on this platform under another ID.')
        if key in records:
            record = records[key]
            require(resume and record['state'] in ['preparing','failed_before_submit'],
                    'Existing intent/post blocks resubmission. Use reconcile; only pre-submission work can resume.')
            require(record['files'] == manifest['files'] and record['channel_id'] == channel_id,
                    'A reserved attempt cannot change files or channel.')
            record['state'] = 'preparing'
        else:
            record = {'clip_id': identifier, 'platform': platform, 'channel_id': channel_id,
                      'video_sha256': video_hash, 'source_sha256': manifest['source_sha256'],
                      'files': manifest['files'], 'caption': manifest['caption'],
                      'state': 'preparing', 'created_at': now()}
            records[key] = record
        self.event(key, 'claim_before_media_or_buffer')
        try:
            self.event(key, 'before_buffer_channel_query')
            channel = self.buffer.channel(channel_id)
            require(channel['id'] == channel_id and channel['service'] == platform, 'Configured channel belongs to the wrong platform.')
            require(not channel['isDisconnected'] and not channel['isLocked'], 'Refresh or unlock this Buffer channel first.')
            record['media'] = self.host.upload(directory/'video.mp4', identifier, video_hash)
            self.event(key, 'media_uploaded_waiting_verification')
            self.verify(record['media'], manifest, directory)
            request = payload(platform, channel_id, record['caption'], record['media']['url'])
        except Exception:
            record['state'] = 'failed_before_submit'
            self.event(key, 'pre_submission_failure')
            raise
        record['state'] = 'submit_intent'
        record['request_sha256'] = hashlib.sha256(json_bytes(request)).hexdigest()
        self.event(key, 'before_buffer_createPost')
        # Never wrap this mutation in a retry. An uncertain result remains blocked permanently
        # until an existing post is located and reconciled. State-save failure is also uncertain.
        post = self.buffer.create(request)
        record['buffer_post_id'] = post['id']
        record['state'] = 'submitted'
        self.event(key, 'buffer_post_id_received')
        self.accept_post(key, record, post, strict_source=False)
        return record

    def accept_post(self, key, record, post, strict_source):
        require(post['channelId'] == record['channel_id'] and post['channelService'] == record['platform'], 'Post belongs to a different channel.')
        require(post['text'].strip() == record['caption'], 'Post caption differs from this attempt.')
        require(post.get('schedulingType') == 'automatic', 'Post is not automatic; inspect Buffer before continuing.')
        if strict_source:
            require(record['media']['url'] in [a.get('source') for a in post.get('assets', [])],
                    'Cannot match this post to the recorded media URL. Manual investigation required; do not resubmit.')
        if record['platform'] == 'instagram':
            require((post.get('metadata') or {}).get('type') == 'reel', 'Instagram post is not a Reel.')
        record['buffer_post_id'] = post['id']
        record['buffer_status'] = post['status']
        record['post_url'] = post.get('externalLink')
        record['sent_at'] = post.get('sentAt')
        record['state'] = {'sent': 'posted', 'error': 'failed_at_buffer', 'draft': 'needs_attention',
                           'needs_approval': 'needs_attention', 'scheduled': 'submitted', 'sending': 'submitted'}.get(post['status'], 'needs_attention')
        self.event(key, 'buffer_status_recorded')

    def reconcile(self, identifier, platform, post_id=None):
        key = clip_id(identifier)+':'+platform
        record = self.ledger.data['records'].get(key)
        require(record and record.get('media'), 'No submitted media/intent exists for this clip/platform.')
        known_id = record.get('buffer_post_id')
        require(not (known_id and post_id and known_id != post_id), 'Cannot replace an existing Buffer post ID.')
        target_id = known_id or post_id
        require(target_id, 'Find the existing post in Buffer and supply --post-id. Never create another post to resolve an uncertain attempt.')
        self.event(key, 'before_buffer_post_query')
        post = self.buffer.post(target_id)
        require(post['id'] == target_id, 'Buffer returned a different post ID.')
        self.accept_post(key, record, post, strict_source=not bool(known_id))
        return record

    def confirm_public(self, identifier, platform, url):
        record = self.reconcile(identifier, platform)
        require(record['state'] == 'posted', 'Buffer has not confirmed publication yet.')
        parsed = urlsplit(url)
        domain = 'tiktok.com' if platform == 'tiktok' else 'instagram.com'
        require(parsed.scheme == 'https' and (parsed.hostname == domain or (parsed.hostname or '').endswith('.'+domain)), 'Use the actual platform post URL.')
        require(not parsed.username and not parsed.password and not parsed.query and not parsed.fragment, 'Use a clean post URL without tracking parameters.')
        require(record.get('post_url') and url.rstrip('/') == record['post_url'].rstrip('/'), 'URL must match Buffer externalLink; inspect the post before confirming.')
        record['public_verified_at'] = now()
        self.event(identifier+':'+platform, 'user_confirmed_public_visibility')
        return record

    def cleanup(self, identifier):
        records = [self.ledger.data['records'].get(clip_id(identifier)+':'+p) for p in ['tiktok','instagram']]
        require(all(r and r['state'] == 'posted' and r.get('public_verified_at') for r in records),
                'Both platforms must be posted and publicly verified before media cleanup.')
        require(all(r.get('sent_at') for r in records), 'Missing publication time; retain media.')
        for r in records:
            sent = datetime.fromisoformat(r['sent_at'].replace('Z','+00:00'))
            require((datetime.now(timezone.utc)-sent).total_seconds() >= 48*3600, 'Keep media at least 48 hours after both posts publish.')
        seen = set()
        for r in records:
            media = r['media']
            if media['url'] not in seen:
                self.event(identifier, 'before_hosted_media_delete')
                self.host.delete(media)
                seen.add(media['url'])
            r['media_deleted_at'] = now()
        self.event(identifier, 'hosted_media_cleanup_complete')
        return {'clip_id': identifier, 'hosted_copies_removed': len(seen)}

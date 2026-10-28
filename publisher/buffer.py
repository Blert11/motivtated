from datetime import datetime, timezone
from .common import HTTP, Stop, env, require

POST_FIELDS = '''id channelId channelService text status schedulingType externalLink sentAt dueAt
 assets { source } metadata { ... on InstagramPostMetadata { type } }'''


class Buffer:
    def __init__(self, token=None, http=None):
        self.token = token or env('BUFFER_API_KEY')
        self.http = http or HTTP()

    def query(self, query, variables=None):
        result = self.http.json('POST', 'https://api.buffer.com', {'Authorization': f'Bearer {self.token}'},
                                {'query': query, 'variables': variables or {}})
        if result.get('errors') or not result.get('data'):
            raise Stop('Buffer returned GraphQL errors. Check permissions/schema; mutation outcomes must be reconciled, not blindly retried.')
        return result['data']

    def organizations(self):
        return self.query('query { account { organizations { id name } } }')['account']['organizations']

    def channels(self, org_id):
        return self.query('query($input: ChannelsInput!) { channels(input: $input) { id name service isDisconnected isLocked } }',
                          {'input': {'organizationId': org_id}})['channels']

    def channel(self, channel_id):
        return self.query('query($input: ChannelInput!) { channel(input: $input) { id name service isDisconnected isLocked isQueuePaused } }',
                          {'input': {'id': channel_id}})['channel']

    def create(self, payload):
        result = self.query('mutation($input: CreatePostInput!) { createPost(input: $input) { __typename '
                            '... on PostActionSuccess { post { '+POST_FIELDS+' } } '
                            '... on MutationError { message } } }', {'input': payload})['createPost']
        if result.get('__typename') != 'PostActionSuccess' or not result.get('post', {}).get('id'):
            raise Stop('Buffer did not return a confirmed post ID. Inspect Buffer and reconcile this attempt; no automatic resubmission.')
        return result['post']

    def post(self, post_id):
        return self.query('query($input: PostInput!) { post(input: $input) { '+POST_FIELDS+' } }',
                          {'input': {'id': post_id}})['post']

    def pending(self, organization_id, channel_ids):
        result = self.query('query($input: PostsInput!) { posts(first: 100, input: $input) { '
            'edges { node { id channelId status dueAt } } pageInfo { hasNextPage } } }',
            {'input': {'organizationId': organization_id,
                       'filter': {'channelIds': channel_ids, 'status': ['scheduled','sending','draft','needs_approval']}}})['posts']
        require(not result['pageInfo']['hasNextPage'], 'Too many pending Buffer posts to audit safely.')
        return [edge['node'] for edge in result['edges']]


def payload(platform, channel_id, caption, media_url, due_at=None):
    require(platform in ['tiktok', 'instagram'], 'Unsupported platform.')
    data = {'text': caption, 'channelId': channel_id, 'schedulingType': 'automatic',
            'mode': 'shareNow', 'needsApproval': False, 'saveToDraft': False,
            'assets': [{'video': {'url': media_url}}]}
    if platform == 'instagram':
        data['metadata'] = {'instagram': {'type': 'reel', 'shouldShareToFeed': True}}
    if due_at:
        due = datetime.fromisoformat(due_at.replace('Z','+00:00'))
        require(due.tzinfo is not None and due > datetime.now(timezone.utc), 'Scheduled time must be in the future with a timezone.')
        data['mode'] = 'customScheduled'
        data['dueAt'] = due_at
    # The current API has no TikTok privacy input. Public visibility is checked after posting.
    return data

import hashlib
import os
import re
import json
import urllib.parse
import urllib.request

from .common import HTTP, Stop, env, https_url, require
from .github import GitHub


def key_for(identifier, digest):
    require(re.fullmatch(r'M\d{6}', identifier) and re.fullmatch(r'[0-9a-f]{64}', digest), 'Invalid media key.')
    return f'media/{identifier}-{digest}.mp4'


def verify_public(media, manifest, directory, http=None):
    https_url(media['url'])
    entry = manifest['files']['video.mp4']
    # A real, unauthenticated full download verifies content, not merely an HTTP 200 preview page.
    (http or HTTP()).download(media['url'], directory/'public-verification.mp4', entry['size'],
                              expected_sha=entry['sha256'], public=True)


class PagesHost:
    def can_fit(self, identifier, digest, size):
        if self.gh.file(key_for(identifier,digest),self.branch,True):
            return True
        tree = self.gh.request('GET', f'/git/trees/{urllib.parse.quote(self.branch, safe="")}?recursive=1')
        require(not tree.get('truncated'), 'Cannot establish total Pages site size.')
        return sum(item.get('size',0) for item in tree['tree'] if item['type']=='blob') + size <= 900_000_000

    def __init__(self, gh=None, base=None):
        self.gh = gh or GitHub(env('MEDIA_GITHUB_REPOSITORY'), env('MEDIA_GITHUB_TOKEN'))
        self.base = https_url(base or env('MEDIA_PUBLIC_BASE_URL'))
        repo = self.gh.request('GET')
        require(repo.get('private') is False, 'Pages media repository must be a separate PUBLIC repository.')
        require(self.gh.repo != os.environ.get('GITHUB_REPOSITORY'), 'Never put media in the publisher repository.')
        self.branch = repo['default_branch']
        pages = self.gh.request('GET', '/pages')
        require(https_url(pages['html_url']) == self.base, 'MEDIA_PUBLIC_BASE_URL must match the configured Pages site.')

    def upload(self, path, identifier, digest):
        require(path.stat().st_size < 100 * 1024 * 1024, 'GitHub rejects files over 100 MiB; use R2 for this clip.')
        key = key_for(identifier, digest)
        existing = self.gh.file(key, self.branch, True)
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == digest, 'Video changed before Pages upload; refusing to publish.')
        git_sha = hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()
        if existing:
            require(existing.get('sha') == git_sha, 'Existing public media differs; refusing to overwrite it.')
        else:
            tree = self.gh.request('GET', f'/git/trees/{urllib.parse.quote(self.branch, safe="")}?recursive=1')
            require(not tree.get('truncated'), 'Cannot establish total Pages site size.')
            total = sum(item.get('size', 0) for item in tree['tree'] if item['type'] == 'blob')
            require(total + len(raw) <= 900_000_000, 'Pages site would exceed the conservative 900 MB cap; clean up confirmed posts or use R2.')
            if hasattr(self.gh, 'push_file'):
                # git push handles 40-100 MB clips; the Contents API PUT returned HTTP 422 for a 55 MB clip.
                self.gh.push_file(key, path, self.branch, f'Host clip {identifier}')
                hosted = self.gh.file(key, self.branch, True)
                require(hosted and hosted.get('sha') == git_sha, 'Pushed media does not match the local clip; do not publish.')
            else:
                self.gh.put(key, raw, self.branch, f'Host clip {identifier}')
        return {'provider': 'pages', 'key': key, 'url': self.base+'/'+key,
                'repository': self.gh.repo, 'branch': self.branch, 'git_sha': git_sha}

    def delete(self, media):
        require(media['provider'] == 'pages' and media['repository'] == self.gh.repo
                and media['branch'] == self.branch and media['url'] == self.base+'/'+media['key'], 'Media configuration changed; refusing deletion.')
        existing = self.gh.file(media['key'], self.branch, True)
        if existing:
            require(existing.get('sha') == media['git_sha'], 'Hosted object changed; refusing deletion.')
            self.gh.request('DELETE', '/contents/'+media['key'], {'message': 'Remove confirmed published media',
                            'branch': self.branch, 'sha': existing['sha']})


class R2Host:
    STORAGE_LIMIT_BYTES = 2_000_000_000
    STORAGE_WARNING_BYTES = 1_500_000_000

    def __init__(self, client=None, bucket=None, base=None):
        self.bucket = bucket or env('R2_BUCKET')
        self.base = https_url(base or env('MEDIA_PUBLIC_BASE_URL'))
        if client is None:
            import boto3
            from botocore.config import Config
            account = env('R2_ACCOUNT_ID')
            require(re.fullmatch(r'[0-9a-f]{32}', account), 'Invalid R2 account ID.')
            client = boto3.client('s3', endpoint_url=f'https://{account}.r2.cloudflarestorage.com',
                                  aws_access_key_id=env('R2_ACCESS_KEY_ID'), aws_secret_access_key=env('R2_SECRET_ACCESS_KEY'),
                                  region_name='auto', config=Config(retries={'max_attempts': 2, 'mode': 'standard'},
                                  request_checksum_calculation='when_required', response_checksum_validation='when_required'))
        self.client = client

    def usage(self):
        """Bounded scan of this dedicated bucket, not a Cloudflare billing/spend cap."""
        total = 0
        objects = 0
        continuation = None
        seen = set()
        for _ in range(10):
            params = {'Bucket': self.bucket, 'MaxKeys': 1000}
            if continuation:
                params['ContinuationToken'] = continuation
            try:
                page = self.client.list_objects_v2(**params)
            except Exception:
                raise Stop('Cannot measure R2 storage; new uploads are stopped until the check succeeds.') from None
            for item in page.get('Contents', []):
                size = item.get('Size')
                require(isinstance(size, int) and size >= 0, 'Invalid object size in R2 response; cannot establish usage.')
                total += size
                objects += 1
            if not page.get('IsTruncated'):
                return {'provider':'r2', 'bucket':self.bucket, 'storage_bytes':total, 'object_count':objects,
                        'storage_limit_bytes':self.STORAGE_LIMIT_BYTES,
                        'warning':total >= self.STORAGE_WARNING_BYTES,
                        'stop_new_uploads':total >= self.STORAGE_LIMIT_BYTES,
                        'billing_scope':'This bucket only; does not measure account spend or public read operations.'}
            continuation = page.get('NextContinuationToken')
            require(continuation and continuation not in seen, 'R2 pagination is incomplete; new uploads are stopped.')
            seen.add(continuation)
        raise Stop('R2 bucket has too many objects to audit safely in one run; new uploads are stopped.')

    def head(self, key):
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            code = getattr(e, 'response', {}).get('Error', {}).get('Code')
            if code in ['404', 'NoSuchKey', 'NotFound']:
                return None
            raise Stop('R2 metadata request failed; check bucket permissions.') from None

    def upload(self, path, identifier, digest):
        key = key_for(identifier, digest)
        existing = self.head(key)
        if existing:
            require(existing.get('Metadata', {}).get('sha256') == digest and existing['ContentLength'] == path.stat().st_size,
                    'Existing R2 media differs; refusing overwrite.')
        else:
            usage = self.usage()
            require(usage['storage_bytes'] + path.stat().st_size <= self.STORAGE_LIMIT_BYTES,
                    'Upload would exceed the 2 GB application storage ceiling. Retain pending videos; clean up only confirmed posts.')
            try:
                with path.open('rb') as f:
                    self.client.put_object(Bucket=self.bucket, Key=key, Body=f, ContentType='video/mp4',
                                           Metadata={'sha256': digest}, CacheControl='public, max-age=3600')
            except Exception:
                raise Stop('R2 upload failed; no Buffer post was submitted by this upload.') from None
        return {'provider': 'r2', 'key': key, 'url': self.base+'/'+key, 'bucket': self.bucket, 'sha256': digest}

    def delete(self, media):
        require(media['provider'] == 'r2' and media['bucket'] == self.bucket
                and media['url'] == self.base+'/'+media['key'], 'Media configuration changed; refusing deletion.')
        existing = self.head(media['key'])
        if existing:
            require(existing.get('Metadata', {}).get('sha256') == media['sha256'], 'Hosted object changed; refusing deletion.')
            try:
                self.client.delete_object(Bucket=self.bucket, Key=media['key'])
            except Exception:
                raise Stop('R2 deletion failed; retain the ledger and retry cleanup later.') from None


class ReleaseHost(PagesHost):
    """Main-lane clips as assets of a public prerelease in the media repo (2026-11-22).

    A release asset is public as soon as its upload returns, so runs no longer sit for minutes
    waiting for a Pages deploy (those waits used most of the account's Actions minutes).
    Older records hosted on Pages are still deleted through PagesHost."""
    TAG = 'lane1-media'

    def __init__(self, gh=None, base=None):
        super().__init__(gh, base)
        self._release = None

    def can_fit(self, identifier, digest, size):
        return True                      # assets are up to 2 GB each with no site-size cap

    def release(self):
        if not self._release:
            rel = self.gh.request('GET', f'/releases/tags/{self.TAG}', missing_ok=True)
            if not rel:
                rel = self.gh.request('POST', '/releases', {'tag_name': self.TAG, 'target_commitish': self.branch,
                                      'name': 'Main lane media (temporary)', 'body': 'Clips waiting to post; removed after posting.',
                                      'draft': False, 'prerelease': True})
            self._release = rel
        return self._release

    def upload(self, path, identifier, digest):
        key_for(identifier, digest)
        name = f'{identifier}-{digest[:16]}.mp4'
        rel = self.release()
        found = [a for a in self.gh.request('GET', f"/releases/{rel['id']}/assets?per_page=100") if a['name'] == name]
        if found:
            asset = found[0]
        else:
            raw = path.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == digest, 'Video changed before upload; refusing to publish.')
            req = urllib.request.Request(f"https://uploads.github.com/repos/{self.gh.repo}/releases/{rel['id']}/assets?name={name}",
                                         data=raw, method='POST', headers={**self.gh.headers, 'Content-Type': 'video/mp4',
                                                                           'Content-Length': str(len(raw))})
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    asset = json.loads(r.read())
            except Exception:
                raise Stop('Release asset upload failed; nothing was posted.') from None
        require(asset.get('state') == 'uploaded' and asset.get('size') == path.stat().st_size, 'Uploaded asset incomplete.')
        if asset.get('digest'):
            require(asset['digest'] == 'sha256:'+digest, 'Uploaded asset digest mismatch.')
        return {'provider': 'release', 'key': name, 'url': https_url(asset['browser_download_url']),
                'asset_id': asset['id'], 'repository': self.gh.repo, 'sha256': digest}

    def delete(self, media):
        if media.get('provider') != 'release':
            return super().delete(media)
        require(media['repository'] == self.gh.repo, 'Media configuration changed; refusing deletion.')
        self.gh.request('DELETE', f"/releases/assets/{media['asset_id']}", missing_ok=True)


def host_from_env():
    provider = env('MEDIA_PROVIDER')
    require(provider in ['pages', 'r2', 'release'], 'MEDIA_PROVIDER must be pages, release or r2.')
    # 'pages' now means the same public media repo, but new clips go up as release assets (no deploy wait).
    return ReleaseHost() if provider in ('pages', 'release') else R2Host()

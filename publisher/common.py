import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


class Stop(RuntimeError):
    """A deliberate stop requiring a correction or reconciliation."""


def require(condition, message):
    if not condition:
        raise Stop(message)


def env(name):
    value = os.environ.get(name, '').strip()
    require(value, f'Missing environment variable: {name}')
    return value


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def json_bytes(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def clip_id(value):
    require(bool(re.fullmatch(r'M\d{6}', value)), 'Clip ID must have format M000032.')
    return value


def https_url(value):
    p = urllib.parse.urlsplit(value)
    require(p.scheme == 'https' and p.hostname and not p.username and not p.password
            and not p.query and not p.fragment, 'Use a stable HTTPS URL without credentials, query, or fragment.')
    return value.rstrip('/')


class HTTP:
    """No automatic mutation retries. Errors omit credentials and response bodies."""
    def json(self, method, url, headers=None, data=None, missing_ok=False, form=None):
        headers = dict(headers or {})
        headers.setdefault('User-Agent', 'motivtated-publisher/1')
        payload = None
        if data is not None:
            headers['Content-Type'] = 'application/json'
            payload = json_bytes(data)
        if form is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
            payload = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                body = response.read(20 * 1024 * 1024 + 1)
                require(len(body) <= 20 * 1024 * 1024, 'API response unexpectedly large.')
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and missing_ok:
                return None
            raise Stop(f'HTTP {exc.code} from {urllib.parse.urlsplit(url).hostname}; no automatic retry.') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise Stop('Network/JSON response failure; no automatic mutation retry.') from None

    def download(self, url, path, limit, headers=None, expected_sha=None, public=False):
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                require(urllib.parse.urlsplit(response.url).scheme == 'https', 'Download redirected away from HTTPS.')
                if public:
                    content_type = response.headers.get('Content-Type', '').lower()
                    require('video/' in content_type or 'application/octet-stream' in content_type,
                            'Public URL did not serve a video file.')
                h = hashlib.sha256()
                size = 0
                with path.open('wb') as f:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        require(size <= limit, 'Download exceeds permitted size.')
                        h.update(chunk)
                        f.write(chunk)
                require(size > 0, 'Empty download.')
                if expected_sha:
                    require(h.hexdigest() == expected_sha, 'Downloaded content hash mismatch; do not publish.')
        except (urllib.error.URLError, TimeoutError, OSError):
            raise Stop('Download failed; public media may not be deployed yet. No post was created by this download.') from None

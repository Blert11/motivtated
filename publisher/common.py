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


def github_error_message(exc, headers):
    """Only expose GitHub's bounded message field, with known credentials redacted."""
    try:
        body = exc.read(8193)
        if len(body) > 8192:
            return ''
        message = json.loads(body).get('message')
        if not isinstance(message, str):
            return ''
        secrets = [value for name, value in os.environ.items()
                   if re.search(r'TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY', name, re.I) and value]
        for name, value in headers.items():
            if re.search(r'authorization|cookie|token|key', name, re.I):
                secrets.extend([value, value.split(' ', 1)[-1]])
        for value in sorted(set(secrets), key=len, reverse=True):
            for representation in {value, urllib.parse.quote(value, safe='')}:
                message = message.replace(representation, '[REDACTED]')
        message = re.sub(r'(?i)\b(?:Bearer\s+\S+|github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]+)',
                         '[REDACTED]', message)
        message = re.sub(r'https?://\S+', '[URL]', message)
        message = ' '.join(''.join(c if c.isprintable() else ' ' for c in message).split())
        return message[:500] + ('...' if len(message) > 500 else '')
    except (OSError, ValueError, AttributeError, TypeError):
        return ''


class HTTP:
    """No automatic mutation retries; only sanitized GitHub error messages are exposed."""
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
            hostname = urllib.parse.urlsplit(url).hostname
            message = github_error_message(exc, headers) if hostname == 'api.github.com' else ''
            detail = f' GitHub message: {message}' if message else ''
            if hostname == 'api.buffer.com' and exc.code == 400:
                # GraphQL request rejected before execution; keep Buffer's (non-secret) validation text.
                try:
                    errs = json.loads(exc.read(65536) or b'{}').get('errors') or []
                    text = '; '.join(str(e.get('message', ''))[:200] for e in errs[:3])
                except Exception:
                    text = ''
                text = re.sub(r'https?://\S+', '[URL]', text)
                detail = f' Buffer message: {text}' if text else ''
            raise Stop(f'HTTP {exc.code} from {hostname}; no automatic retry.{detail}') from None
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

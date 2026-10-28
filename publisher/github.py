import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

from .common import HTTP, Stop, env, json_bytes, require


class GitHub:
    def __init__(self, repo, token, http=None):
        require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'Invalid GitHub repository name.')
        self.repo = repo
        self.http = http or HTTP()
        self.token = token
        self.headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                        'X-GitHub-Api-Version': '2022-11-28'}

    def request(self, method, path='', data=None, missing_ok=False):
        return self.http.json(method, f'https://api.github.com/repos/{self.repo}{path}', self.headers, data, missing_ok)

    def file(self, path, branch, metadata_only=False):
        url = f'https://api.github.com/repos/{self.repo}/contents/{path}?ref={urllib.parse.quote(branch, safe="")}'
        if not metadata_only:
            return self.http.json('GET', url, self.headers, None, True)
        # Files of 1-100 MB need the "object" media type; it still returns the blob sha.
        return self.http.json('GET', url, {**self.headers, 'Accept': 'application/vnd.github.object+json'}, None, True)

    def put(self, path, content, branch, message, sha=None):
        data = {'message': message, 'content': base64.b64encode(content).decode('ascii'), 'branch': branch}
        if sha:
            data['sha'] = sha
        return self.request('PUT', f'/contents/{path}', data)

    def push_file(self, path, source, branch, message):
        """Add ONE new file with git itself (the Contents API rejects large request bodies).
        Fails if the file already exists on the branch; never force-pushes or rewrites history."""
        require(re.fullmatch(r'[A-Za-z0-9_./-]+', path) and '..' not in path, 'Unsafe media path.')
        auth = base64.b64encode(f'x-access-token:{self.token}'.encode()).decode()
        git_env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
        work = Path(tempfile.mkdtemp(prefix='media-push-'))

        def git(*args):
            result = subprocess.run(['git', '-c', f'http.extraheader=AUTHORIZATION: basic {auth}', *args],
                                    cwd=work, env=git_env, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).replace(self.token, '***').replace(auth, '***')[-400:]
                raise Stop(f'git {args[0]} failed while hosting media: {detail.strip()}')
            return result.stdout
        try:
            git('init', '-q')
            git('remote', 'add', 'origin', f'https://github.com/{self.repo}.git')
            git('fetch', '-q', '--depth', '1', 'origin', branch)
            git('checkout', '-q', '-B', branch, 'FETCH_HEAD')
            target = work / path
            require(not target.exists(), 'Media file already exists in the media repository; refusing to overwrite it.')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            git('add', '--', path)
            git('-c', 'user.name=motivtated-publisher', '-c', 'user.email=publisher@users.noreply.github.com',
                'commit', '-q', '-m', message)
            git('push', '-q', 'origin', f'HEAD:refs/heads/{branch}')
        finally:
            shutil.rmtree(work, ignore_errors=True)


class GitHubLedger:
    BRANCH = 'publisher-state'
    PATH = 'publisher-state.json'

    def __init__(self, gh):
        self.gh = gh
        require(gh.request('GET').get('private') is True, 'Publisher repository must be private before state or publishing is enabled.')
        self.version = None
        self.data = None

    @classmethod
    def from_env(cls):
        return cls(GitHub(env('GITHUB_REPOSITORY'), env('GITHUB_TOKEN')))

    def initialize(self):
        ref = self.gh.request('GET', f'/git/ref/heads/{self.BRANCH}', missing_ok=True)
        if not ref:
            repo = self.gh.request('GET')
            base = self.gh.request('GET', f"/git/ref/heads/{repo['default_branch']}")
            self.gh.request('POST', '/git/refs', {'ref': f'refs/heads/{self.BRANCH}', 'sha': base['object']['sha']})
        existing = self.gh.file(self.PATH, self.BRANCH)
        if existing:
            return self.load()
        self.gh.put(self.PATH, json_bytes({'version': 1, 'records': {}, 'events': []}), self.BRANCH, 'Initialize publisher ledger')
        return self.load()

    def load(self):
        result = self.gh.file(self.PATH, self.BRANCH)
        require(result is not None, 'Run init-state once before publishing. Missing state is never silently reset.')
        require(result.get('encoding') == 'base64', 'State format/size unsupported; inspect ledger.')
        self.data = json.loads(base64.b64decode(result['content']))
        require(self.data.get('version') == 1, 'Unknown state version.')
        self.version = result['sha']
        return self.data

    def save(self):
        require(self.version, 'State must be loaded before writing.')
        try:
            result = self.gh.put(self.PATH, json_bytes(self.data), self.BRANCH,
                                 'Record publisher transition', self.version)
            self.version = result['content']['sha']
        except Exception:
            raise Stop('Durable state write failed or conflicted. Stopped before the next Buffer call; inspect ledger before retrying.') from None

import base64
import json
import re
import urllib.parse

from .common import HTTP, Stop, env, json_bytes, require


class GitHub:
    def __init__(self, repo, token, http=None):
        require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'Invalid GitHub repository name.')
        self.repo = repo
        self.http = http or HTTP()
        self.headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                        'X-GitHub-Api-Version': '2022-11-28'}

    def request(self, method, path='', data=None, missing_ok=False):
        return self.http.json(method, f'https://api.github.com/repos/{self.repo}{path}', self.headers, data, missing_ok)

    def file(self, path, branch):
        return self.request('GET', f'/contents/{path}?ref={urllib.parse.quote(branch, safe="")}', missing_ok=True)

    def put(self, path, content, branch, message, sha=None):
        data = {'message': message, 'content': base64.b64encode(content).decode('ascii'), 'branch': branch}
        if sha:
            data['sha'] = sha
        return self.request('PUT', f'/contents/{path}', data)


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

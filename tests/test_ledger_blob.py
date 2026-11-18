import base64, json, unittest
from publisher.github import GitHubLedger


class FakeGH:
    def __init__(self, data):
        self.blob = base64.b64encode(json.dumps(data).encode()).decode()
    def file(self, path, branch, metadata_only=False):
        return {'encoding': 'none', 'content': '', 'sha': 'a' * 40}
    def request(self, method, path='', data=None, missing_ok=False):
        assert method == 'GET' and path == '/git/blobs/' + 'a' * 40
        return {'encoding': 'base64', 'content': self.blob}


class LedgerOverOneMegabyte(unittest.TestCase):
    def test_large_state_is_read_through_its_blob(self):
        ledger = GitHubLedger.__new__(GitHubLedger)
        ledger.gh = FakeGH({'version': 1, 'records': {'x': {}}, 'events': []})
        self.assertEqual(ledger.load()['records'], {'x': {}})
        self.assertEqual(ledger.version, 'a' * 40)


if __name__ == '__main__':
    unittest.main()

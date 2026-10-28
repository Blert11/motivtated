import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from publisher.common import HTTP, Stop


class HTTPErrorTests(unittest.TestCase):
    def fail(self, body, host='api.github.com', status=422, missing_ok=False):
        error = urllib.error.HTTPError('https://' + host, status, 'failure', {}, io.BytesIO(body))
        with patch('urllib.request.urlopen', side_effect=error):
            return HTTP().json('POST', 'https://' + host + '/example',
                               {'Authorization': 'Bearer sensitive-token'}, missing_ok=missing_ok)

    def test_message_is_bounded_and_secrets_are_redacted(self):
        body = json.dumps({'message': 'Validation failed\n sensitive-token github_pat_example '
                           'https://example.com/?token=other ' + 'x'*1000,
                           'errors': ['never-print-this']}).encode()
        with self.assertRaises(Stop) as caught: self.fail(body)
        message = str(caught.exception)
        self.assertIn('Validation failed', message)
        for secret in ['sensitive-token', 'github_pat_example', 'token=other', 'never-print-this', '\n']:
            self.assertNotIn(secret, message)
        self.assertLess(len(message), 600)

    def test_environment_secret_is_redacted(self):
        with patch.dict('os.environ', {'GOOGLE_REFRESH_TOKEN': 'private-refresh'}):
            with self.assertRaises(Stop) as caught:
                self.fail(b'{"message":"Invalid private-refresh"}')
        self.assertNotIn('private-refresh', str(caught.exception))

    def test_invalid_or_large_bodies_are_not_logged(self):
        for body in [b'not-json secret', b'{"message":"' + b'x'*9000 + b'"}', b'[]']:
            with self.subTest(body_size=len(body)), self.assertRaises(Stop) as caught:
                self.fail(body)
            self.assertNotIn('GitHub message:', str(caught.exception))

    def test_other_services_keep_error_bodies_private(self):
        with self.assertRaises(Stop) as caught:
            self.fail(b'{"message":"private oauth detail"}', host='oauth.example.com')
        self.assertNotIn('private oauth', str(caught.exception))

    def test_missing_ok_remains_none(self):
        self.assertIsNone(self.fail(b'{"message":"Not found"}', status=404, missing_ok=True))

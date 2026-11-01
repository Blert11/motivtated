import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from publisher.bundles import download_github_release
from publisher.common import Stop
import test_publisher as fixtures
from test_publisher import manifest


class ReleaseDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.cleanup)
        self.target = Path(self.temp.name)/'input.zip'
        self.digest = hashlib.sha256(b'package').hexdigest()
        self.asset = {'name':'M000006.zip','state':'uploaded','size':7,'digest':'sha256:'+self.digest}
        self.private = True
        outer = self
        class GH:
            repo = 'owner/private'
            def request(self, method, path=''):
                return {'private':outer.private} if not path else {'assets':[outer.asset]}
        self.gh = GH()

    def cleanup(self):
        assert Path(self.temp.name).resolve().parent == Path(__file__).resolve().parent
        self.temp.cleanup()

    def download(self):
        return download_github_release('M000006',self.target,self.digest,self.gh)

    def test_verified_private_download_uses_exact_asset_and_env_token(self):
        def run(args, **kwargs):
            self.assertIn('M000006.zip',args)
            self.assertNotIn('test-token',args)
            self.assertEqual(kwargs['env']['GH_TOKEN'],'test-token')
            self.target.write_bytes(b'package')
            return SimpleNamespace(returncode=0)
        with patch.dict('os.environ',{'GITHUB_TOKEN':'test-token'}), patch('publisher.bundles.subprocess.run',side_effect=run):
            self.download()

    def test_public_repo_stops_before_download(self):
        self.private = False
        with patch('publisher.bundles.subprocess.run') as run, self.assertRaises(Stop): self.download()
        run.assert_not_called()

    def test_bad_remote_digest_stops_before_download(self):
        self.asset['digest']='sha256:wrong'
        with patch('publisher.bundles.subprocess.run') as run, self.assertRaises(Stop): self.download()
        run.assert_not_called()

    def test_oversized_asset_stops_before_download(self):
        self.asset['size']=300*1024*1024
        with patch('publisher.bundles.subprocess.run') as run, self.assertRaises(Stop): self.download()
        run.assert_not_called()

    def test_corrupt_download_stops(self):
        def run(*args, **kwargs):
            self.target.write_bytes(b'corrupt')
            return SimpleNamespace(returncode=0)
        with patch.dict('os.environ',{'GITHUB_TOKEN':'test-token'}), patch('publisher.bundles.subprocess.run',side_effect=run), self.assertRaises(Stop):
            self.download()

    def test_failed_command_does_not_echo_stderr(self):
        with patch.dict('os.environ',{'GITHUB_TOKEN':'test-token'}), patch('publisher.bundles.subprocess.run',return_value=SimpleNamespace(returncode=1,stderr=b'secret')) as run:
            with self.assertRaises(Stop) as caught: self.download()
        self.assertNotIn('secret',str(caught.exception))
        run.assert_called_once()

    def test_revision_asset_name_downloads_exact_revision(self):
        self.asset['name'] = 'M000006.r2.zip'
        def run(args, **kwargs):
            self.assertIn('M000006.r2.zip', args)
            self.target.write_bytes(b'package')
            return SimpleNamespace(returncode=0)
        with patch.dict('os.environ',{'GITHUB_TOKEN':'test-token'}), patch('publisher.bundles.subprocess.run',side_effect=run):
            download_github_release('M000006',self.target,self.digest,self.gh,asset_name='M000006.r2.zip')

    def test_revision_name_for_another_clip_is_rejected(self):
        self.asset['name'] = 'M000007.r2.zip'
        with patch('publisher.bundles.subprocess.run') as run, self.assertRaises(Stop):
            download_github_release('M000006',self.target,self.digest,self.gh,asset_name='M000007.r2.zip')
        run.assert_not_called()


class MilestoneTests(unittest.TestCase):
    def test_completed_integration_allows_next_instagram_without_manual_per_clip_gate(self):
        fixture = fixtures.EngineTests()
        fixture.setUp()
        fixture.publish()
        fixture.engine.confirm_public('M000032','tiktok','https://www.tiktok.com/test-post')
        fixture.publish('instagram')
        fixture.engine.confirm_public('M000032','instagram','https://www.instagram.com/test-post')
        fixture.m=manifest('M000006')
        fixture.m['files']['video.mp4']['sha256']='f'*64
        self.assertEqual(fixture.publish('instagram')['state'],'posted')

    def test_first_five_tate_clips_are_excluded(self):
        for n in range(1,6):
            fixture = fixtures.EngineTests(); fixture.setUp(); fixture.m=manifest(f'M{n:06d}')
            with self.assertRaises(Stop): fixture.publish()
            self.assertEqual(fixture.buffer.calls,[])

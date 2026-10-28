import base64
import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from publisher.buffer import Buffer, payload
from publisher.bundles import prepare, unpack, validate_caption
from publisher.common import Stop, json_bytes, sha256
from publisher.engine import Engine
from publisher.github import GitHubLedger
from publisher.media import PagesHost, R2Host, verify_public


class MemoryLedger:
    def __init__(self):
        self.data = {'version':1, 'records':{}, 'events':[]}
        self.snapshots = []
        self.fail_action = None

    def save(self):
        if self.data['events'] and self.data['events'][-1]['action'] == self.fail_action:
            raise Stop('simulated durable save failure')
        self.snapshots.append(copy.deepcopy(self.data))


class FakeBuffer:
    def __init__(self, ledger):
        self.ledger = ledger
        self.calls = []
        self.fail_create = False
        self.disconnected = False
        self.posts = {}

    def channel(self, identifier):
        return {'id':identifier, 'service':identifier, 'isDisconnected':self.disconnected, 'isLocked':False}

    def create(self, p):
        # Verify durability at the external-side-effect boundary.
        saved = self.ledger.snapshots[-1]
        assert saved['events'][-1]['action'] == 'before_buffer_createPost'
        assert any(r['state'] == 'submit_intent' for r in saved['records'].values())
        self.calls.append(p)
        if self.fail_create:
            raise Stop('simulated timeout AFTER server may have created a post')
        result = {'id':'post-'+p['channelId'], 'channelId':p['channelId'], 'channelService':p['channelId'],
                  'text':p['text'], 'schedulingType':'automatic', 'status':'sent',
                  'externalLink':f"https://www.{p['channelId']}.com/test-post", 'sentAt':datetime.now(timezone.utc).isoformat(),
                  'assets':[{'source':p['assets'][0]['video']['url']}],
                  'metadata':{'type':'reel'} if p['channelId']=='instagram' else None}
        self.posts[result['id']] = result
        return result

    def post(self, identifier):
        return copy.deepcopy(self.posts[identifier])


class FakeHost:
    def __init__(self): self.uploads = []; self.deletes = []
    def upload(self, path, identifier, digest):
        self.uploads.append(identifier)
        return {'provider':'fake','key':identifier,'url':f'https://media.example/{identifier}-{digest}.mp4'}
    def delete(self, media): self.deletes.append(media['url'])


def manifest(identifier='M000032'):
    return {'clip_id':identifier,'caption':'Keep moving. #motivtated 👑','source_sha256':'b'*64,
            'files':{'video.mp4':{'sha256':'a'*64,'size':4}, 'caption.txt':{'sha256':'c'*64,'size':42},
                     'metadata.json':{'sha256':'d'*64,'size':10}}}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.ledger = MemoryLedger(); self.buffer = FakeBuffer(self.ledger); self.host = FakeHost()
        self.engine = Engine(self.ledger,self.buffer,self.host, verify=lambda *args: None)
        self.m = manifest()

    def publish(self, platform='tiktok', **kwargs):
        return self.engine.publish(self.m, Path('.'), platform, platform, confirmed_unposted=True, **kwargs)

    def test_intent_is_durable_before_create(self):
        self.assertEqual(self.publish()['state'], 'posted')
        self.assertEqual(len(self.buffer.calls), 1)

    def test_second_run_never_resubmits(self):
        self.publish()
        with self.assertRaises(Stop): self.publish()
        with self.assertRaises(Stop): self.publish(resume=True)
        self.assertEqual(len(self.buffer.calls),1)

    def test_timeout_blocks_retry_even_without_post_id(self):
        self.buffer.fail_create = True
        with self.assertRaises(Stop): self.publish()
        self.assertEqual(self.ledger.snapshots[-1]['records']['M000032:tiktok']['state'],'submit_intent')
        with self.assertRaises(Stop): self.publish(resume=True)
        self.assertEqual(len(self.buffer.calls),1)

    def test_failed_intent_save_prevents_create(self):
        self.ledger.fail_action = 'before_buffer_createPost'
        with self.assertRaises(Stop): self.publish()
        self.assertEqual(self.buffer.calls,[])

    def test_failure_after_response_keeps_durable_intent(self):
        self.ledger.fail_action = 'buffer_post_id_received'
        with self.assertRaises(Stop): self.publish()
        saved = self.ledger.snapshots[-1]['records']['M000032:tiktok']
        self.assertEqual(saved['state'],'submit_intent')
        self.assertNotIn('buffer_post_id',saved)
        self.assertEqual(len(self.buffer.calls),1)

    def test_source_hash_deduplicates_renamed_video(self):
        self.publish(); self.m = manifest('M000033')
        with self.assertRaises(Stop): self.publish()
        self.assertEqual(len(self.buffer.calls),1)

    def test_disconnected_channel_can_resume_before_submission(self):
        self.buffer.disconnected = True
        with self.assertRaises(Stop): self.publish()
        self.assertEqual(len(self.host.uploads),0)
        self.buffer.disconnected = False
        self.assertEqual(self.publish(resume=True)['state'],'posted')

    def test_public_media_failure_blocks_buffer(self):
        self.engine.verify = lambda *args: (_ for _ in ()).throw(Stop('not deployed'))
        with self.assertRaises(Stop): self.publish()
        self.assertEqual(self.buffer.calls,[])

    def test_instagram_waits_for_public_tiktok_verification(self):
        self.publish()
        with self.assertRaises(Stop): self.publish('instagram')
        self.engine.confirm_public('M000032','tiktok','https://www.tiktok.com/test-post')
        self.publish('instagram')
        self.assertEqual(self.buffer.calls[-1]['metadata']['instagram']['type'],'reel')
        self.assertEqual(len(self.buffer.calls),2)

    def test_reconcile_does_not_publish(self):
        self.publish(); self.engine.reconcile('M000032','tiktok')
        self.assertEqual(len(self.buffer.calls),1)

    def test_unknown_post_id_requires_matching_asset(self):
        self.publish()
        r = self.ledger.data['records']['M000032:tiktok']; del r['buffer_post_id']; r['state']='submit_intent'
        self.buffer.posts['post-tiktok']['assets'] = [{'source':'https://wrong.example/video.mp4'}]
        with self.assertRaises(Stop): self.engine.reconcile('M000032','tiktok','post-tiktok')
        self.assertNotIn('buffer_post_id',r)

    def test_unknown_post_can_be_adopted_without_resubmission(self):
        self.publish()
        r = self.ledger.data['records']['M000032:tiktok']; del r['buffer_post_id']; r['state']='submit_intent'
        self.engine.reconcile('M000032','tiktok','post-tiktok')
        self.assertEqual(r['state'],'posted'); self.assertEqual(len(self.buffer.calls),1)

    def test_wrong_channel_cannot_be_adopted(self):
        self.publish()
        r=self.ledger.data['records']['M000032:tiktok']; del r['buffer_post_id']
        self.buffer.posts['post-tiktok']['channelId']='another-account'
        with self.assertRaises(Stop): self.engine.reconcile('M000032','tiktok','post-tiktok')
        self.assertNotIn('buffer_post_id',r)

    def test_changed_resume_input_is_blocked(self):
        self.buffer.disconnected=True
        with self.assertRaises(Stop): self.publish()
        self.m['files']['caption.txt']['sha256']='f'*64
        with self.assertRaises(Stop): self.publish(resume=True)
        self.assertEqual(self.buffer.calls,[])

    def test_notification_result_not_accepted(self):
        self.publish(); self.buffer.posts['post-tiktok']['schedulingType']='notification'
        with self.assertRaises(Stop): self.engine.reconcile('M000032','tiktok')

    def test_manual_test_clip_is_held(self):
        self.m = manifest('M000001')
        with self.assertRaises(Stop): self.publish()
        self.assertEqual(self.buffer.calls,[])

    def test_cleanup_requires_both_platforms_and_grace(self):
        self.publish()
        with self.assertRaises(Stop): self.engine.cleanup('M000032')
        self.engine.confirm_public('M000032','tiktok','https://www.tiktok.com/test-post')
        self.publish('instagram')
        self.engine.confirm_public('M000032','instagram','https://www.instagram.com/test-post')
        with self.assertRaises(Stop): self.engine.cleanup('M000032')
        for r in self.ledger.data['records'].values():
            r['sent_at']=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat()
        self.engine.cleanup('M000032')
        self.assertEqual(len(self.host.deletes),1)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='test-', dir=Path(__file__).resolve().parent)
        self.addCleanup(self.clean_temp)
        self.root=Path(self.temp.name)
        for folder in ['Staging/Clips','Staging/Captions','Staging/Metadata','Control']:
            (self.root/folder).mkdir(parents=True)
        self.video=self.root/'Staging/Clips/M000032.mp4'; self.video.write_bytes(b'fake-video')
        self.caption=self.root/'Staging/Captions/M000032.txt'; self.caption.write_bytes('Keep moving. #motivtated 👑\r\n'.encode())
        self.source=self.root/'source.mp4'; self.source.write_bytes(b'original-source')
        self.metadata=self.root/'Staging/Metadata/M000032.json'
        self.metadata.write_text(json.dumps({'id':'M000032','sha256':sha256(self.video)}))
        self.registry={'clips':{'M000032':{'state':'staged','sha256':sha256(self.video),'caption_sha256':sha256(self.caption),
                       'metadata_sha256':sha256(self.metadata),'source_sha256':sha256(self.source),'source_video':str(self.source)}}}
        (self.root/'Control/registry.json').write_text(json.dumps(self.registry))

    def clean_temp(self):
        assert Path(self.temp.name).resolve().parent == Path(__file__).resolve().parent
        self.temp.cleanup()

    @patch('publisher.bundles.probe', return_value={'duration_seconds':30})
    def test_prepare_roundtrip_preserves_crlf_caption_hash(self, _):
        output=self.root/'bundle.zip'
        info=prepare(self.root,'M000032',output)
        target=self.root/'unpacked'; target.mkdir()
        m=unpack(output,info['bundle_sha256'],target)
        self.assertEqual(m['clip_id'],'M000032')
        self.assertEqual((target/'caption.txt').read_bytes(),self.caption.read_bytes())

    @patch('publisher.bundles.probe', return_value={})
    def test_changed_caption_after_validation_blocks_prepare(self, _):
        self.caption.write_text('Different text. #motivtated 🏆',encoding='utf-8')
        with self.assertRaises(Stop): prepare(self.root,'M000032',self.root/'bundle.zip')

    def test_missing_pair_is_rejected(self):
        self.caption.unlink()
        with self.assertRaises(Stop): prepare(self.root,'M000032',self.root/'bundle.zip')

    @patch('publisher.bundles.probe', return_value={})
    def test_changed_source_is_rejected(self, _):
        self.source.write_bytes(b'changed')
        with self.assertRaises(Stop): prepare(self.root,'M000032',self.root/'bundle.zip')

    def test_path_traversal_bundle_is_rejected(self):
        p=self.root/'bad.zip'
        with zipfile.ZipFile(p,'w') as z: z.writestr('../escape','bad')
        target=self.root/'out'; target.mkdir()
        with self.assertRaises(Stop): unpack(p,sha256(p),target)
        self.assertFalse((self.root/'escape').exists())

    def test_caption_rules(self):
        for text in ['Hello #wakeuplockinn 👑','Hello #motivtated #extra 👑','Hello #motivtated','Hello\n#motivtated 👑','Hello #motivtated 👑🏆']:
            with self.subTest(text=text),self.assertRaises(Stop): validate_caption(text.encode())


class InfrastructureTests(unittest.TestCase):
    def test_compare_and_swap_failure_stops_ledger(self):
        class GH:
            def request(self,*a,**kw): return {'private':True}
            def put(self,*a,**kw): raise Stop('HTTP 409')
        ledger=GitHubLedger(GH()); ledger.version='old'; ledger.data={'events':[]}
        with self.assertRaises(Stop): ledger.save()

    def test_public_publisher_repository_rejected(self):
        class GH:
            def request(self,*a,**kw): return {'private':False}
        with self.assertRaises(Stop): GitHubLedger(GH())

    def test_graphql_mutation_error_is_not_retried(self):
        class Http:
            count=0
            def json(self,*a,**kw):
                self.count+=1
                return {'data':{'createPost':{'__typename':'MutationError','message':'example'}}}
        http=Http()
        with self.assertRaises(Stop): Buffer('test',http).create({})
        self.assertEqual(http.count,1)

    def test_payload_does_not_invent_tiktok_privacy_fields(self):
        p=payload('tiktok','id','Caption','https://example.com/v.mp4')
        self.assertEqual(p['mode'],'shareNow'); self.assertEqual(p['schedulingType'],'automatic')
        self.assertNotIn('metadata',p); self.assertFalse(p['needsApproval'])

    def test_public_video_is_verified_with_no_auth_headers(self):
        class Http:
            def download(self,url,path,limit,**kw):
                self.kw=kw
        http=Http(); verify_public({'url':'https://example.com/v.mp4'},manifest(),Path('.'),http)
        self.assertTrue(http.kw['public']); self.assertNotIn('headers',http.kw)

    def test_r2_never_overwrites_mismatched_object(self):
        class Client:
            def head_object(self,**kw): return {'Metadata':{'sha256':'wrong'},'ContentLength':4}
        host=R2Host(Client(),'bucket','https://media.example.com')
        with tempfile.TemporaryDirectory(prefix='test-', dir=Path(__file__).resolve().parent) as t:
            assert Path(t).resolve().parent == Path(__file__).resolve().parent
            p=Path(t)/'v.mp4'; p.write_bytes(b'1234')
            with self.assertRaises(Stop): host.upload(p,'M000032','a'*64)

    def test_pages_requires_public_separate_repo(self):
        class GH:
            repo='owner/media'
            def request(self,*a,**kw): return {'private':True}
        with self.assertRaises(Stop): PagesHost(GH(),'https://owner.github.io/media')

    def test_pages_upload_and_reuse_content_addressed_file(self):
        class GH:
            repo='owner/media'
            count=0
            existing=None
            def request(self,method,path='',**kw):
                if not path: return {'private':False,'default_branch':'main'}
                if path=='/pages': return {'html_url':'https://owner.github.io/media/'}
                return {'tree':[],'truncated':False}
            def file(self,*a): return self.existing
            def put(self,key,raw,branch,message):
                self.count+=1
                self.existing={'sha':hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest()}
        gh=GH(); host=PagesHost(gh,'https://owner.github.io/media')
        with tempfile.TemporaryDirectory(prefix='test-',dir=Path(__file__).resolve().parent) as t:
            assert Path(t).resolve().parent==Path(__file__).resolve().parent
            p=Path(t)/'v.mp4'; p.write_bytes(b'1234')
            first=host.upload(p,'M000032',sha256(p))
            self.assertEqual(host.upload(p,'M000032',sha256(p)),first)
            self.assertEqual(gh.count,1)

    def test_pages_site_size_guard(self):
        class GH:
            repo='owner/media'
            def request(self,method,path='',**kw):
                if not path: return {'private':False,'default_branch':'main'}
                if path=='/pages': return {'html_url':'https://owner.github.io/media/'}
                return {'tree':[{'type':'blob','size':900_000_000}],'truncated':False}
            def file(self,*a): return None
            def put(self,*a): raise AssertionError('must not upload')
        host=PagesHost(GH(),'https://owner.github.io/media')
        with tempfile.TemporaryDirectory(prefix='test-',dir=Path(__file__).resolve().parent) as t:
            assert Path(t).resolve().parent==Path(__file__).resolve().parent
            p=Path(t)/'v.mp4'; p.write_bytes(b'1234')
            with self.assertRaises(Stop): host.upload(p,'M000032',sha256(p))


if __name__=='__main__': unittest.main()

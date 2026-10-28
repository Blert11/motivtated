"""Validate R2 adapter calls against botocore's real service model, without network."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from publisher.media import R2Host, key_for


@unittest.skipUnless(importlib.util.find_spec('boto3'), 'Install requirements.txt for SDK model tests')
class R2SDKTests(unittest.TestCase):
    def setUp(self):
        import boto3
        from botocore.stub import Stubber
        self.client=boto3.client('s3',endpoint_url='https://example.r2.cloudflarestorage.com',
                                 aws_access_key_id='offline-test',aws_secret_access_key='offline-test',region_name='auto')
        self.stub=Stubber(self.client)
        self.stub.activate(); self.addCleanup(self.stub.deactivate)
        self.host=R2Host(self.client,'test-bucket','https://media.example.com')

    def test_new_object_upload_uses_expected_sdk_parameters(self):
        from botocore.stub import ANY
        digest='a'*64; key=key_for('M000032',digest)
        self.stub.add_client_error('head_object',service_error_code='404',http_status_code=404,
                                   expected_params={'Bucket':'test-bucket','Key':key})
        self.stub.add_response('put_object',{},expected_params={'Bucket':'test-bucket','Key':key,'Body':ANY,
                               'ContentType':'video/mp4','Metadata':{'sha256':digest},'CacheControl':'public, max-age=3600'})
        with tempfile.TemporaryDirectory(prefix='test-',dir=Path(__file__).resolve().parent) as t:
            assert Path(t).resolve().parent==Path(__file__).resolve().parent
            path=Path(t)/'v.mp4'; path.write_bytes(b'1234')
            result=self.host.upload(path,'M000032',digest)
        self.assertEqual(result['url'],'https://media.example.com/'+key)
        self.stub.assert_no_pending_responses()

    def test_cleanup_deletes_only_the_saved_hash(self):
        digest='a'*64; key=key_for('M000032',digest)
        self.stub.add_response('head_object',{'ContentLength':4,'Metadata':{'sha256':digest}},
                               expected_params={'Bucket':'test-bucket','Key':key})
        self.stub.add_response('delete_object',{},expected_params={'Bucket':'test-bucket','Key':key})
        self.host.delete({'provider':'r2','bucket':'test-bucket','key':key,'sha256':digest,'url':'https://media.example.com/'+key})
        self.stub.assert_no_pending_responses()

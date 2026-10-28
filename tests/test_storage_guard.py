import tempfile
import unittest
from pathlib import Path

from publisher.common import Stop
from publisher.media import R2Host


class Client:
    def __init__(self,pages): self.pages=list(pages); self.uploaded=False; self.calls=[]
    def list_objects_v2(self,**kwargs):
        self.calls.append(kwargs)
        value=self.pages.pop(0)
        if isinstance(value,Exception): raise value
        return value
    def head_object(self,**kwargs):
        error=RuntimeError('not found'); error.response={'Error':{'Code':'404'}}; raise error
    def put_object(self,**kwargs): self.uploaded=True


class StorageGuardTests(unittest.TestCase):
    def test_usage_counts_other_prefixes_and_all_pages(self):
        client=Client([{'Contents':[{'Key':'unrelated/file','Size':100}], 'IsTruncated':True,'NextContinuationToken':'next'},
                       {'Contents':[{'Size':200}], 'IsTruncated':False}])
        report=R2Host(client,'bucket','https://media.example.com').usage()
        self.assertEqual(report['storage_bytes'],300)
        self.assertEqual(report['object_count'],2)
        self.assertEqual(client.calls[1]['ContinuationToken'],'next')

    def test_warning_below_hard_application_threshold(self):
        client=Client([{'Contents':[{'Size':1_600_000_000}], 'IsTruncated':False}])
        report=R2Host(client,'bucket','https://media.example.com').usage()
        self.assertTrue(report['warning']); self.assertFalse(report['stop_new_uploads'])

    def test_unmeasurable_storage_stops_upload(self):
        self.check_upload_blocked([RuntimeError('permission denied')])

    def test_projected_storage_stops_upload(self):
        self.check_upload_blocked([{'Contents':[{'Size':1_999_999_999}],'IsTruncated':False}])

    def test_incomplete_pagination_stops_scan(self):
        client=Client([{'Contents':[], 'IsTruncated':True}])
        with self.assertRaises(Stop): R2Host(client,'bucket','https://media.example.com').usage()

    def test_pagination_cycle_is_rejected(self):
        client=Client([{'Contents':[], 'IsTruncated':True,'NextContinuationToken':'same'}]*2)
        with self.assertRaises(Stop): R2Host(client,'bucket','https://media.example.com').usage()

    def check_upload_blocked(self,pages):
        client=Client(pages)
        host=R2Host(client,'bucket','https://media.example.com')
        with tempfile.TemporaryDirectory(prefix='test-',dir=Path(__file__).resolve().parent) as t:
            assert Path(t).resolve().parent==Path(__file__).resolve().parent
            path=Path(t)/'clip.mp4'; path.write_bytes(b'1234')
            with self.assertRaises(Stop): host.upload(path,'M000032','a'*64)
        self.assertFalse(client.uploaded)


if __name__=='__main__': unittest.main()

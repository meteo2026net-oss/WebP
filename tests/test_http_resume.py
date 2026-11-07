import hashlib, tempfile, unittest, urllib.error
from pathlib import Path
from urllib.request import Request
from ecmwf_collector.sources.http_resume import download_resumable, download_resumable_with_retry

class Response:
    def __init__(self,payload,status,headers,fail_after=None):
        self.payload,self.status,self.headers=payload,status,headers; self.offset=0; self.fail_after=fail_after
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self,size=-1):
        if self.fail_after is not None and self.offset>=self.fail_after: raise OSError("simulated connection drop")
        if self.offset>=len(self.payload): return b""
        end=min(self.offset+size,len(self.payload))
        if self.fail_after is not None: end=min(end,self.fail_after)
        data=self.payload[self.offset:end]; self.offset=end; return data

class HttpResumeTests(unittest.TestCase):
    def test_resume_uses_range_and_validator(self):
        payload=b"GRIB"+b"weather-data"*100+b"7777"
        with tempfile.TemporaryDirectory() as tmp:
            part=Path(tmp)/"file.part"
            def first(req,timeout):
                self.assertIsInstance(req,Request)
                return Response(payload,200,{"ETag":'"v1"',"Content-Length":str(len(payload))},211)
            with self.assertRaises(OSError): download_resumable("https://example.test/file",part,timeout=5,opener=first)
            offset=part.stat().st_size
            def second(req,timeout):
                self.assertEqual(req.get_header("Range"),f"bytes={offset}-")
                self.assertEqual(req.get_header("If-range"),'"v1"')
                return Response(payload[offset:],206,{"Content-Range":f"bytes {offset}-{len(payload)-1}/{len(payload)}","ETag":'"v1"'})
            digest=download_resumable("https://example.test/file",part,timeout=5,opener=second)
            self.assertEqual(part.read_bytes(),payload); self.assertEqual(digest,hashlib.sha256(payload).hexdigest())

    def test_server_ignoring_range_restarts_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            part=Path(tmp)/"file.part"; part.write_bytes(b"old")
            part.with_suffix(".part.resume.json").write_text('{"url":"https://example.test/file","etag":"v1"}')
            response=Response(b"complete",200,{"Content-Length":"8"})
            download_resumable("https://example.test/file",part,timeout=5,opener=lambda req,timeout:response)
            self.assertEqual(part.read_bytes(),b"complete")

    def test_connection_drop_retries_and_resumes(self):
        payload=b"GRIB"+b"retry-me"*100+b"7777"; calls=[]; delays=[]
        with tempfile.TemporaryDirectory() as tmp:
            part=Path(tmp)/"retry.part"
            def opener(req,timeout):
                calls.append(req)
                if len(calls)==1: return Response(payload,200,{"ETag":'"stable"'},120)
                self.assertEqual(req.get_header("Range"),"bytes=120-")
                return Response(payload[120:],206,{"Content-Range":f"bytes 120-{len(payload)-1}/{len(payload)}","ETag":'"stable"'})
            digest=download_resumable_with_retry("https://example.test/retry",part,timeout=5,opener=opener,sleeper=delays.append)
            self.assertEqual(len(calls),2); self.assertEqual(delays,[1.0])
            self.assertEqual(part.read_bytes(),payload); self.assertEqual(digest,hashlib.sha256(payload).hexdigest())

    def test_transient_http_error_retries_but_forbidden_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            part=Path(tmp)/"retry.part"; calls=[]
            def unavailable(req,timeout):
                calls.append(req); raise urllib.error.HTTPError(req.full_url,503,"busy",{},None)
            with self.assertRaises(urllib.error.HTTPError):
                download_resumable_with_retry("https://example.test/retry",part,timeout=1,opener=unavailable,max_attempts=3,sleeper=lambda d:None)
            self.assertEqual(len(calls),3); calls.clear()
            def forbidden(req,timeout):
                calls.append(req); raise urllib.error.HTTPError(req.full_url,403,"forbidden",{},None)
            with self.assertRaises(urllib.error.HTTPError):
                download_resumable_with_retry("https://example.test/retry",part,timeout=1,opener=forbidden,max_attempts=3,sleeper=lambda d:None)
            self.assertEqual(len(calls),1)

if __name__=="__main__": unittest.main()

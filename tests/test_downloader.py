import hashlib
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from pathlib import Path

from ecmwf_collector.connection import ConnectionSettings, open_session
from ecmwf_collector.downloader import DownloadManager, Filters, build_plan
from ecmwf_collector.state import StateStore
from tests.fakes import FakeServerState, make_factory
from tests.test_naming_inspect_state import grib2

FP = "/20261027/FPD10270000102703001"
FS = "/20261027/FSD10271200102712011"
AN = "/20261027/AND10270000102700001"
FM = "/20261027/FMD10270000102706001"
ODD = "/20261027/weird.txt"


def settings(**kw):
    base = dict(host="h", port=21, username="u", password="secret-pass", protocol="ftps", timeout=5, max_retries=3)
    base.update(kw)
    return ConnectionSettings(**base)


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "downloads"
        self.state = StateStore(Path(self.tmp.name) / "state.db")
        self.sleeps = []

    def tearDown(self):
        self.state.close()
        self.tmp.cleanup()

    def server(self, files, **kw):
        return FakeServerState(files=files, **kw)

    def plan(self, st, filters=Filters()):
        with open_session(settings(), make_factory(st), self.sleeps.append) as s:
            return build_plan(s, self.root, self.state, filters)

    def manager(self, st, **kw):
        kw.setdefault("blocksize", 1024)
        kw.setdefault("progress_interval", 0)
        return DownloadManager(settings(), self.state, factory=make_factory(st), sleep=self.sleeps.append, **kw)

    def local(self, name):
        return self.root / "2026-10-27" / "original_files" / name

    def test_download_integrity_and_state(self):
        data = grib2(5000)
        st = self.server({FP: data})
        plan = self.plan(st)
        res = self.manager(st).run(plan.to_download)
        self.assertEqual((res.downloaded, res.failed, res.invalid), (1, 0, 0))
        f = self.local("FPD10270000102703001")
        self.assertEqual(f.read_bytes(), data)
        self.assertFalse(f.with_name(f.name + ".part").exists())
        rec = self.state.get(FP)
        self.assertEqual((rec.status, rec.sha256, rec.local_size, rec.detected_type, rec.validation),
                         ("complete", hashlib.sha256(data).hexdigest(), len(data), "GRIB2", "ok"))
        ts = datetime.fromisoformat(rec.downloaded_at)
        self.assertEqual(ts.utcoffset().total_seconds(), 0)

    def test_repeat_run_skips_completed(self):
        st = self.server({FP: grib2(3000), FS: grib2(2000)})
        self.manager(st).run(self.plan(st).to_download)
        calls = len(st.retr_calls)
        plan2 = self.plan(st)
        self.assertEqual({i.action for i in plan2.items}, {"skip"})
        res = self.manager(st).run(plan2.items)
        self.assertEqual(res.downloaded, 0)
        self.assertEqual(len(st.retr_calls), calls)

    def test_resume_after_connection_drop(self):
        data = grib2(10000)
        st = self.server({FP: data}, drop_after_bytes=[3000])
        res = self.manager(st).run(self.plan(st).to_download)
        self.assertEqual(res.downloaded, 1)
        self.assertEqual(self.local("FPD10270000102703001").read_bytes(), data)
        self.assertEqual(self.state.get(FP).sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(st.retr_calls[0][1], None)
        self.assertGreater(st.retr_calls[1][1], 0)      # الاستكمال بإزاحة REST
        self.assertEqual(self.sleeps[-1:], [1.0])       # تأخير قبل إعادة المحاولة

    def test_rest_unsupported_restarts_from_zero(self):
        data = grib2(10000)
        st = self.server({FP: data}, drop_after_bytes=[3000], rest_supported=False)
        res = self.manager(st).run(self.plan(st).to_download)
        self.assertEqual(res.downloaded, 1)
        self.assertEqual(self.local("FPD10270000102703001").read_bytes(), data)
        self.assertEqual(self.state.get(FP).sha256, hashlib.sha256(data).hexdigest())

    def test_empty_file_flagged_invalid(self):
        st = self.server({FP: b""})
        res = self.manager(st).run(self.plan(st).to_download)
        self.assertEqual((res.downloaded, res.invalid), (0, 1))
        self.assertFalse(self.local("FPD10270000102703001").exists())
        self.assertTrue(self.local("FPD10270000102703001.invalid").exists())
        self.assertEqual(self.state.get(FP).status, "invalid")

    def test_corrupt_grib_not_stored_as_final(self):
        st = self.server({FP: grib2(500)[:-9]})
        res = self.manager(st).run(self.plan(st).to_download)
        self.assertEqual(res.invalid, 1)
        self.assertFalse(self.local("FPD10270000102703001").exists())

    def test_unknown_format_kept_but_unverified(self):
        st = self.server({ODD: b"a,b\n1,2\n"})
        res = self.manager(st).run(self.plan(st).to_download)
        self.assertEqual(res.downloaded, 1)
        rec = self.state.get(ODD)
        self.assertEqual(rec.detected_type, "unknown")
        self.assertTrue(rec.validation.startswith("unverified"))

    def test_disk_space_guard(self):
        st = self.server({FP: grib2(1000)})
        res = self.manager(st, min_free_bytes=10 ** 18).run(self.plan(st).to_download)
        self.assertTrue(res.disk_full)
        self.assertEqual(res.downloaded, 0)
        self.assertEqual(st.retr_calls, [])
        self.assertFalse(self.local("FPD10270000102703001").exists())

    def test_source_still_being_written_is_retried(self):
        data = grib2(3000)
        st = self.server({FP: data}, size_sequence={FP: [len(data), len(data) + 500, len(data), len(data)]})
        res = self.manager(st).run(self.plan(st).to_download)
        self.assertEqual(res.downloaded, 1)
        self.assertEqual(len(st.retr_calls), 2)
        self.assertEqual(self.local("FPD10270000102703001").read_bytes(), data)

    def test_permanent_failure_marks_failed(self):
        st = self.server({FP: grib2(3000)}, drop_after_bytes=[0] * 50)
        res = self.manager(st).run(self.plan(st).to_download)
        self.assertEqual((res.downloaded, res.failed), (0, 1))
        self.assertEqual(self.state.get(FP).status, "failed")
        self.assertEqual(self.sleeps, [1.0, 2.0])
        self.assertFalse(self.local("FPD10270000102703001").exists())

    def test_safe_stop_leaves_part_then_resumes(self):
        data = grib2(10000)
        st = self.server({FP: data})
        holder = {}

        def on_progress(snap):
            if snap.bytes_done >= 3000:
                holder["m"].stop()

        m = self.manager(st, on_progress=on_progress)
        holder["m"] = m
        res = m.run(self.plan(st).to_download)
        self.assertTrue(res.stopped)
        f = self.local("FPD10270000102703001")
        part = f.with_name(f.name + ".part")
        self.assertTrue(part.exists())
        self.assertFalse(f.exists())
        part_size = part.stat().st_size
        plan2 = self.plan(st)
        self.assertEqual(plan2.items[0].action, "resume")
        res2 = self.manager(st).run(plan2.to_download)
        self.assertEqual(res2.downloaded, 1)
        self.assertEqual(st.retr_calls[-1][1], part_size)
        self.assertEqual(f.read_bytes(), data)
        self.assertEqual(self.state.get(FP).sha256, hashlib.sha256(data).hexdigest())

    def test_pause_then_resume(self):
        data = grib2(8000)
        st = self.server({FP: data})
        holder = {"paused_once": False}

        def on_progress(snap):
            if snap.bytes_done >= 2000 and not holder["paused_once"]:
                holder["paused_once"] = True
                holder["m"].pause()
                import threading
                threading.Timer(0.3, holder["m"].resume).start()

        m = self.manager(st, on_progress=on_progress)
        holder["m"] = m
        res = m.run(self.plan(st).to_download)
        self.assertEqual(res.downloaded, 1)
        self.assertEqual(self.local("FPD10270000102703001").read_bytes(), data)

    def test_filters_and_unknown_names(self):
        st = self.server({FP: grib2(100), FS: grib2(100), AN: grib2(100), FM: grib2(100), ODD: b"x"})
        names = lambda p: sorted(i.name for i in p.items)
        p = self.plan(st, Filters(kinds=frozenset({"FP", "FS"}), cycles=frozenset({"12"}), include_unknown=False))
        self.assertEqual(names(p), ["FSD10271200102712011"])
        p = self.plan(st, Filters(kinds=frozenset({"FP"}), cycles=frozenset({"00"})))
        self.assertEqual(names(p), ["FPD10270000102703001", "weird.txt"])  # المجهول لا يُهمل بصمت

    def test_parallel_downloads(self):
        files = {FP: grib2(4000), FS: grib2(4000), AN: grib2(4000), FM: grib2(4000)}
        st = self.server(files)
        res = self.manager(st, max_parallel=3).run(self.plan(st).to_download)
        self.assertEqual(res.downloaded, 4)
        for path, data in files.items():
            self.assertEqual(self.local(path.split("/")[-1]).read_bytes(), data)

    def test_worker_session_close_error_does_not_escape_cleanup(self):
        st = self.server({FP: grib2(100)})
        from ecmwf_collector.downloader import _Worker
        manager = self.manager(st)
        worker = _Worker(manager)

        class BrokenSession:
            def close(self):
                raise RuntimeError("socket close failed")

        worker.session = BrokenSession()
        worker.cwd = "/20261027"
        with self.assertLogs("ecmwf_collector.downloader", level="ERROR"):
            worker.close()

        self.assertIsNone(worker.session)
        self.assertIsNone(worker.cwd)

    def test_unexpected_worker_exception_is_reported_to_run_result(self):
        st = self.server({FP: grib2(100)})
        plan = self.plan(st)
        manager = self.manager(st)
        with patch("ecmwf_collector.downloader._Worker.process",
                   side_effect=RuntimeError("unexpected worker failure")):
            result = manager.run(plan.to_download)

        self.assertEqual(result.failed, 1)
        self.assertIn("FPD10270000102703001", result.errors[0])
        self.assertIn("RuntimeError", result.fatal_message)
        self.assertEqual(self.state.get(FP).status, "failed")

    def test_bad_password_is_fatal_and_not_retried(self):
        st = self.server({FP: grib2(100)})
        plan = self.plan(st)
        bad = DownloadManager(settings(password="wrong"), self.state, factory=make_factory(st),
                              sleep=self.sleeps.append, progress_interval=0)
        res = bad.run(plan.to_download)
        self.assertTrue(res.auth_failed)
        self.assertEqual(res.downloaded, 0)


if __name__ == "__main__":
    unittest.main()

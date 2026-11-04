import ftplib
import socket
import unittest

from ecmwf_collector.connection import (AuthenticationError, ConnectionSettings, NetworkError,
                                        PlainFtpNotAllowedError, TlsError, open_session,
                                        test_connection as run_connection_test)
from tests.fakes import FakeServerState, make_factory


def settings(**kw):
    base = dict(host="diss.ecmwf.int", port=21, username="wmo_xx", password="secret-pass",
                passive=True, protocol="auto", allow_plain_ftp=False, timeout=7, max_retries=3)
    base.update(kw)
    return ConnectionSettings(**base)


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        self.sleep = self.sleeps.append

    def open(self, state, **kw):
        return open_session(settings(**kw), make_factory(state), self.sleep)

    def test_auto_prefers_tls_and_sets_options(self):
        st = FakeServerState()
        with self.open(st) as s:
            self.assertTrue(s.use_tls)
            self.assertTrue(s.ftp.prot)
            self.assertTrue(s.ftp.pasv)
            self.assertEqual(s.ftp.encoding, "utf-8")
        self.assertIn(7, st.timeouts)

    def test_passive_off_respected(self):
        with self.open(FakeServerState(), passive=False) as s:
            self.assertFalse(s.ftp.pasv)

    def test_auto_refuses_plain_when_not_allowed(self):
        st = FakeServerState(tls_supported=False)
        with self.assertRaises(PlainFtpNotAllowedError):
            self.open(st)
        self.assertEqual(st.login_calls, 0)  # لم تُرسل كلمة المرور

    def test_auto_plain_when_allowed(self):
        with self.open(FakeServerState(tls_supported=False), allow_plain_ftp=True) as s:
            self.assertFalse(s.use_tls)

    def test_explicit_plain_ftp(self):
        with self.open(FakeServerState(), protocol="ftp") as s:
            self.assertFalse(s.use_tls)

    def test_bad_password_no_retry(self):
        st = FakeServerState(valid_password="other")
        with self.assertRaises(AuthenticationError):
            self.open(st)
        self.assertEqual(st.login_calls, 1)
        self.assertEqual(self.sleeps, [])

    def test_transient_failure_retries_with_backoff(self):
        st = FakeServerState(fail_connect_times=2, connect_exception=socket.timeout("t"))
        with self.open(st, protocol="ftps") as s:
            self.assertTrue(s.use_tls)
        self.assertEqual(self.sleeps, [1.0, 2.0])

    def test_permanent_network_failure(self):
        st = FakeServerState(fail_connect_times=99, connect_exception=ConnectionRefusedError("no"))
        with self.assertRaises(NetworkError):
            self.open(st, protocol="ftps")
        self.assertEqual(self.sleeps, [1.0, 2.0])  # 3 محاولات، تأخير متزايد

    def test_temp_error_421_is_retried(self):
        st = FakeServerState(fail_connect_times=1, connect_exception=ftplib.error_temp("421 busy"))
        with self.open(st, protocol="ftps"):
            pass
        self.assertEqual(self.sleeps, [1.0])

    def test_cert_error_never_downgrades(self):
        st = FakeServerState(cert_error=True)
        with self.assertRaises(TlsError):
            self.open(st, allow_plain_ftp=True)
        self.assertEqual(st.login_calls, 0)

    def test_test_connection_ok(self):
        r = run_connection_test(settings(), make_factory(FakeServerState()), self.sleep)
        self.assertTrue(r.ok)
        self.assertIn("FTPS", r.protocol)
        self.assertEqual(r.cwd, "/")

    def test_test_connection_failure_messages_are_arabic_and_hide_password(self):
        r = run_connection_test(settings(password="wrong-pw"), make_factory(FakeServerState()), self.sleep)
        self.assertFalse(r.ok)
        self.assertEqual(r.kind, "auth")
        self.assertIn("كلمة مرور", r.message_ar)
        self.assertNotIn("wrong-pw", r.message_ar)

    def test_test_connection_network_failure(self):
        st = FakeServerState(fail_connect_times=99, connect_exception=socket.gaierror("dns"))
        r = run_connection_test(settings(protocol="ftps"), make_factory(st), self.sleep)
        self.assertFalse(r.ok)
        self.assertEqual(r.kind, "network")

    def test_password_not_in_repr(self):
        self.assertNotIn("secret-pass", repr(settings()))


if __name__ == "__main__":
    unittest.main()

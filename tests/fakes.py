"""خادم FTP وهمي للاختبارات. لا اتصال شبكي ولا حساب ECMWF حقيقي."""
import ftplib
import posixpath
import socket
import ssl
from collections import deque


class FakeServerState:
    def __init__(self, tree=None, valid_password="secret-pass", tls_supported=True,
                 fail_connect_times=0, connect_exception=None, mlsd_supported=True,
                 cert_error=False, list_lines=None, files=None, rest_supported=True,
                 drop_after_bytes=None, size_sequence=None):
        self.files = files or {}          # {"/folder/name": bytes}
        self.rest_supported = rest_supported
        self.drop_after_bytes = list(drop_after_bytes or [])   # قطع الاتصال بعد n بايت في كل نداء
        self.size_sequence = {k: deque(v) for k, v in (size_sequence or {}).items()}
        self.retr_calls = []              # [(path, rest)]
        self.tree = tree or {}
        if self.files and not tree:
            self.tree = {"/": []}
            for path, data in self.files.items():
                folder, name = posixpath.split(path)
                if folder not in self.tree:
                    self.tree[folder] = []
                    self.tree["/"].append((folder.strip("/"), {"type": "dir"}))
                self.tree[folder].append((name, {"type": "file", "size": str(len(data))}))
        self.valid_password = valid_password
        self.tls_supported = tls_supported
        self.fail_connect_times = fail_connect_times
        self.connect_exception = connect_exception or socket.timeout("timed out")
        self.mlsd_supported = mlsd_supported
        self.cert_error = cert_error
        self.list_lines = list_lines or {}
        self.connect_calls = 0
        self.login_calls = 0
        self.instances = []
        self.timeouts = []


class FakeFtp:
    def __init__(self, state: FakeServerState, use_tls: bool):
        self.state, self.use_tls = state, use_tls
        self.encoding = "latin-1"
        self.pasv = None
        self.cwd_path = "/"
        self.prot = False
        self.closed = False
        state.instances.append(self)

    def connect(self, host, port, timeout):
        self.state.connect_calls += 1
        self.state.timeouts.append(timeout)
        if self.state.cert_error and self.use_tls:
            raise ssl.SSLCertVerificationError(1, "certificate verify failed")
        if self.state.connect_calls <= self.state.fail_connect_times:
            raise self.state.connect_exception
        return "220 Fake DISS ready"

    def auth(self):
        if not self.state.tls_supported:
            raise ftplib.error_perm("534 TLS not available")

    def login(self, user, password):
        self.state.login_calls += 1
        if password != self.state.valid_password:
            raise ftplib.error_perm("530 Login incorrect.")

    def prot_p(self):
        self.prot = True

    def set_pasv(self, flag):
        self.pasv = flag

    def pwd(self):
        return "/"

    def cwd(self, path):
        self.cwd_path = path

    def mlsd(self, path, facts=None):
        if not self.state.mlsd_supported:
            raise ftplib.error_perm("500 MLSD not understood")
        items = self.state.tree.get(path)
        if items is None:
            raise ftplib.error_perm("550 No such directory")
        yield from items

    def retrlines(self, cmd, callback):
        for line in self.state.list_lines.get(self.cwd_path, []):
            callback(line)

    def voidcmd(self, cmd):
        return "200 ok"

    def size(self, name):
        path = posixpath.join(self.cwd_path, name)
        if path not in self.state.files:
            raise ftplib.error_perm("550 No such file")
        seq = self.state.size_sequence.get(path)
        if seq:
            return seq.popleft()
        return len(self.state.files[path])

    def retrbinary(self, cmd, callback, blocksize=8192, rest=None):
        name = cmd[5:]
        path = posixpath.join(self.cwd_path, name)
        if path not in self.state.files:
            raise ftplib.error_perm("550 No such file")
        self.state.retr_calls.append((path, rest))
        if rest and not self.state.rest_supported:
            raise ftplib.error_perm("502 REST not implemented")
        data, pos, sent = self.state.files[path], rest or 0, 0
        while pos < len(data):
            limit = self.state.drop_after_bytes[0] if self.state.drop_after_bytes else None
            if limit is not None and sent >= limit:
                self.state.drop_after_bytes.pop(0)
                raise ConnectionResetError("connection dropped")
            chunk = data[pos:pos + blocksize]
            callback(chunk)
            pos += len(chunk)
            sent += len(chunk)

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True


def make_factory(state: FakeServerState):
    def factory(use_tls, timeout):
        return FakeFtp(state, use_tls)
    return factory

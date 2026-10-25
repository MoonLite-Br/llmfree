"""A stand-in for ``curl_cffi.requests`` (the sandbox cannot install the real one).

It follows the documented API surface llmf relies on: ``request(method, url, headers=, data=,
timeout=, proxies=, impersonate=, stream=True)`` -> object with ``status_code``, ``headers``,
``iter_content(chunk_size=None)``, ``close()``; failures raise exceptions defined in a module whose
name starts with ``curl_cffi``.
"""
import sys
import types
import urllib.error
import urllib.request

CALLS = []


def install(raise_kind=None, unusable=False):
    pkg = types.ModuleType("curl_cffi")
    pkg.__version__ = "0.0-test"
    mod = types.ModuleType("curl_cffi.requests")
    exc = types.ModuleType("curl_cffi.requests.exceptions")

    class RequestException(Exception):
        pass

    class Timeout(RequestException):
        code = 28

    exc.RequestException, exc.Timeout = RequestException, Timeout
    for c in (RequestException, Timeout):
        c.__module__ = "curl_cffi.requests.exceptions"

    class Resp:
        def __init__(self, r):
            self._r = r
            self.status_code = r.status
            self.headers = dict(r.headers)

        def iter_content(self, chunk_size=None):
            while True:
                c = self._r.read1(4096) if hasattr(self._r, "read1") else self._r.read(4096)
                if not c:
                    return
                yield c

        def close(self):
            self._r.close()

    class ErrResp(Resp):
        def __init__(self, e):
            self._r = e
            self.status_code = e.code
            self.headers = dict(e.headers)

    def request(method, url, **kw):
        CALLS.append((method, url, kw))
        if unusable:
            raise TypeError("unexpected keyword argument")
        if raise_kind == "timeout":
            raise Timeout("Operation timed out")
        if raise_kind == "network":
            raise RequestException("Could not resolve host")
        req = urllib.request.Request(url, data=kw.get("data"), headers=kw.get("headers") or {}, method=method)
        try:
            return Resp(urllib.request.urlopen(req, timeout=kw.get("timeout") or 10))
        except urllib.error.HTTPError as e:
            return ErrResp(e)

    mod.request = request
    pkg.requests = mod
    sys.modules.update({"curl_cffi": pkg, "curl_cffi.requests": mod, "curl_cffi.requests.exceptions": exc})
    CALLS.clear()


def uninstall():
    for k in [k for k in sys.modules if k == "curl_cffi" or k.startswith("curl_cffi.")]:
        del sys.modules[k]

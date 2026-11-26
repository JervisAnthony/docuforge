import threading
import time
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from docuforge.ops import batch_transport as transport
from docuforge.ops import deployment_smoke
from docuforge.ops.batch_smoke import TOKEN_HEADER, Lifecycle
from tests.ops.batch_support import API, TOKEN, Clock


@contextmanager
def endpoint(
    monkeypatch,
    *,
    status=302,
    location="/redirected",
    payload=b"redirect",
    delay=0,
    response_headers=None,
    header_delay=0,
):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append((self.command, self.path, self.headers.get(TOKEN_HEADER)))
            if self.headers.get("Content-Length"):
                self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(status)
            self.send_header("Location", location)
            self.send_header("Content-Length", str(len(payload)))
            for key, value in (response_headers or {}).items():
                self.send_header(key, value)
            if header_delay:
                time.sleep(header_delay)
            self.end_headers()
            try:
                if delay:
                    for byte in payload:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(delay)
                else:
                    self.wfile.write(payload)
            except (OSError, ConnectionError):
                pass

        do_POST = do_DELETE = do_GET

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.daemon_threads = True
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        thread.start()

        def connection(host, port, *, timeout):
            assert host == "api.example.com" and port is None
            return HTTPConnection("127.0.0.1", server.server_port, timeout=timeout)

        # Exercise the actual default transport against an owned listener. Only TLS
        # connection establishment is replaced; there is no fake requester/redirect logic.
        monkeypatch.setattr(transport, "HTTPSConnection", connection)
        try:
            yield calls
        finally:
            server.shutdown()
            thread.join(timeout=2)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "location", ["https://api.example.com/redirected", "https://elsewhere.invalid/redirected"]
)
@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_default_transport_never_follows_any_redirect(monkeypatch, status, location, method):
    with endpoint(monkeypatch, status=status, location=location) as calls:
        result = transport.request_batch_http(
            method,
            API + "/owned",
            headers={TOKEN_HEADER: TOKEN},
            body=b"synthetic" if method == "POST" else None,
            timeout=1,
        )
    assert result.status_code == status
    assert calls == [(method, "/owned", TOKEN)]


def test_lifecycle_names_redirect_failure_from_actual_default_transport(monkeypatch):
    clock = Clock()
    with endpoint(monkeypatch) as calls:
        runner = Lifecycle(API, clock=clock, sleeper=clock.sleep)
        with pytest.raises(Exception, match="redirect_refused") as error:
            runner.request("GET", "/owned", 2, token=TOKEN)
    assert TOKEN not in str(error.value)
    assert calls == [("GET", "/owned", TOKEN)]


def test_default_reader_bounds_body_and_closes_connection(monkeypatch):
    monkeypatch.setattr(deployment_smoke, "MAX_RESPONSE_BYTES", 32)
    with (
        endpoint(monkeypatch, status=200, payload=b"x" * 100) as calls,
        pytest.raises(RuntimeError, match="batch_transport_failed") as error,
    ):
        transport.request_batch_http(
            "GET", API + "/owned", timeout=1, headers={TOKEN_HEADER: TOKEN}
        )
    assert TOKEN not in str(error.value) and len(calls) == 1


def test_trickling_body_obeys_total_exchange_deadline(monkeypatch):
    started = time.monotonic()
    with (
        endpoint(monkeypatch, status=200, payload=b"x" * 30, delay=0.01),
        pytest.raises(RuntimeError, match="batch_transport_failed"),
    ):
        transport.request_batch_http("GET", API + "/owned", timeout=0.05)
    assert time.monotonic() - started < 2


def test_header_read_is_bounded_by_exchange_deadline(monkeypatch):
    started = time.monotonic()
    with (
        endpoint(monkeypatch, status=200, header_delay=0.2),
        pytest.raises(RuntimeError, match="batch_transport_failed"),
    ):
        transport.request_batch_http("GET", API + "/owned", timeout=0.05)
    assert time.monotonic() - started < 2


@pytest.mark.parametrize("read_failure", ["oversize", "timeout"])
def test_acceptance_read_failure_retains_safe_headers_for_owned_cleanup(monkeypatch, read_failure):
    from tests.ops.batch_support import IDENTITY

    monkeypatch.setattr(deployment_smoke, "MAX_RESPONSE_BYTES", 8)
    with endpoint(
        monkeypatch,
        status=202,
        payload=b"x" * 30,
        delay=0.01 if read_failure == "timeout" else 0,
        response_headers={TOKEN_HEADER: TOKEN},
    ) as calls:
        result = transport.request_batch_http("POST", API + "/owned", timeout=0.05)
    assert result.status_code == 202 and result.headers[TOKEN_HEADER.lower()] == TOKEN
    assert result.body_error == (
        "transport_failed" if read_failure == "timeout" else "response_too_large"
    )
    assert len(calls) == 1 and TOKEN not in repr(result) and IDENTITY not in repr(result)


@pytest.mark.parametrize(
    "url", ["http://api.example.com/owned", API + "/owned?token=x", API + "/owned#fragment"]
)
def test_default_transport_rejects_unsafe_urls_before_connection(monkeypatch, url):
    def forbidden(*args, **kwargs):
        pytest.fail("must reject before connecting")

    monkeypatch.setattr(transport, "HTTPSConnection", forbidden)
    with pytest.raises(RuntimeError, match="batch_transport_failed"):
        transport.request_batch_http("GET", url, timeout=1)

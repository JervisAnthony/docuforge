"""One bounded HTTPS exchange; redirects are returned, never followed.

Connections are direct (proxy environment variables are intentionally ignored).
The response is fully consumed and closed before returning, including downloads.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from http.client import HTTPSConnection
from urllib.parse import urlsplit

from docuforge.ops.deployment_smoke import (
    DeploymentSmokeError,
    HttpResponse,
    _bounded_response_read,
)
from docuforge.ops.release_identity import normalize_origin


@dataclass(frozen=True, slots=True, repr=False)
class BatchHttpResponse(HttpResponse):
    """Retain an acceptance grant even if reading its body fails."""

    body_error: str | None = None

    def __repr__(self):
        return "BatchHttpResponse(private response omitted)"


def request_batch_http(method, url, *, headers=None, body=None, timeout):
    """Never replay bodies or forward capabilities, even on same-origin 3xx."""
    connection = None
    timer = None
    watched_sockets = []
    try:
        parts = urlsplit(url)
        normalize_origin(f"{parts.scheme}://{parts.netloc}", label="API")
        if parts.fragment or parts.query or not parts.path.startswith("/"):
            raise ValueError
        deadline = time.monotonic() + timeout
        connection = HTTPSConnection(parts.hostname, parts.port, timeout=timeout)

        def expire():
            # Abort only this client's exchange, including trickling headers/TLS.
            for active in [connection.sock, *watched_sockets]:
                if active is not None:
                    try:
                        active.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        connection.connect()
        sock = connection.sock
        watched_sockets.append(sock)

        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise TimeoutError
            sock.settimeout(value)
            return value

        remaining()
        connection.request(method, parts.path, body=body, headers=dict(headers or {}))
        remaining()
        with connection.getresponse() as response:

            class Reader:
                def read(self, limit):
                    chunks = []
                    size = 0
                    while size < limit:
                        if response.isclosed():
                            break
                        remaining()
                        chunk = response.read1(min(65536, limit - size))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        size += len(chunk)
                    if time.monotonic() >= deadline:
                        raise TimeoutError
                    return b"".join(chunks)

            response_headers = {}
            for key, value in response.getheaders():
                key = key.lower()
                response_headers[key] = (
                    response_headers[key] + "," + value if key in response_headers else value
                )
            try:
                payload = _bounded_response_read(Reader())
            except Exception as error:
                if response.status == 202 and method == "POST":
                    return BatchHttpResponse(
                        response.status,
                        response_headers,
                        b"",
                        "response_too_large"
                        if isinstance(error, DeploymentSmokeError)
                        else "transport_failed",
                    )
                raise
            return BatchHttpResponse(response.status, response_headers, payload)
    except Exception:  # noqa: BLE001 - no private transport diagnostics may escape
        # Never chain exceptions containing URLs, headers, bodies or credentials.
        raise RuntimeError("batch_transport_failed") from None
    finally:
        if timer is not None:
            timer.cancel()
        if connection is not None:
            connection.close()

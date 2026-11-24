"""Run the four additional public checks through a disposable real local API.

The CLI always uses the installed LibreOffice/Tesseract engines. Tests can inject
an app, but never count that evidence as real production-image execution.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from contextlib import contextmanager
from http.client import HTTPConnection
from urllib.parse import urlsplit

import uvicorn

from docuforge.api import ApiSettings, create_app
from docuforge.ops.deployment_smoke import (
    OFFICE_OCR_CHECKS,
    DeploymentSmokeError,
    HttpResponse,
    ProductionSmokeRunner,
    _bounded_response_read,
)

_API_ORIGIN = "https://api.docuforge.invalid"
_PATHS = frozenset("/api/v1/" + name.replace("-", "/", 1) for name in OFFICE_OCR_CHECKS)


@contextmanager
def _local_api(app):
    """Own an ephemeral loopback listener and shut it down even on check failure."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                log_config=None,
                access_log=False,
                log_level="critical",
                timeout_graceful_shutdown=5,
            )
        )
        errors = []

        def serve():
            try:
                server.run(sockets=[listener])
            except (Exception, SystemExit):  # noqa: BLE001 - never print private server diagnostics
                errors.append(True)

        thread = threading.Thread(target=serve, name="docuforge-office-ocr-api", daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if errors or not thread.is_alive() or time.monotonic() >= deadline:
                    raise DeploymentSmokeError("local integration API did not start")
                time.sleep(0.01)
            yield port
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                server.force_exit = True
                thread.join(timeout=5)
            if thread.is_alive():
                raise DeploymentSmokeError("local integration API did not stop")


def run_office_ocr_integration(*, app=None) -> tuple[str, ...]:
    """Exercise the actual HTTP routes and converters, without public traffic."""
    application = app if app is not None else create_app(ApiSettings(docs_enabled=False))
    with _local_api(application) as port:

        def requester(method, url, *, headers=None, body=None, timeout):
            parts = urlsplit(url)
            if (
                method != "POST"
                or f"{parts.scheme}://{parts.netloc}" != _API_ORIGIN
                or parts.path not in _PATHS
                or parts.query
                or parts.fragment
            ):
                raise DeploymentSmokeError("unexpected integration request")
            # Connect directly to our own listener, ignoring proxy environment variables.
            connection = HTTPConnection("127.0.0.1", port, timeout=timeout)
            try:
                connection.request(method, parts.path, body=body, headers=dict(headers or {}))
                with connection.getresponse() as response:
                    return HttpResponse(
                        response.status,
                        {key.lower(): value for key, value in response.getheaders()},
                        _bounded_response_read(response),
                    )
            finally:
                connection.close()

        runner = ProductionSmokeRunner(
            frontend_url="https://frontend.docuforge.invalid",
            api_url=_API_ORIGIN,
            timeout=180,
            requester=requester,
        )
        passed = []
        for name in OFFICE_OCR_CHECKS:
            try:
                getattr(runner, f"_check_{name.replace('-', '_')}")()
            except DeploymentSmokeError as error:
                raise DeploymentSmokeError(f"{name}: {error}") from error
            except Exception as error:
                raise DeploymentSmokeError(
                    f"{name}: invalid response or transport failure"
                ) from error
            passed.append(name)
        return tuple(passed)


def main() -> int:
    try:
        checks = run_office_ocr_integration()
    except DeploymentSmokeError as error:
        print(f"Office/OCR API integration FAIL: {error}", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - safe CLI boundary, including startup/cleanup failures
        print("Office/OCR API integration FAIL: local runtime unavailable", file=sys.stderr)
        return 1
    print(f"Office/OCR API integration PASS: {len(checks)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

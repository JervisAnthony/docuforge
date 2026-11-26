"""Disposable local four-batch integration; CLI uses real production engines.

This injected transport is deliberately separate from the strict public transport.
App-injected tests use image converters and Office doubles, not engine evidence.
"""

from __future__ import annotations

from http.client import HTTPConnection
from urllib.parse import urlsplit

from docuforge.api import ApiSettings, create_app
from docuforge.ops.batch_smoke import BATCH_CHECKS, CREATION_PATHS, Lifecycle, Timing, location_id
from docuforge.ops.batch_summary import valid_report
from docuforge.ops.deployment_smoke import HttpResponse, _bounded_response_read
from docuforge.ops.office_ocr_integration import _local_api

ORIGIN = "https://batch.docuforge.invalid"


def run_batch_integration(*, app=None):
    application = app if app is not None else create_app(ApiSettings(docs_enabled=False))
    with _local_api(application) as port:

        def requester(method, url, *, headers=None, body=None, timeout):
            parts = urlsplit(url)
            base = parts.path.removesuffix("/download").removesuffix("/cancel")
            if (
                f"{parts.scheme}://{parts.netloc}" != ORIGIN
                or parts.query
                or parts.fragment
                or method not in {"GET", "POST", "DELETE"}
                or not (parts.path in CREATION_PATHS or location_id(base))
            ):
                raise RuntimeError("integration_request_invalid")
            connection = HTTPConnection("127.0.0.1", port, timeout=timeout)
            try:
                connection.request(method, parts.path, body=body, headers=dict(headers or {}))
                with connection.getresponse() as response:
                    return HttpResponse(
                        response.status,
                        {k.lower(): v for k, v in response.getheaders()},
                        _bounded_response_read(response),
                    )
            finally:
                connection.close()

        report = Lifecycle(
            ORIGIN, requester=requester, timing=Timing(case_seconds=240, suite_seconds=1000)
        ).run()
        if not valid_report(report) or report["result"] != "PASS":
            raise RuntimeError("batch_integration_failed")
    return BATCH_CHECKS


def main():
    try:
        checks = run_batch_integration()
    except Exception:  # noqa: BLE001 - local server/engine diagnostics remain private
        print("Batch API integration FAIL: local lifecycle or cleanup failed")
        return 1
    print(f"Batch API integration PASS: {len(checks)} lifecycles with confirmed cleanup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

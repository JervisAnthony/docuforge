"""Exercise smoke multipart contracts through real, local conversion implementations."""

from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from docuforge.api import create_app
from docuforge.ops.deployment_smoke import (
    MVP1_OPERATION_CHECKS,
    SMOKE_CHECKS,
    HttpResponse,
    ProductionSmokeRunner,
)


def test_ten_mvp1_checks_against_real_local_api():
    calls = []
    with TestClient(create_app()) as client:

        def requester(method, url, *, headers=None, body=None, timeout):
            path = urlsplit(url).path
            calls.append(path)
            response = client.request(method, path, headers=headers, content=body)
            return HttpResponse(response.status_code, response.headers, response.content)

        runner = ProductionSmokeRunner(
            frontend_url="https://app.example.com",
            api_url="https://api.example.com",
            requester=requester,
        )
        # System contracts and OS-dependent Office/OCR checks have separate tests.
        assert len(MVP1_OPERATION_CHECKS) == len(set(MVP1_OPERATION_CHECKS)) == 10
        assert set(MVP1_OPERATION_CHECKS) <= set(SMOKE_CHECKS)
        for name in MVP1_OPERATION_CHECKS:
            getattr(runner, f"_check_{name.replace('-', '_')}")()
    assert len(calls) == 10
    assert len(set(calls)) == 10

import json
from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfWriter

from docuforge.ops.deployment_smoke import (
    DeploymentSmokeError,
    HttpResponse,
    ProductionSmokeRunner,
)


def _pdf(*widths: int) -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=120)
    writer.write(buffer)
    return buffer.getvalue()


def _jpeg() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (96, 64), (42, 106, 174)).save(buffer, format="JPEG")
    return buffer.getvalue()


class FakeRequester:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], bytes | None, float]] = []

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers=None,
        body=None,
        timeout: float,
    ) -> HttpResponse:
        resolved_headers = dict(headers or {})
        self.calls.append((method, url, resolved_headers, body, timeout))

        if method == "GET" and url == "https://app.example.com":
            return HttpResponse(
                200,
                {"content-type": "text/html"},
                b"<title>DocuForge</title>",
            )
        if method == "GET" and url.endswith("/api/v1/ready"):
            return HttpResponse(
                200,
                {"content-type": "application/json"},
                json.dumps(
                    {"status": "ready", "service": "docuforge", "version": "1.2.3"}
                ).encode(),
            )
        if method == "GET" and url.endswith("/api/v1/health"):
            return HttpResponse(
                200,
                {
                    "content-type": "application/json",
                    "x-content-type-options": "nosniff",
                    "x-frame-options": "DENY",
                    "referrer-policy": "no-referrer",
                    "permissions-policy": "camera=(), microphone=(), geolocation=()",
                    "strict-transport-security": "max-age=31536000",
                    "x-request-id": "trace-123",
                    "access-control-allow-origin": "https://app.example.com",
                    "access-control-expose-headers": "X-Request-ID",
                },
                json.dumps(
                    {"status": "ok", "service": "docuforge", "version": "1.2.3"}
                ).encode(),
            )
        if method == "GET" and url.endswith("/api/v1/capabilities"):
            return HttpResponse(
                200,
                {"content-type": "application/json"},
                json.dumps({
                    "office_to_pdf": {"available": True},
                    "ocr": {"available": True},
                }).encode(),
            )
        if method == "OPTIONS" and url.endswith("/api/v1/health"):
            return HttpResponse(
                200,
                {
                    "access-control-allow-origin": "https://app.example.com",
                    "access-control-allow-headers": "Accept, Content-Type, X-Request-ID",
                },
                b"OK",
            )
        if method == "POST" and url.endswith("/api/v1/pdf/merge"):
            return HttpResponse(200, {"content-type": "application/pdf"}, _pdf(100, 200))
        if method == "POST" and url.endswith("/api/v1/images/compress"):
            return HttpResponse(200, {"content-type": "image/jpeg"}, _jpeg())
        if method == "POST" and url.endswith("/api/v1/office/docx-to-pdf"):
            return HttpResponse(200, {"content-type": "application/pdf"}, _pdf(100))
        if method == "POST" and url.endswith("/api/v1/ocr/image-to-text"):
            return HttpResponse(
                200,
                {"content-type": "text/plain; charset=utf-8"},
                b"synthetic OCR",
            )
        return HttpResponse(404, {}, b"")


def _runner(requester) -> ProductionSmokeRunner:
    return ProductionSmokeRunner(
        frontend_url="https://app.example.com/",
        api_url="https://api.example.com/",
        timeout=7.5,
        requester=requester,
    )


def test_runner_verifies_full_public_contract() -> None:
    requester = FakeRequester()

    checks = _runner(requester).run()

    assert checks == (
        "frontend",
        "readiness",
        "runtime-capabilities",
        "liveness-and-headers",
        "cors",
        "pdf-merge",
        "image-compression",
        "office-docx-to-pdf",
        "ocr-image-to-text",
    )
    assert [call[0] for call in requester.calls] == [
        "GET",
        "GET",
        "GET",
        "GET",
        "OPTIONS",
        "POST",
        "POST",
        "POST",
        "POST",
    ]
    assert all(call[4] == 7.5 for call in requester.calls)
    assert requester.calls[5][2]["Content-Type"].startswith(
        "multipart/form-data; boundary="
    )
    assert requester.calls[5][3]
    assert requester.calls[6][3]
    assert requester.calls[7][3]
    assert requester.calls[8][3]


def test_runner_uses_frontend_origin_for_browser_cors_checks() -> None:
    requester = FakeRequester()

    _runner(requester).run()

    assert requester.calls[3][2]["Origin"] == "https://app.example.com"
    assert requester.calls[4][2] == {
        "Origin": "https://app.example.com",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Request-ID",
    }


@pytest.mark.parametrize(
    ("frontend_url", "api_url"),
    [
        ("http://app.example.com", "https://api.example.com"),
        ("https://app.example.com/path", "https://api.example.com"),
        ("https://app.example.com", "https://api.example.com?debug=1"),
    ],
)
def test_runner_rejects_non_public_origin_urls(frontend_url: str, api_url: str) -> None:
    with pytest.raises(DeploymentSmokeError):
        ProductionSmokeRunner(frontend_url=frontend_url, api_url=api_url)


def test_runner_rejects_non_positive_timeout() -> None:
    with pytest.raises(DeploymentSmokeError, match="timeout"):
        ProductionSmokeRunner(
            frontend_url="https://app.example.com",
            api_url="https://api.example.com",
            timeout=0,
        )


def test_runner_fails_when_production_security_header_is_missing() -> None:
    requester = FakeRequester()

    def without_hsts(method, url, *, headers=None, body=None, timeout):
        response = requester(method, url, headers=headers, body=body, timeout=timeout)
        if method == "GET" and url.endswith("/api/v1/health"):
            response_headers = dict(response.headers)
            response_headers.pop("strict-transport-security")
            return HttpResponse(response.status_code, response_headers, response.body)
        return response

    with pytest.raises(DeploymentSmokeError, match="Strict-Transport-Security"):
        _runner(without_hsts).run()


def test_runner_fails_when_pdf_merge_semantics_are_wrong() -> None:
    requester = FakeRequester()

    def reversed_pdf(method, url, *, headers=None, body=None, timeout):
        response = requester(method, url, headers=headers, body=body, timeout=timeout)
        if method == "POST" and url.endswith("/api/v1/pdf/merge"):
            return HttpResponse(200, response.headers, _pdf(200, 100))
        return response

    with pytest.raises(DeploymentSmokeError, match="page order"):
        _runner(reversed_pdf).run()


def test_runner_fails_when_image_workflow_returns_invalid_output() -> None:
    requester = FakeRequester()

    def invalid_image(method, url, *, headers=None, body=None, timeout):
        response = requester(method, url, headers=headers, body=body, timeout=timeout)
        if method == "POST" and url.endswith("/api/v1/images/compress"):
            return HttpResponse(200, response.headers, b"not-an-image")
        return response

    with pytest.raises(DeploymentSmokeError, match="invalid image"):
        _runner(invalid_image).run()


@pytest.mark.parametrize("capability", ["office_to_pdf", "ocr"])
def test_runner_fails_when_runtime_capability_is_unavailable(capability: str) -> None:
    requester = FakeRequester()

    def unavailable(method, url, *, headers=None, body=None, timeout):
        response = requester(method, url, headers=headers, body=body, timeout=timeout)
        if method == "GET" and url.endswith("/api/v1/capabilities"):
            payload = {
                "office_to_pdf": {"available": True},
                "ocr": {"available": True},
            }
            payload[capability]["available"] = False
            return HttpResponse(200, response.headers, json.dumps(payload).encode())
        return response

    with pytest.raises(DeploymentSmokeError, match=f"{capability} is unavailable"):
        _runner(unavailable).run()


def test_runner_fails_safely_for_malformed_capability_response() -> None:
    requester = FakeRequester()

    def malformed(method, url, *, headers=None, body=None, timeout):
        response = requester(method, url, headers=headers, body=body, timeout=timeout)
        if method == "GET" and url.endswith("/api/v1/capabilities"):
            return HttpResponse(200, response.headers, b'{"office_to_pdf": []}')
        return response

    with pytest.raises(DeploymentSmokeError, match="office_to_pdf is unavailable") as failure:
        _runner(malformed).run()
    assert "private" not in str(failure.value)


def test_runner_accepts_office_pdf_and_ocr_utf8_workflows() -> None:
    assert _runner(FakeRequester()).run()[-2:] == (
        "office-docx-to-pdf",
        "ocr-image-to-text",
    )


def test_runner_rejects_invalid_office_pdf_response() -> None:
    requester = FakeRequester()

    def invalid_office(method, url, *, headers=None, body=None, timeout):
        response = requester(method, url, headers=headers, body=body, timeout=timeout)
        if method == "POST" and url.endswith("/api/v1/office/docx-to-pdf"):
            return HttpResponse(200, {"content-type": "application/pdf"}, b"not-a-pdf")
        return response

    with pytest.raises(DeploymentSmokeError, match="invalid PDF"):
        _runner(invalid_office).run()


def test_runner_rejects_failed_ocr_endpoint_without_exposing_body() -> None:
    requester = FakeRequester()

    def failed_ocr(method, url, *, headers=None, body=None, timeout):
        response = requester(method, url, headers=headers, body=body, timeout=timeout)
        if method == "POST" and url.endswith("/api/v1/ocr/image-to-text"):
            return HttpResponse(503, {"content-type": "application/json"}, b"private stderr")
        return response

    with pytest.raises(DeploymentSmokeError, match="returned HTTP 503") as failure:
        _runner(failed_ocr).run()
    assert "private stderr" not in str(failure.value)

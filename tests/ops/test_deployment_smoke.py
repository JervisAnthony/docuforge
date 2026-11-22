import json
import subprocess
import sys
from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image
from pypdf import PdfWriter

from docuforge.ops import deployment_smoke as smoke
from docuforge.ops.deployment_smoke import (
    SMOKE_CHECKS,
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


def _image_bytes(fmt="PNG", size=(96, 64)):
    buffer = BytesIO()
    Image.new("RGB", size, (42, 106, 174)).save(buffer, format=fmt)
    return buffer.getvalue()


def _zip(entries):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return buffer.getvalue()


def _split_entries():
    return [(f"report-page-{i:04d}.pdf", _pdf(width)) for i, width in enumerate((100, 200, 300), 1)]


def _render_entries():
    return [
        (f"report-page-{i:04d}.png", _image_bytes(size=(width, 120)))
        for i, width in enumerate((100, 200, 300), 1)
    ]


def _rotated_pdf():
    writer = PdfWriter()
    for width, rotation in zip((100, 200, 300), (90, 180, 0), strict=True):
        page = writer.add_blank_page(width=width, height=120)
        if rotation:
            page.rotate(rotation)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _images_pdf(reverse=False):
    writer = PdfWriter()
    sizes = [(96, 64), (40, 80)]
    for width, height in reversed(sizes) if reverse else sizes:
        writer.add_blank_page(width=width, height=height)
    buffer = BytesIO()
    writer.write(buffer)
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
                json.dumps({"status": "ok", "service": "docuforge", "version": "1.2.3"}).encode(),
            )
        if method == "GET" and url.endswith("/api/v1/capabilities"):
            return HttpResponse(
                200,
                {"content-type": "application/json"},
                json.dumps(
                    {
                        "office_to_pdf": {"available": True},
                        "ocr": {"available": True},
                    }
                ).encode(),
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
        outputs = {
            "/pdf/split": ("application/zip", lambda: _zip(_split_entries())),
            "/pdf/rotate": ("application/pdf", _rotated_pdf),
            "/pdf/remove-pages": ("application/pdf", lambda: _pdf(100, 300)),
            "/pdf/extract-pages": ("application/pdf", lambda: _pdf(300, 100)),
            "/pdf/to-images": ("application/zip", lambda: _zip(_render_entries())),
            "/images/convert": ("image/jpeg", _jpeg),
            "/images/resize": ("image/png", lambda: _image_bytes(size=(48, 32))),
            "/images/to-pdf": ("application/pdf", _images_pdf),
        }
        for path, (media_type, make_output) in outputs.items():
            if method == "POST" and url.endswith("/api/v1" + path):
                return HttpResponse(200, {"content-type": media_type}, make_output())
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

    assert checks == SMOKE_CHECKS
    assert len(checks) == 17
    assert [call[0] for call in requester.calls] == ["GET"] * 4 + ["OPTIONS"] + ["POST"] * 12
    assert [
        call[1].removeprefix("https://api.example.com/api/v1/") for call in requester.calls[5:]
    ] == [
        "pdf/merge",
        "pdf/split",
        "pdf/rotate",
        "pdf/remove-pages",
        "pdf/extract-pages",
        "pdf/to-images",
        "images/convert",
        "images/resize",
        "images/compress",
        "images/to-pdf",
        "office/docx-to-pdf",
        "ocr/image-to-text",
    ]
    assert all(call[4] == 7.5 for call in requester.calls)
    assert requester.calls[5][2]["Content-Type"].startswith("multipart/form-data; boundary=")
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


@pytest.mark.parametrize(
    ("path", "payload", "reason"),
    [
        ("pdf/split", b"not a zip", "invalid ZIP"),
        ("pdf/split", _zip(_split_entries()[:2]), "member order"),
        ("pdf/split", _zip(list(reversed(_split_entries()))), "member order"),
        ("pdf/split", _zip([(n, _pdf(300)) for n, _ in _split_entries()]), "page order"),
        ("pdf/rotate", _pdf(100, 200, 300), "rotations"),
        ("pdf/rotate", _pdf(300, 200, 100), "page order"),
        ("pdf/remove-pages", _pdf(100, 200), "page order"),
        ("pdf/remove-pages", b"", "invalid PDF"),
        ("pdf/extract-pages", _pdf(100, 300), "page order"),
        ("pdf/to-images", _zip(_render_entries()[:2]), "member order"),
        (
            "pdf/to-images",
            _zip(
                [
                    (n, _image_bytes("GIF", (w, 120)))
                    for (n, _), w in zip(_render_entries(), (100, 200, 300))
                ]
            ),
            "image format",
        ),
        (
            "pdf/to-images",
            _zip([(n, _image_bytes(size=(10, 120))) for n, _ in _render_entries()]),
            "dimensions",
        ),
        ("images/resize", _image_bytes(size=(48, 64)), "dimensions"),
        ("images/convert", _image_bytes(), "image format"),
        ("images/to-pdf", _images_pdf(reverse=True), "orientation or order"),
    ],
    ids=[
        "invalid-split-zip",
        "missing-split-page",
        "reversed-split-members",
        "wrong-split-widths",
        "wrong-rotations",
        "rotated-page-order",
        "wrong-surviving-pages",
        "empty-pdf",
        "wrong-extraction-order",
        "missing-rendered-image",
        "gif-as-png",
        "wrong-render-size",
        "wrong-resize-size",
        "png-as-jpeg",
        "reordered-images-to-pdf",
    ],
)
def test_runner_rejects_incorrect_workflow_semantics(path, payload, reason):
    requester = FakeRequester()

    def corrupt(method, url, **kwargs):
        response = requester(method, url, **kwargs)
        return HttpResponse(200, response.headers, payload) if url.endswith(path) else response

    with pytest.raises(DeploymentSmokeError, match=reason):
        _runner(corrupt).run()


@pytest.mark.parametrize("name", ["../page.pdf", "/page.pdf", "C:page.pdf", "page\\x.pdf", "dir/"])
def test_zip_rejects_unsafe_names(name):
    with pytest.raises(DeploymentSmokeError, match="unsafe ZIP"):
        smoke._zip_members(_zip([(name, b"data")]), (name,))


def test_zip_rejects_duplicate_and_extra_members():
    entries = _split_entries()
    with pytest.warns(UserWarning, match="Duplicate"):
        duplicate = _zip(entries + entries[:1])
    for payload in (duplicate, _zip(entries + [("extra.pdf", _pdf(100))])):
        with pytest.raises(DeploymentSmokeError, match="member order"):
            smoke._zip_members(payload, tuple(n for n, _ in entries))


def test_zip_rejects_bad_crc():
    payload = _zip([("page.pdf", b"unique contents")]).replace(
        b"unique contents", b"altered content"
    )
    with pytest.raises(DeploymentSmokeError, match="invalid ZIP or CRC"):
        smoke._zip_members(payload, ("page.pdf",))


def test_zip_rejects_encryption_flag():
    payload = bytearray(_zip([("page.pdf", b"data")]))
    central = payload.index(b"PK\x01\x02")
    payload[central + 8] |= 1
    with pytest.raises(DeploymentSmokeError, match="unsafe ZIP"):
        smoke._zip_members(bytes(payload), ("page.pdf",))


def test_zip_size_limits_precede_member_reads(monkeypatch):
    payload = _zip([("page.pdf", b"x" * 20)])
    monkeypatch.setattr(smoke, "MAX_ZIP_MEMBER_BYTES", 10)
    with pytest.raises(DeploymentSmokeError, match="member exceeds"):
        smoke._zip_members(payload, ("page.pdf",))
    monkeypatch.setattr(smoke, "MAX_ZIP_MEMBER_BYTES", 30)
    monkeypatch.setattr(smoke, "MAX_ZIP_TOTAL_BYTES", 10)
    with pytest.raises(DeploymentSmokeError, match="total exceeds"):
        smoke._zip_members(payload, ("page.pdf",))


@pytest.mark.parametrize("status", [200, 400, 500])
def test_http_transport_bounded_read(monkeypatch, status):
    from urllib.error import HTTPError

    monkeypatch.setattr(smoke, "MAX_RESPONSE_BYTES", 10)

    class Stream(BytesIO):
        status = 200
        headers = None

        def read(self, size=-1):
            assert size == 11
            return super().read(size)

    stream = Stream(b"x" * 11)
    stream.headers = {}

    def open_response(*args, **kwargs):
        if status != 200:
            raise HTTPError("https://api.example.com", status, "failed", {}, stream)
        return stream

    monkeypatch.setattr(smoke, "urlopen", open_response)
    with pytest.raises(DeploymentSmokeError, match="response exceeds"):
        smoke.request_http("GET", "https://api.example.com", timeout=1)
    assert stream.closed


@pytest.mark.parametrize(
    ("path", "status", "headers", "body", "reason"),
    [
        ("pdf/split", 200, {"content-type": "application/pdf"}, b"", "media type"),
        ("images/convert", 400, {}, b"private document", "HTTP 400"),
        ("ready", 200, {}, b"private document", "valid JSON"),
        ("ready", 200, {}, b"[]", "JSON object"),
        ("health", 200, {"access-control-allow-origin": "https://wrong.example"}, b"", "CORS"),
    ],
)
def test_runner_diagnostics_are_named_and_safe(path, status, headers, body, reason):
    requester = FakeRequester()

    def corrupt(method, url, **kwargs):
        response = requester(method, url, **kwargs)
        if url.endswith(path):
            if path == "health":
                return HttpResponse(status, dict(response.headers) | headers, response.body)
            return HttpResponse(status, headers, body)
        return response

    with pytest.raises(DeploymentSmokeError, match=reason) as failure:
        _runner(corrupt).run()
    assert ": " in str(failure.value)
    assert "private document" not in str(failure.value)


def test_runner_guards_injected_oversized_responses(monkeypatch):
    monkeypatch.setattr(smoke, "MAX_RESPONSE_BYTES", 1)
    with pytest.raises(DeploymentSmokeError, match="frontend: response exceeds"):
        _runner(FakeRequester()).run()


def test_download_rejects_unsafe_disposition():
    response = HttpResponse(
        200,
        {
            "content-type": "application/pdf",
            "content-disposition": 'attachment; filename="../private.pdf"',
        },
        b"",
    )
    with pytest.raises(DeploymentSmokeError, match="unsafe download"):
        smoke._download(response, "application/pdf")


@pytest.mark.parametrize("fail", [False, True])
def test_cli_exit_and_machine_report(monkeypatch, capsys, tmp_path, fail):
    requester = FakeRequester()

    def request(method, url, **kwargs):
        if fail and url.endswith("/pdf/split"):
            return HttpResponse(500, {}, b"private document")
        return requester(method, url, **kwargs)

    monkeypatch.setattr(smoke, "ProductionSmokeRunner", lambda **kwargs: _runner(request))
    report = tmp_path / "report.json"
    result = smoke.main(
        [
            "--frontend-url",
            "https://app.example.com",
            "--api-url",
            "https://api.example.com",
            "--report-json",
            str(report),
        ]
    )
    output = capsys.readouterr()
    evidence = json.loads(report.read_text())
    assert result == (1 if fail else 0)
    assert evidence["result"] == ("FAIL" if fail else "PASS")
    assert evidence["checks_executed"] == (7 if fail else 17)
    assert evidence["passed_checks"] == list(SMOKE_CHECKS[:6] if fail else SMOKE_CHECKS)
    if fail:
        assert "FAIL pdf-split: download returned HTTP 500" in output.err
        assert "Production smoke passed" not in output.out
        assert "private document" not in output.err


@pytest.mark.parametrize("name", SMOKE_CHECKS[5:])
def test_every_download_requires_expected_media_type(name):
    requester = FakeRequester()

    def wrong_type(method, url, **kwargs):
        response = requester(method, url, **kwargs)
        if method == "POST":
            return HttpResponse(200, {"content-type": "text/html"}, response.body)
        return response

    runner = _runner(wrong_type)
    with pytest.raises(DeploymentSmokeError, match="media type"):
        getattr(runner, f"_check_{name.replace('-', '_')}")()


def test_split_rejects_encrypted_pdf_member():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=120)
    writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)
    entries = _split_entries()
    entries[0] = (entries[0][0], output.getvalue())
    requester = FakeRequester()

    def encrypted(method, url, **kwargs):
        response = requester(method, url, **kwargs)
        if url.endswith("pdf/split"):
            return HttpResponse(200, response.headers, _zip(entries))
        return response

    with pytest.raises(DeploymentSmokeError, match="pdf-split: invalid PDF"):
        _runner(encrypted).run()


@pytest.mark.parametrize(
    "scenario", ["pass", "partial", "identity-failed", "missing", "invalid-origin"]
)
def test_workflow_summary_is_fail_closed(monkeypatch, tmp_path, scenario):
    from pathlib import Path
    from textwrap import dedent

    workflow = (
        Path(__file__).resolve().parents[2] / ".github/workflows/production-smoke.yml"
    ).read_text()
    assert "  workflow_dispatch:" in workflow
    assert (
        "  push:" not in workflow
        and "  pull_request:" not in workflow
        and "  schedule:" not in workflow
    )
    assert "continue-on-error" not in workflow
    script = dedent(workflow.split("          python - <<'PY'\n")[1].split("          PY\n")[0])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DOCUFORGE_FRONTEND_URL", "https://app.example.com")
    monkeypatch.setenv("DOCUFORGE_API_URL", "https://api.example.com")
    monkeypatch.setenv(
        "IDENTITY_OUTCOME", "failure" if scenario == "identity-failed" else "success"
    )
    monkeypatch.setenv("SMOKE_OUTCOME", "failure" if scenario == "partial" else "success")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "JervisAnthony/docuforge")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    if scenario == "invalid-origin":
        monkeypatch.setenv("DOCUFORGE_API_URL", "https://user:private-token@api.example.com")
        monkeypatch.setenv("SMOKE_OUTCOME", "failure")
    if scenario != "missing":
        partial = scenario == "partial"
        (tmp_path / "production-smoke.json").write_text(
            json.dumps(
                {
                    "result": "FAIL" if partial else "PASS",
                    "passed_checks": list(SMOKE_CHECKS[:6] if partial else SMOKE_CHECKS),
                    "checks_executed": 7 if partial else 17,
                }
            )
        )
    subprocess.run([sys.executable, "-c", script], check=True)
    content = summary.read_text()
    assert f"Overall: {'PASS' if scenario == 'pass' else 'FAIL'}" in content
    assert "Expected semantic release version: 0.1.0" in content
    assert "https://github.com/JervisAnthony/docuforge/actions/runs/123" in content
    assert "private-token" not in content
    if scenario == "partial":
        assert "Checks executed: 7 / 17" in content
        assert "pdf-split" not in content

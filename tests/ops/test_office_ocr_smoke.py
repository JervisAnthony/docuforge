"""Meaningful failure boundaries for the four required Office/scanned-PDF checks."""

import json
from email import policy
from email.parser import BytesParser
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter

from docuforge.ops import deployment_smoke as smoke
from docuforge.ops.smoke_fixtures import (
    PPTX_MARKER,
    SCAN_MARKERS,
    SCAN_PAGE_SIZES,
    XLSX_MARKER,
    make_synthetic_scanned_pdf,
)
from tests.ops.office_ocr_support import text_pdf
from tests.ops.test_deployment_smoke import FakeRequester, _runner


def _path(name):
    return "/api/v1/" + name.replace("-", "/", 1)


def _check(name, requester):
    getattr(_runner(requester), f"_check_{name.replace('-', '_')}")()


def _override(name, *, payload=b"private response text", media=None, status=200, error=None):
    requester = FakeRequester()

    def altered(method, url, **kwargs):
        response = requester(method, url, **kwargs)
        if url.endswith(_path(name)):
            if error:
                raise error
            headers = dict(response.headers)
            if media is not None:
                headers["content-type"] = media
            return smoke.HttpResponse(status, headers, payload)
        return response

    return altered


@pytest.mark.parametrize("name", smoke.OFFICE_OCR_CHECKS)
def test_four_requests_use_exact_single_multipart_file_contract(name):
    requester = FakeRequester()
    _check(name, requester)
    [(method, url, headers, body, timeout)] = requester.calls
    assert method == "POST" and url.endswith(_path(name))
    assert timeout == 7.5
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + headers["Content-Type"].encode() + b"\r\n\r\n" + body
    )
    [part] = list(message.iter_parts())
    assert part.get_param("name", header="content-disposition") == "file"
    extension = (
        "pptx"
        if name.startswith("office-pptx")
        else "xlsx"
        if name.startswith("office-xlsx")
        else "pdf"
    )
    assert part.get_filename() == (
        f"runtime-smoke.{extension}" if extension != "pdf" else "runtime-scan.pdf"
    )
    expected_type = {
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
    }[extension]
    assert part.get_content_type() == expected_type
    if extension == "pdf":
        pages = PdfReader(BytesIO(part.get_payload(decode=True))).pages
        assert len(pages) == 2 and all(not page.extract_text() for page in pages)


@pytest.mark.parametrize("name", smoke.OFFICE_OCR_CHECKS)
@pytest.mark.parametrize("status", [400, 422, 500, 502, 503, 504])
def test_required_check_http_failures_are_named_safe_and_stop_at_that_attempt(name, status):
    runner = _runner(_override(name, status=status))
    with pytest.raises(
        smoke.DeploymentSmokeError, match=f"{name}: download returned HTTP {status}"
    ) as failure:
        runner.run()
    assert runner.passed_checks == list(smoke.SMOKE_CHECKS[: smoke.SMOKE_CHECKS.index(name)])
    assert "private" not in str(failure.value)


@pytest.mark.parametrize("name", smoke.OFFICE_OCR_CHECKS)
@pytest.mark.parametrize("kind", ["timeout", "unavailable"])
def test_required_check_transport_failures_never_print_raw_diagnostics(name, kind):
    error = (
        TimeoutError("private timeout details")
        if kind == "timeout"
        else OSError("private engine path")
    )
    with pytest.raises(
        smoke.DeploymentSmokeError, match=f"{name}: invalid response or transport failure"
    ) as failure:
        _runner(_override(name, error=error)).run()
    assert "private" not in str(failure.value)


@pytest.mark.parametrize("name", smoke.OFFICE_OCR_CHECKS)
def test_new_checks_require_pdf_or_plain_text_media_and_safe_download_names(name):
    with pytest.raises(smoke.DeploymentSmokeError, match="media type"):
        _check(name, _override(name, media="text/html"))
    requester = FakeRequester()

    def bad_filename(method, url, **kwargs):
        response = requester(method, url, **kwargs)
        return smoke.HttpResponse(
            200,
            {
                **response.headers,
                "content-disposition": 'attachment; filename="../private-document"',
            },
            response.body,
        )

    with pytest.raises(smoke.DeploymentSmokeError, match="unsafe download filename"):
        _check(name, bad_filename)


def _encrypted_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=360, height=216)
    writer.encrypt("synthetic-password")
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


PDF_CHECKS = tuple(name for name in smoke.OFFICE_OCR_CHECKS if name != "ocr-pdf-to-text")


@pytest.mark.parametrize("name", PDF_CHECKS)
@pytest.mark.parametrize(
    "payload",
    [b"", b"private malformed PDF text", text_pdf(), _encrypted_pdf()],
    ids=["empty", "malformed", "zero-pages", "encrypted"],
)
def test_pdf_checks_reject_invalid_unencrypted_empty_or_missing_outputs(
    name, payload, capsys, caplog
):
    with pytest.raises(smoke.DeploymentSmokeError, match="invalid PDF") as failure:
        _check(name, _override(name, payload=payload))
    assert "private" not in str(failure.value)
    output = capsys.readouterr()
    assert "private" not in output.out + output.err + caplog.text


@pytest.mark.parametrize("name", ("office-pptx-to-pdf", "office-xlsx-to-pdf"))
@pytest.mark.parametrize("kind", ["blank", "wrong-marker", "extra-page"])
def test_office_pdf_requires_one_page_and_its_own_marker(name, kind):
    marker = PPTX_MARKER if name == "office-pptx-to-pdf" else XLSX_MARKER
    payload = text_pdf(
        (
            720,
            540,
            "" if kind == "blank" else "private wrong marker" if kind == "wrong-marker" else marker,
        )
    )
    if kind == "extra-page":
        payload = text_pdf((720, 540, marker), (720, 540, marker))
    with pytest.raises(smoke.DeploymentSmokeError, match="page count|text marker") as failure:
        _check(name, _override(name, payload=payload))
    assert "private" not in str(failure.value)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b" \n\f\t",
        b"\xff\fBRAVO",
        b"ALPHA",
        b"ALPHA\nBRAVO",
        b"BRAVO\fALPHA",
        b"ALPHA\f\fBRAVO",
        b"ALPHA\f",
        b"ALPHA BRAVO\fBRAVO",
        b"private error response",
        b"<html>ALPHA\fBRAVO</html>",
    ],
    ids=[
        "empty",
        "whitespace",
        "invalid-utf8",
        "missing-page",
        "no-boundary",
        "reordered",
        "extra-page",
        "empty-page",
        "merged-markers",
        "error-text",
        "html-error-page",
    ],
)
def test_pdf_text_rejects_invalid_text_boundaries_order_and_error_pages(payload):
    with pytest.raises(smoke.DeploymentSmokeError) as failure:
        _check("ocr-pdf-to-text", _override("ocr-pdf-to-text", payload=payload))
    assert "private" not in str(failure.value)


@pytest.mark.parametrize(
    "kind",
    [
        "original-scan",
        "blank",
        "no-second-text",
        "missing-page",
        "reordered",
        "swapped-text",
        "wrong-geometry",
    ],
)
def test_searchable_pdf_requires_text_layers_order_count_and_geometry(kind):
    pages = [(*size, marker) for size, marker in zip(SCAN_PAGE_SIZES, SCAN_MARKERS, strict=True)]
    if kind == "blank":
        pages = [(*size, "") for size in SCAN_PAGE_SIZES]
    elif kind == "no-second-text":
        pages[1] = (*SCAN_PAGE_SIZES[1], "")
    elif kind == "missing-page":
        pages = pages[:1]
    elif kind == "reordered":
        pages.reverse()
    elif kind == "swapped-text":
        pages = [
            (*size, marker)
            for size, marker in zip(SCAN_PAGE_SIZES, reversed(SCAN_MARKERS), strict=True)
        ]
    elif kind == "wrong-geometry":
        pages[0] = (362, 216, "ALPHA")
    payload = make_synthetic_scanned_pdf() if kind == "original-scan" else text_pdf(*pages)
    with pytest.raises(smoke.DeploymentSmokeError):
        _check("ocr-pdf-to-searchable-pdf", _override("ocr-pdf-to-searchable-pdf", payload=payload))


def test_case_whitespace_normalization_and_one_point_geometry_tolerance():
    _check("ocr-pdf-to-text", _override("ocr-pdf-to-text", payload=b"al pha\n\fbra vo\n"))
    payload = text_pdf((361, 215, "al pha"), (431, 253, "bra vo"))
    _check("ocr-pdf-to-searchable-pdf", _override("ocr-pdf-to-searchable-pdf", payload=payload))


@pytest.mark.parametrize("name", smoke.OFFICE_OCR_CHECKS)
def test_cli_reports_new_check_failure_and_accurate_partial_21_check_evidence(
    monkeypatch, tmp_path, capsys, name
):
    runner = _runner(_override(name, status=503))
    monkeypatch.setattr(smoke, "ProductionSmokeRunner", lambda **kwargs: runner)
    report = tmp_path / "smoke.json"
    code = smoke.main(
        [
            "--api-url",
            "https://api.example.com",
            "--frontend-url",
            "https://app.example.com",
            "--report-json",
            str(report),
        ]
    )
    evidence = json.loads(report.read_bytes())
    index = smoke.SMOKE_CHECKS.index(name)
    assert code == 1 and evidence["result"] == "FAIL"
    assert evidence["passed_checks"] == list(smoke.SMOKE_CHECKS[:index])
    assert evidence["checks_executed"] == index + 1
    assert evidence["expected_count"] == 21
    output = capsys.readouterr()
    assert name in output.err and "private" not in output.out + output.err
    assert "Production smoke passed" not in output.out


def test_cli_cannot_call_an_old_17_check_run_complete(monkeypatch, tmp_path, capsys):
    runner = _runner(FakeRequester())

    def old_run():
        runner.passed_checks = list(smoke.SMOKE_CHECKS[:17])
        return tuple(runner.passed_checks)

    monkeypatch.setattr(runner, "run", old_run)
    monkeypatch.setattr(smoke, "ProductionSmokeRunner", lambda **kwargs: runner)
    report = tmp_path / "smoke.json"
    assert (
        smoke.main(
            [
                "--api-url",
                "https://api.example.com",
                "--frontend-url",
                "https://app.example.com",
                "--report-json",
                str(report),
            ]
        )
        == 1
    )
    evidence = json.loads(report.read_bytes())
    assert evidence["result"] == "FAIL" and evidence["checks_executed"] == 17
    assert evidence["expected_count"] == 21
    assert "Production smoke passed" not in capsys.readouterr().out

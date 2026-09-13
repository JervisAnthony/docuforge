"""HTTP-to-core Office conversion coverage without a LibreOffice installation."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
from threading import current_thread
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from docuforge.api import create_app
from docuforge.api.config import ApiSettings
from docuforge.api.workspace import RequestWorkspace
from docuforge.converters.office import (
    OfficeConversionError,
    OfficeConversionRequest,
    OfficeConversionResult,
    OfficeEngineExecutionError,
    OfficeEngineTimeoutError,
    OfficeEngineUnavailableError,
)
from docuforge.core import DocumentFormat

FORMATS = {
    "docx": (DocumentFormat.DOCX, "word/document.xml"),
    "pptx": (DocumentFormat.PPTX, "ppt/presentation.xml"),
    "xlsx": (DocumentFormat.XLSX, "xl/workbook.xml"),
}


def package(kind: str, *, members: tuple[str, ...] | None = None) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for member in members or ("[Content_Types].xml", FORMATS[kind][1]):
            archive.writestr(member, "<xml />")
    return buffer.getvalue()


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[OfficeConversionRequest] = []
        self.workspaces: list[Path] = []

    def convert_to_pdf(self, request: OfficeConversionRequest) -> OfficeConversionResult:
        self.calls.append(request)
        self.workspaces.append(request.output_directory)
        output = request.output_directory / "rendered.pdf"
        output.write_bytes(b"%PDF-1.7\nfake Office output")
        return OfficeConversionResult(
            input_path=request.input_path,
            output_path=output,
            source_format=DocumentFormat.normalize(request.input_path.suffix),
        )


@pytest.mark.parametrize("kind", FORMATS)
def test_each_office_route_uses_core_converter_and_downloads_pdf(kind: str) -> None:
    engine = FakeEngine()
    response = TestClient(create_app(office_engine_factory=lambda: engine)).post(
        f"/api/v1/office/{kind}-to-pdf",
        files={"file": (f"quarterly report.{kind}", package(kind), "text/plain")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert unquote(response.headers["content-disposition"].split("''", 1)[1]) == (
        "quarterly report.pdf"
    )
    assert response.content.startswith(b"%PDF-")
    assert len(engine.calls) == 1
    assert engine.calls[0].input_path.suffix == f".{kind}"
    assert engine.workspaces[0].parent.name.startswith("docuforge-")
    assert not engine.workspaces[0].parent.exists()


@pytest.mark.parametrize("kind", FORMATS)
def test_uppercase_extension_and_safe_unicode_name(kind: str) -> None:
    response = TestClient(create_app(office_engine_factory=FakeEngine)).post(
        f"/api/v1/office/{kind}-to-pdf",
        files={"file": (f"résumé.{kind.upper()}", package(kind), "application/octet-stream")},
    )
    assert response.status_code == 200
    assert unquote(response.headers["content-disposition"].split("''", 1)[1]) == "résumé.pdf"


@pytest.mark.parametrize("kind", FORMATS)
def test_wrong_extension_and_missing_or_multiple_files(kind: str) -> None:
    client = TestClient(create_app(office_engine_factory=FakeEngine))
    wrong = next(candidate for candidate in FORMATS if candidate != kind)
    response = client.post(
        f"/api/v1/office/{kind}-to-pdf",
        files={"file": (f"file.{wrong}", package(wrong))},
    )
    assert response.status_code == 415
    assert client.post(f"/api/v1/office/{kind}-to-pdf").json()["code"] == "invalid_office_request"
    multiple = client.post(
        f"/api/v1/office/{kind}-to-pdf",
        files=[
            ("file", (f"first.{kind}", package(kind))),
            ("file", (f"second.{kind}", package(kind))),
        ],
    )
    assert multiple.status_code == 400
    assert multiple.json()["code"] == "invalid_office_request"


@pytest.mark.parametrize("kind", FORMATS)
@pytest.mark.parametrize("contents", [b"text", b"PK\x03\x04broken", b"\x00\x01\x02"])
def test_invalid_ooxml_is_rejected_before_engine_call(kind: str, contents: bytes) -> None:
    engine = FakeEngine()
    response = TestClient(create_app(office_engine_factory=lambda: engine)).post(
        f"/api/v1/office/{kind}-to-pdf",
        files={"file": (f"source.{kind}", contents)},
    )
    assert response.status_code == 400
    assert response.json() == {
        "code": "invalid_office_request",
        "message": "The Office conversion request is invalid.",
    }
    assert engine.calls == []


@pytest.mark.parametrize("kind", FORMATS)
@pytest.mark.parametrize("missing", ["[Content_Types].xml", "format_member"])
def test_incomplete_ooxml_is_rejected(kind: str, missing: str) -> None:
    required = ("[Content_Types].xml", FORMATS[kind][1])
    members = tuple(member for member in required if member != (FORMATS[kind][1] if missing == "format_member" else missing))
    engine = FakeEngine()
    response = TestClient(create_app(office_engine_factory=lambda: engine)).post(
        f"/api/v1/office/{kind}-to-pdf",
        files={"file": (f"source.{kind}", package(kind, members=members))},
    )
    assert response.status_code == 400
    assert engine.calls == []


@pytest.mark.parametrize(
    ("exception", "status", "code", "message"),
    [
        (OfficeEngineUnavailableError("secret"), 503, "office_engine_unavailable", "Office conversion is temporarily unavailable."),
        (OfficeEngineTimeoutError("secret"), 504, "office_conversion_timeout", "The Office conversion timed out."),
        (OfficeEngineExecutionError("secret"), 502, "office_engine_failed", "The Office conversion engine failed."),
        (OfficeConversionError("secret"), 422, "office_conversion_failed", "The Office document could not be converted."),
    ],
)
def test_office_errors_are_safe(exception: Exception, status: int, code: str, message: str) -> None:
    def fail() -> FakeEngine:
        raise exception

    response = TestClient(create_app(office_engine_factory=fail)).post(
        "/api/v1/office/docx-to-pdf",
        files={"file": ("source.docx", package("docx"))},
    )
    assert response.status_code == status
    assert response.json() == {"code": code, "message": message}
    assert "secret" not in response.text


def test_engine_factory_is_lazy_and_other_routes_remain_healthy() -> None:
    calls = 0

    def unavailable() -> FakeEngine:
        nonlocal calls
        calls += 1
        raise OfficeEngineUnavailableError("private path")

    app = create_app(office_engine_factory=unavailable)
    client = TestClient(app)
    assert calls == 0
    assert client.get("/api/v1").status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    assert calls == 0
    assert client.post(
        "/api/v1/office/docx-to-pdf", files={"file": ("source.docx", package("docx"))}
    ).status_code == 503
    assert calls == 1


@pytest.mark.parametrize("prefix", ["/", "/custom"])
def test_custom_prefix_includes_office_routes(prefix: str) -> None:
    path = "/office/docx-to-pdf" if prefix == "/" else f"{prefix}/office/docx-to-pdf"
    response = TestClient(
        create_app(ApiSettings(api_prefix=prefix), office_engine_factory=FakeEngine)
    ).post(path, files={"file": ("source.docx", package("docx"))})
    assert response.status_code == 200


def test_openapi_documents_pdf_and_errors() -> None:
    schema = TestClient(create_app(office_engine_factory=FakeEngine)).get("/openapi.json").json()
    for kind in FORMATS:
        responses = schema["paths"][f"/api/v1/office/{kind}-to-pdf"]["post"]["responses"]
        assert responses["200"]["content"]["application/pdf"]["schema"] == {
            "type": "string", "format": "binary"
        }
        assert {"400", "413", "415", "422", "502", "503", "504"}.issubset(responses)


def test_upload_limit_and_client_filename_safety() -> None:
    limited = TestClient(
        create_app(
            ApiSettings(max_upload_file_bytes=8, max_upload_request_bytes=8),
            office_engine_factory=FakeEngine,
        )
    )
    oversized = limited.post(
        "/api/v1/office/docx-to-pdf", files={"file": ("source.docx", package("docx"))}
    )
    assert oversized.status_code == 413

    client = TestClient(create_app(office_engine_factory=FakeEngine))
    traversing = client.post(
        "/api/v1/office/docx-to-pdf",
        files={"file": ("../../proposal.docx", package("docx"))},
    )
    assert traversing.status_code == 200
    disposition = traversing.headers["content-disposition"]
    assert disposition == 'attachment; filename="proposal.pdf"'
    assert ".." not in disposition


def test_engine_factory_and_conversion_run_in_worker_thread() -> None:
    thread_names: list[str] = []

    class RecordingEngine(FakeEngine):
        def convert_to_pdf(self, request: OfficeConversionRequest) -> OfficeConversionResult:
            thread_names.append(current_thread().name)
            return super().convert_to_pdf(request)

    def factory() -> RecordingEngine:
        thread_names.append(current_thread().name)
        return RecordingEngine()

    response = TestClient(create_app(office_engine_factory=factory)).post(
        "/api/v1/office/docx-to-pdf",
        files={"file": ("source.docx", package("docx"))},
    )
    assert response.status_code == 200
    assert len(thread_names) == 2
    assert all("AnyIO worker thread" in name for name in thread_names)


def test_request_workspace_is_cleaned_after_conversion_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import docuforge.api.routes.office as office_routes

    paths: list[Path] = []

    class TrackingWorkspace(RequestWorkspace):
        def __init__(self) -> None:
            super().__init__()
            paths.append(self.path)

    class FailingEngine(FakeEngine):
        def convert_to_pdf(self, request: OfficeConversionRequest) -> OfficeConversionResult:
            raise OfficeEngineExecutionError("private process detail")

    monkeypatch.setattr(office_routes, "RequestWorkspace", TrackingWorkspace)
    response = TestClient(create_app(office_engine_factory=FailingEngine)).post(
        "/api/v1/office/docx-to-pdf",
        files={"file": ("source.docx", package("docx"))},
    )
    assert response.status_code == 502
    assert paths and all(not path.exists() for path in paths)

"""OCR HTTP routes exercise the real core workflows with an injected fake engine."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from threading import current_thread
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader, PdfWriter

from docuforge.api import ApiSettings, create_app
from docuforge.api.workspace import RequestWorkspace
from docuforge.converters.ocr import (
    OcrEngineExecutionError,
    OcrEngineRequest,
    OcrEngineResult,
    OcrEngineTimeoutError,
    OcrEngineUnavailableError,
    OcrOutputError,
)
from docuforge.core import DocumentFormat, InvalidConversionRequestError
from tests.api.image_test_support import make_image
from tests.api.pdf_test_support import make_pdf

BASE = "/api/v1/ocr"
EXACT_TEXT = "  Café\r\nsecond line  \n"


class FakeOcrEngine:
    def __init__(self, *, text: str = EXACT_TEXT) -> None:
        self.text = text
        self.calls: list[OcrEngineRequest] = []
        self.threads: list[str] = []
        self.workspace_paths: list[Path] = []

    def recognize(self, request: OcrEngineRequest) -> OcrEngineResult:
        self.calls.append(request)
        self.threads.append(current_thread().name)
        self.workspace_paths.append(request.output_directory)
        output = request.output_directory / f"page.{request.output_format.value}"
        if request.output_format is DocumentFormat.TXT:
            output.write_bytes(self.text.encode("utf-8"))
        else:
            assert request.dpi is not None
            with Image.open(request.input_path) as image:
                width, height = image.size
            writer = PdfWriter()
            writer.add_blank_page(width=width * 72 / request.dpi, height=height * 72 / request.dpi)
            with output.open("wb") as stream:
                writer.write(stream)
            writer.close()
        return OcrEngineResult(
            request.input_path, output, request.output_format, request.language, request.dpi
        )


def upload(name: str, content: bytes, *, mime: str = "text/plain") -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, content, mime)}


@pytest.mark.parametrize(
    ("format_name", "suffix"),
    [("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp"),
     ("BMP", ".bmp"), ("TIFF", ".tif")],
)
def test_image_route_uses_core_and_returns_exact_utf8(format_name: str, suffix: str) -> None:
    engine = FakeOcrEngine()
    response = TestClient(create_app(ocr_engine_factory=lambda: engine)).post(
        f"{BASE}/image-to-text", files=upload(f"receipt{suffix.upper()}", make_image(format_name))
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.content == EXACT_TEXT.encode("utf-8")
    assert response.headers["content-disposition"] == 'attachment; filename="receipt.txt"'
    assert len(engine.calls) == 1
    assert engine.calls[0].output_format is DocumentFormat.TXT
    assert engine.calls[0].dpi is None
    assert not engine.workspace_paths[0].parent.exists()


def test_image_route_retains_empty_text_and_safe_unicode_filename() -> None:
    engine = FakeOcrEngine(text="")
    response = TestClient(create_app(ocr_engine_factory=lambda: engine)).post(
        f"{BASE}/image-to-text", files=upload("résumé scan.png", make_image())
    )
    assert response.status_code == 200
    assert response.content == b""
    assert unquote(response.headers["content-disposition"].split("''", 1)[1]) == "résumé scan.txt"


def test_pdf_text_uses_default_dpi_and_exact_page_boundaries() -> None:
    engine = FakeOcrEngine(text="one\n")
    response = TestClient(create_app(ocr_engine_factory=lambda: engine)).post(
        f"{BASE}/pdf-to-text", files=upload("scan.pdf", make_pdf(72, 90))
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="scan.txt"'
    assert response.content == b"one\n\fone\n"
    assert len(engine.calls) == 2
    assert all(call.output_format is DocumentFormat.TXT and call.dpi == 300 for call in engine.calls)
    assert all(not path.parent.exists() for path in engine.workspace_paths)


def test_searchable_pdf_is_parseable_and_ordered() -> None:
    engine = FakeOcrEngine()
    response = TestClient(create_app(ocr_engine_factory=lambda: engine)).post(
        f"{BASE}/pdf-to-searchable-pdf", files=upload("scan.PDF", make_pdf(72, 90))
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="scan-searchable.pdf"'
    assert response.content.startswith(b"%PDF-")
    assert len(PdfReader(BytesIO(response.content)).pages) == 2
    assert len(engine.calls) == 2
    assert all(call.output_format is DocumentFormat.PDF and call.dpi == 300 for call in engine.calls)
    assert all(not path.parent.exists() for path in engine.workspace_paths)


@pytest.mark.parametrize("route", ["image-to-text", "pdf-to-text", "pdf-to-searchable-pdf"])
def test_exactly_one_file_is_required(route: str) -> None:
    client = TestClient(create_app(ocr_engine_factory=FakeOcrEngine))
    for response in (
        client.post(f"{BASE}/{route}"),
        client.post(f"{BASE}/{route}", files=[
            ("file", ("one.pdf", make_pdf(72))), ("file", ("two.pdf", make_pdf(72))),
        ]),
    ):
        assert response.status_code == 400
        assert response.json() == {
            "code": "invalid_ocr_request",
            "message": "This OCR operation requires exactly one file.",
        }


@pytest.mark.parametrize(
    ("route", "filename", "content"),
    [("image-to-text", "photo.gif", b"GIF89a"),
     ("image-to-text", "scan.pdf", make_pdf(72)),
     ("pdf-to-text", "photo.png", make_image()),
     ("pdf-to-searchable-pdf", "notes.txt", b"text")],
)
def test_transport_extension_policy_rejects_wrong_files(
    route: str, filename: str, content: bytes
) -> None:
    response = TestClient(create_app(ocr_engine_factory=FakeOcrEngine)).post(
        f"{BASE}/{route}", files=upload(filename, content)
    )
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_file_extension"


@pytest.mark.parametrize("contents", [b"plain text", b"\x89PNG\r\ncorrupt"])
def test_invalid_image_is_rejected_before_recognition(contents: bytes) -> None:
    engine = FakeOcrEngine()
    response = TestClient(create_app(ocr_engine_factory=lambda: engine)).post(
        f"{BASE}/image-to-text", files=upload("photo.png", contents)
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_ocr_request"
    assert engine.calls == []


def test_image_suffix_content_mismatch_and_multiframe_tiff_never_reach_engine() -> None:
    engine = FakeOcrEngine()
    client = TestClient(create_app(ocr_engine_factory=lambda: engine))
    mismatch = client.post(
        f"{BASE}/image-to-text", files=upload("photo.png", make_image("JPEG"))
    )
    first = Image.new("RGB", (8, 8), "red")
    second = Image.new("RGB", (8, 8), "blue")
    stream = BytesIO()
    first.save(stream, format="TIFF", save_all=True, append_images=[second])
    multiframe = client.post(
        f"{BASE}/image-to-text", files=upload("photo.tiff", stream.getvalue())
    )
    assert mismatch.status_code == multiframe.status_code == 400
    assert engine.calls == []


@pytest.mark.parametrize("contents", [b"not a PDF", b"%PDF-truncated", make_pdf(encrypted=True)])
def test_invalid_pdf_is_safe_and_never_reaches_engine(contents: bytes) -> None:
    engine = FakeOcrEngine()
    response = TestClient(create_app(ocr_engine_factory=lambda: engine)).post(
        f"{BASE}/pdf-to-text", files=upload("scan.pdf", contents)
    )
    assert response.status_code == 422
    assert response.json()["code"] == "ocr_processing_failed"
    assert engine.calls == []


def test_zero_page_pdf_is_rejected_before_recognition() -> None:
    engine = FakeOcrEngine()
    response = TestClient(create_app(ocr_engine_factory=lambda: engine)).post(
        f"{BASE}/pdf-to-text", files=upload("empty.pdf", make_pdf())
    )
    assert response.status_code == 422
    assert response.json()["code"] == "ocr_processing_failed"
    assert engine.calls == []


@pytest.mark.parametrize("limit", ["pages", "pixels"])
def test_pdf_deployment_limits_reach_core_before_recognition(limit: str) -> None:
    settings = (
        ApiSettings(max_pdf_render_pages=1) if limit == "pages"
        else ApiSettings(max_pdf_render_pixels_per_page=1_000)
    )
    engine = FakeOcrEngine()
    response = TestClient(create_app(settings, ocr_engine_factory=lambda: engine)).post(
        f"{BASE}/pdf-to-text", files=upload("scan.pdf", make_pdf(72, 90))
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_ocr_request"
    assert engine.calls == []


@pytest.mark.parametrize(
    ("exception", "status", "code", "message"),
    [(OcrEngineUnavailableError("private Tesseract path"), 503, "ocr_engine_unavailable", "OCR is temporarily unavailable."),
     (OcrEngineTimeoutError("stderr secret"), 504, "ocr_timeout", "The OCR operation timed out."),
     (OcrEngineExecutionError("workspace secret"), 502, "ocr_engine_failed", "The OCR engine failed."),
     (OcrOutputError("workspace secret"), 422, "ocr_processing_failed", "The document could not be processed with OCR."),
     (InvalidConversionRequestError("workspace secret"), 400, "invalid_ocr_request", "The OCR request is invalid.")],
)
def test_structured_errors_have_safe_responses(
    exception: Exception, status: int, code: str, message: str
) -> None:
    def fail() -> FakeOcrEngine:
        raise exception

    response = TestClient(create_app(ocr_engine_factory=fail)).post(
        f"{BASE}/image-to-text", files=upload("photo.png", make_image())
    )
    assert response.status_code == status
    assert response.json() == {"code": code, "message": message}
    assert all(secret not in response.text for secret in (
        "private Tesseract path", "stderr secret", "workspace secret",
    ))


def test_engine_failure_during_recognition_is_safe_and_cleans_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import docuforge.api.routes.ocr as ocr_routes

    paths: list[Path] = []

    class TrackingWorkspace(RequestWorkspace):
        def __init__(self) -> None:
            super().__init__()
            paths.append(self.path)

    class FailingEngine(FakeOcrEngine):
        def recognize(self, request: OcrEngineRequest) -> OcrEngineResult:
            raise OcrEngineExecutionError("stderr secret")

    monkeypatch.setattr(ocr_routes, "RequestWorkspace", TrackingWorkspace)
    response = TestClient(create_app(ocr_engine_factory=FailingEngine)).post(
        f"{BASE}/image-to-text", files=upload("photo.png", make_image())
    )
    assert response.status_code == 502
    assert response.json()["code"] == "ocr_engine_failed"
    assert "stderr secret" not in response.text
    assert paths and all(not path.exists() for path in paths)


def test_engine_factory_is_lazy_independent_and_runs_in_threadpool() -> None:
    engine = FakeOcrEngine()
    factory_threads: list[str] = []

    def factory() -> FakeOcrEngine:
        factory_threads.append(current_thread().name)
        return engine

    client = TestClient(create_app(ocr_engine_factory=factory))
    assert factory_threads == []
    assert client.get("/api/v1").status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    assert client.post(
        "/api/v1/pdf/to-images",
        files=[("file", ("scan.pdf", make_pdf(72))), ("format", (None, "png"))],
    ).status_code == 200
    assert client.post(
        "/api/v1/images/convert",
        files=[("file", ("photo.png", make_image())), ("format", (None, "jpeg"))],
    ).status_code == 200
    assert client.post(
        "/api/v1/office/docx-to-pdf", files=upload("broken.docx", b"not OOXML")
    ).status_code == 503
    assert factory_threads == []
    assert client.post(f"{BASE}/image-to-text", files=upload("photo.png", make_image())).status_code == 200
    assert factory_threads == ["AnyIO worker thread"]
    assert engine.threads == ["AnyIO worker thread"]


@pytest.mark.parametrize("prefix", ["/", "/custom"])
def test_custom_prefix_includes_all_three_ocr_routes(prefix: str) -> None:
    root = "" if prefix == "/" else prefix
    client = TestClient(create_app(ApiSettings(api_prefix=prefix), ocr_engine_factory=FakeOcrEngine))
    assert client.post(f"{root}/ocr/image-to-text", files=upload("photo.png", make_image())).status_code == 200
    assert client.post(f"{root}/ocr/pdf-to-text", files=upload("scan.pdf", make_pdf(72))).status_code == 200
    assert client.post(f"{root}/ocr/pdf-to-searchable-pdf", files=upload("scan.pdf", make_pdf(72))).status_code == 200


def test_openapi_documents_media_and_errors() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    for route in ("image-to-text", "pdf-to-text", "pdf-to-searchable-pdf"):
        operation = schema["paths"][f"{BASE}/{route}"]["post"]
        assert operation["tags"] == ["OCR"]
        responses = operation["responses"]
        expected_media = "application/pdf" if route == "pdf-to-searchable-pdf" else "text/plain"
        assert expected_media in responses["200"]["content"]
        assert {"400", "413", "415", "422", "502", "503", "504"}.issubset(responses)


def test_upload_limit_filename_safety_and_workspace_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    import docuforge.api.routes.ocr as ocr_routes

    paths: list[Path] = []

    class TrackingWorkspace(RequestWorkspace):
        def __init__(self) -> None:
            super().__init__()
            paths.append(self.path)

    monkeypatch.setattr(ocr_routes, "RequestWorkspace", TrackingWorkspace)
    limited = TestClient(create_app(
        ApiSettings(max_upload_file_bytes=8, max_upload_request_bytes=8),
        ocr_engine_factory=FakeOcrEngine,
    ))
    assert limited.post(f"{BASE}/image-to-text", files=upload("photo.png", make_image())).status_code == 413
    client = TestClient(create_app(ocr_engine_factory=FakeOcrEngine))
    success = client.post(f"{BASE}/image-to-text", files=upload("../../scan.png", make_image()))
    assert success.status_code == 200
    assert success.headers["content-disposition"] == 'attachment; filename="scan.txt"'
    assert client.post(f"{BASE}/image-to-text", files=upload("photo.png", b"broken")).status_code == 400
    assert all(not path.exists() for path in paths)

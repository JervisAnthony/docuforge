"""PDF-to-images HTTP workflow, limits, ZIP safety, and errors."""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from docuforge.api.workspace import RequestWorkspace
from tests.api.image_test_support import inspect_image
from tests.api.pdf_test_support import make_pdf


def render_fields(
    *,
    content: bytes | None = None,
    filename: str = "report.pdf",
    format: str | None = "png",
    dpi: str | None = None,
) -> list[tuple[str, tuple[str | None, bytes | str, str | None]]]:
    fields: list[tuple[str, tuple[str | None, bytes | str, str | None]]] = [
        (
            "file",
            (filename, make_pdf(72) if content is None else content, "application/pdf"),
        )
    ]
    if format is not None:
        fields.append(("format", (None, format, None)))
    if dpi is not None:
        fields.append(("dpi", (None, dpi, None)))
    return fields


def unzip_images(content: bytes) -> tuple[list[str], list[tuple[str | None, tuple[int, int], str]]]:
    with ZipFile(BytesIO(content)) as archive:
        names = archive.namelist()
        images = [inspect_image(archive.read(name)) for name in names]
    return names, images


def test_one_page_default_dpi_returns_safe_png_zip() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/to-images", files=render_fields()
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == (
        'attachment; filename="report-images.zip"'
    )
    names, images = unzip_images(response.content)
    assert names == ["report-page-0001.png"]
    assert images == [("PNG", (150, 359), "RGB")]


def test_multiple_pages_preserve_order_and_dimensions() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/to-images",
        files=render_fields(content=make_pdf(72, 144, 216), dpi="72"),
    )

    assert response.status_code == 200
    names, images = unzip_images(response.content)
    assert names == [
        "report-page-0001.png",
        "report-page-0002.png",
        "report-page-0003.png",
    ]
    assert [image[1] for image in images] == [(72, 172), (144, 244), (216, 316)]


@pytest.mark.parametrize(
    ("format", "expected_format", "suffix", "media_type"),
    [
        ("jpeg", "JPEG", ".jpg", "image/jpeg"),
        ("PNG", "PNG", ".png", "image/png"),
        ("webp", "WEBP", ".webp", "image/webp"),
        ("bmp", "BMP", ".bmp", "image/bmp"),
        ("tif", "TIFF", ".tiff", "image/tiff"),
    ],
)
def test_pdf_render_supports_all_explicit_raster_targets(
    format: str,
    expected_format: str,
    suffix: str,
    media_type: str,
) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/to-images", files=render_fields(format=format, dpi="72")
    )

    assert response.status_code == 200
    names, images = unzip_images(response.content)
    assert names == [f"report-page-0001{suffix}"]
    assert images[0][0] == expected_format
    schema = TestClient(create_app()).get("/openapi.json").json()
    assert "application/zip" in schema["paths"]["/api/v1/pdf/to-images"]["post"][
        "responses"
    ]["200"]["content"]
    assert media_type.startswith("image/")


def test_custom_dpi_changes_dimensions() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/to-images", files=render_fields(dpi="144")
    )

    assert response.status_code == 200
    assert unzip_images(response.content)[1][0][1] == (144, 344)


@pytest.mark.parametrize("dpi", ["71", "301", "true", "72.5", "-72", " 72"])
def test_invalid_http_dpi_has_stable_error(dpi: str) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/to-images", files=render_fields(dpi=dpi)
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "invalid_pdf_render_request",
        "message": "The PDF rendering request is invalid.",
    }


@pytest.mark.parametrize("format", [None, "", "pdf", "gif", "svg"])
def test_invalid_pdf_image_format_has_stable_error(format: str | None) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/to-images", files=render_fields(format=format)
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_image_format"


@pytest.mark.parametrize("content", [b"not a pdf", b"%PDF truncated"])
def test_corrupt_pdf_returns_safe_processing_error(content: bytes) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/to-images", files=render_fields(content=content)
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "pdf_processing_failed",
        "message": "The PDF document could not be processed.",
    }
    assert "PDFium" not in response.text
    assert "docuforge-" not in response.text
    assert "traceback" not in response.text.lower()


def test_encrypted_pdf_returns_safe_processing_error() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/to-images",
        files=render_fields(content=make_pdf(72, encrypted=True)),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "pdf_processing_failed"
    assert "password" not in response.text.lower()


def test_page_count_limit_is_exposed_as_invalid_render_request() -> None:
    settings = ApiSettings(max_pdf_render_pages=1)
    response = TestClient(create_app(settings)).post(
        "/api/v1/pdf/to-images", files=render_fields(content=make_pdf(72, 72))
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_pdf_render_request"


def test_pixel_limit_is_exposed_as_invalid_render_request() -> None:
    settings = ApiSettings(max_pdf_render_pixels_per_page=9_999)
    response = TestClient(create_app(settings)).post(
        "/api/v1/pdf/to-images", files=render_fields(dpi="72")
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_pdf_render_request"


def test_zip_names_remove_traversal_and_internal_identifiers() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/to-images",
        files=render_fields(filename="../../..report.pdf", content=make_pdf(72, 72)),
    )

    assert response.status_code == 200
    names, _ = unzip_images(response.content)
    assert names == ["_report-page-0001.png", "_report-page-0002.png"]
    assert all(not Path(name).is_absolute() and ".." not in name for name in names)
    assert all("docuforge-" not in name for name in names)
    assert ".." not in response.headers["content-disposition"]


def test_pdf_render_upload_uses_transport_limit() -> None:
    settings = ApiSettings(
        max_upload_file_bytes=100,
        max_upload_request_bytes=200,
        upload_chunk_bytes=16,
    )
    response = TestClient(create_app(settings)).post(
        "/api/v1/pdf/to-images", files=render_fields()
    )

    assert response.status_code == 413
    assert response.json()["code"] == "upload_too_large"


def test_pdf_render_rejects_non_pdf_extension() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/to-images", files=render_fields(filename="report.txt")
    )

    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_file_extension"


def test_pdf_render_rejects_multiple_files_with_render_context_error() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/to-images",
        files=[
            ("file", ("one.pdf", make_pdf(72), "application/pdf")),
            ("file", ("two.pdf", make_pdf(72), "application/pdf")),
            ("format", (None, "png")),
        ],
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_pdf_render_request"


@pytest.mark.parametrize("success", [True, False])
def test_pdf_render_workspace_cleans_after_response(
    monkeypatch, success: bool
) -> None:
    created_paths: list[Path] = []

    class RecordingWorkspace(RequestWorkspace):
        def __init__(self) -> None:
            super().__init__()
            created_paths.append(self.path)

    monkeypatch.setattr("docuforge.api.routes.pdf.RequestWorkspace", RecordingWorkspace)
    response = TestClient(create_app()).post(
        "/api/v1/pdf/to-images",
        files=render_fields(content=make_pdf(72) if success else b"broken"),
    )

    assert response.status_code == (200 if success else 422)
    assert len(created_paths) == 1
    assert not created_paths[0].exists()

"""Stable image HTTP errors and transport-limit integration."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from docuforge.api.workspace import RequestWorkspace
from tests.api.image_test_support import make_image


def image_fields(
    path: str,
    *,
    filename: str = "photo.png",
    content: bytes | None = None,
    format: str | None = "png",
    **fields: str,
) -> list[tuple[str, tuple[str | None, bytes | str, str | None]]]:
    multipart: list[tuple[str, tuple[str | None, bytes | str, str | None]]] = [
        ("file", (filename, make_image() if content is None else content, "image/png"))
    ]
    if format is not None:
        multipart.append(("format", (None, format, None)))
    multipart.extend((name, (None, value, None)) for name, value in fields.items())
    return multipart


@pytest.mark.parametrize("value", [None, "", "pdf", "gif", "svg", "unknown"])
@pytest.mark.parametrize("path", ["convert", "resize", "compress"])
def test_invalid_image_format_has_stable_error(
    path: str, value: str | None
) -> None:
    fields = image_fields(path, format=value)
    if path == "resize":
        fields.append(("max_width", (None, "10", None)))
    if path == "compress":
        fields.append(("max_bytes", (None, "1000", None)))

    response = TestClient(create_app()).post(f"/api/v1/images/{path}", files=fields)

    assert response.status_code == 400
    assert response.json() == {
        "code": "invalid_image_format",
        "message": "A supported target image format is required.",
    }


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"max_width": "0"},
        {"max_height": "-1"},
        {"max_width": "1.5"},
        {"max_width": "true"},
        {"max_width": "10", "allow_upscale": "yes"},
    ],
)
def test_invalid_resize_fields_have_stable_error(fields: dict[str, str]) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/resize", files=image_fields("resize", **fields)
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_resize_request"


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"quality": "60", "max_bytes": "1000"},
        {"quality": "0"},
        {"quality": "96"},
        {"quality": "true"},
        {"quality": "1.5"},
        {"max_bytes": "0"},
        {"max_bytes": "-1"},
    ],
)
def test_invalid_compression_fields_have_stable_error(
    fields: dict[str, str]
) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/compress", files=image_fields("compress", **fields)
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_compression_request"


@pytest.mark.parametrize("format", ["png", "bmp", "tiff"])
def test_quality_on_unsupported_target_uses_image_conversion_error(
    format: str,
) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/compress",
        files=image_fields("compress", format=format, quality="60"),
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "unsupported_image_conversion",
        "message": "The image conversion is not supported.",
    }


def test_impossible_maximum_size_uses_invalid_image_request() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/compress",
        files=image_fields("compress", max_bytes="1"),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_image_request"


@pytest.mark.parametrize("path", ["convert", "resize", "compress"])
def test_corrupt_image_returns_safe_processing_error(path: str) -> None:
    extra = {"max_width": "10"} if path == "resize" else {}
    if path == "compress":
        extra = {"max_bytes": "1000"}
    response = TestClient(create_app()).post(
        f"/api/v1/images/{path}",
        files=image_fields(path, content=b"not an image", **extra),
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "image_processing_failed",
        "message": "The image could not be processed.",
    }
    assert "Pillow" not in response.text
    assert "docuforge-" not in response.text
    assert "traceback" not in response.text.lower()


def test_images_to_pdf_corrupt_image_returns_safe_processing_error() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/to-pdf",
        files={"files": ("broken.png", b"not an image", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "image_processing_failed"
    assert "broken.png" not in response.text


@pytest.mark.parametrize(
    ("path", "field_name"),
    [("convert", "file"), ("resize", "file"), ("compress", "file"), ("to-pdf", "files")],
)
def test_unsupported_source_extension_uses_transport_contract(
    path: str, field_name: str
) -> None:
    fields = [(field_name, ("photo.gif", make_image(), "image/png"))]
    if path != "to-pdf":
        fields.append(("format", (None, "png")))
    if path == "resize":
        fields.append(("max_width", (None, "10")))
    if path == "compress":
        fields.append(("max_bytes", (None, "1000")))

    response = TestClient(create_app()).post(f"/api/v1/images/{path}", files=fields)

    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_file_extension"


def test_image_to_pdf_preserves_narrow_existing_format_set() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/to-pdf",
        files={"files": ("photo.webp", make_image("WEBP"), "image/webp")},
    )

    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_file_extension"


def test_oversized_single_image_uses_transport_limit() -> None:
    settings = ApiSettings(
        max_upload_file_bytes=100,
        max_upload_request_bytes=200,
        upload_chunk_bytes=16,
    )
    response = TestClient(create_app(settings)).post(
        "/api/v1/images/convert",
        files=image_fields("convert"),
    )

    assert response.status_code == 413
    assert response.json()["code"] == "upload_too_large"


def test_too_many_images_to_pdf_uses_transport_limit() -> None:
    response = TestClient(create_app(ApiSettings(max_upload_files=2))).post(
        "/api/v1/images/to-pdf",
        files=[
            ("files", (f"{number}.png", make_image(), "image/png"))
            for number in range(3)
        ],
    )

    assert response.status_code == 413
    assert response.json()["code"] == "too_many_files"


def test_rejected_image_request_cleans_workspace(monkeypatch) -> None:
    created_paths: list[Path] = []

    class RecordingWorkspace(RequestWorkspace):
        def __init__(self) -> None:
            super().__init__()
            created_paths.append(self.path)

    monkeypatch.setattr("docuforge.api.routes.images.RequestWorkspace", RecordingWorkspace)
    response = TestClient(create_app()).post(
        "/api/v1/images/convert",
        files=image_fields("convert", content=b"not an image"),
    )

    assert response.status_code == 422
    assert len(created_paths) == 1
    assert not created_paths[0].exists()

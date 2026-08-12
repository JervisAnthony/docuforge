"""Product-level transport and safe-failure integration coverage."""

import pytest
from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from tests.api.image_test_support import make_image
from tests.api.pdf_test_support import make_pdf


@pytest.mark.parametrize(
    ("settings", "path", "files", "status_code", "code"),
    [
        (
            ApiSettings(
                max_upload_file_bytes=100,
                max_upload_request_bytes=200,
                upload_chunk_bytes=16,
            ),
            "/api/v1/pdf/split",
            {"file": ("input.pdf", make_pdf(100), "application/pdf")},
            413,
            "upload_too_large",
        ),
        (
            ApiSettings(max_upload_files=2),
            "/api/v1/pdf/merge",
            [
                ("files", (f"{number}.pdf", make_pdf(number), "application/pdf"))
                for number in range(3)
            ],
            413,
            "too_many_files",
        ),
        (
            ApiSettings(),
            "/api/v1/images/convert",
            [
                ("file", ("input.gif", make_image(), "image/png")),
                ("format", (None, "webp")),
            ],
            415,
            "unsupported_file_extension",
        ),
    ],
)
def test_representative_product_upload_limits(
    settings: ApiSettings,
    path: str,
    files,
    status_code: int,
    code: str,
) -> None:
    response = TestClient(create_app(settings)).post(path, files=files)

    assert response.status_code == status_code
    assert response.json()["code"] == code


@pytest.mark.parametrize(
    ("path", "files", "status_code", "code"),
    [
        (
            "/api/v1/pdf/split",
            {"file": ("broken.pdf", b"not a pdf", "application/pdf")},
            422,
            "pdf_processing_failed",
        ),
        (
            "/api/v1/images/convert",
            [
                ("file", ("broken.png", b"not an image", "image/png")),
                ("format", (None, "webp")),
            ],
            422,
            "image_processing_failed",
        ),
        (
            "/api/v1/images/compress",
            [
                ("file", ("input.png", make_image(), "image/png")),
                ("format", (None, "png")),
                ("max_bytes", (None, "1")),
            ],
            400,
            "invalid_image_request",
        ),
    ],
)
def test_processing_failures_expose_only_safe_contracts(
    path: str,
    files,
    status_code: int,
    code: str,
) -> None:
    response = TestClient(create_app()).post(path, files=files)

    assert response.status_code == status_code
    assert response.json()["code"] == code
    lowered = response.text.lower()
    assert "docuforge-" not in lowered
    assert "traceback" not in lowered
    assert "pillow" not in lowered
    assert "pdfium" not in lowered

"""Stable PDF HTTP error and transport-limit coverage."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from docuforge.api.workspace import RequestWorkspace
from tests.api.pdf_test_support import make_pdf


def _single_file_fields(
    operation_field: str,
    *values: str,
    content: bytes | None = None,
) -> list[tuple[str, tuple[str | None, bytes | str, str | None]]]:
    fields: list[tuple[str, tuple[str | None, bytes | str, str | None]]] = [
        (
            "file",
            ("report.pdf", make_pdf(100, 200, 300) if content is None else content, "application/pdf"),
        )
    ]
    fields.extend((operation_field, (None, value, None)) for value in values)
    return fields


@pytest.mark.parametrize(
    "value",
    ["", "2", "2:", ":90", "abc:90", "2:45", "0:90", "2:90:extra"],
)
def test_malformed_rotation_is_rejected_with_stable_error(value: str) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/rotate",
        files=_single_file_fields("rotate", value),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_rotation"


def test_duplicate_rotation_page_is_rejected() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/rotate",
        files=_single_file_fields("rotate", "2:90", "2:180"),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_rotation"


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("rotate", "invalid_rotation"),
        ("remove-pages", "invalid_page_selection"),
        ("extract-pages", "invalid_page_selection"),
    ],
)
def test_missing_operation_fields_are_rejected(path: str, code: str) -> None:
    response = TestClient(create_app()).post(
        f"/api/v1/pdf/{path}",
        files={"file": ("report.pdf", make_pdf(100), "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == code


@pytest.mark.parametrize("path", ["remove-pages", "extract-pages"])
@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5", " 1"])
def test_invalid_page_selection_is_rejected(path: str, value: str) -> None:
    response = TestClient(create_app()).post(
        f"/api/v1/pdf/{path}",
        files=_single_file_fields("page", value),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_page_selection"


@pytest.mark.parametrize("path", ["remove-pages", "extract-pages"])
def test_duplicate_page_selection_is_rejected(path: str) -> None:
    response = TestClient(create_app()).post(
        f"/api/v1/pdf/{path}",
        files=_single_file_fields("page", "2", "2"),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_page_selection"


@pytest.mark.parametrize(
    ("path", "field", "value"),
    [
        ("rotate", "rotate", "4:90"),
        ("remove-pages", "page", "4"),
        ("extract-pages", "page", "4"),
    ],
)
def test_out_of_range_pages_use_safe_invalid_request_mapping(
    path: str,
    field: str,
    value: str,
) -> None:
    response = TestClient(create_app()).post(
        f"/api/v1/pdf/{path}",
        files=_single_file_fields(field, value),
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "invalid_pdf_request",
        "message": "The PDF request is invalid.",
    }


def test_remove_every_page_follows_converter_validation() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/remove-pages",
        files=_single_file_fields("page", "1", "2", "3"),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_pdf_request"


@pytest.mark.parametrize(
    ("path", "fields"),
    [
        ("merge", None),
        ("split", None),
        ("rotate", ("rotate", "1:90")),
        ("remove-pages", ("page", "1")),
        ("extract-pages", ("page", "1")),
    ],
)
def test_corrupt_pdf_returns_safe_stable_error(
    path: str,
    fields: tuple[str, str] | None,
) -> None:
    if path == "merge":
        files = [
            ("files", ("broken.pdf", b"not a pdf", "application/pdf")),
            ("files", ("valid.pdf", make_pdf(100), "application/pdf")),
        ]
    elif fields is None:
        files = [("file", ("broken.pdf", b"not a pdf", "application/pdf"))]
    else:
        files = _single_file_fields(fields[0], fields[1], content=b"not a pdf")

    response = TestClient(create_app()).post(f"/api/v1/pdf/{path}", files=files)

    assert response.status_code == 422
    assert response.json() == {
        "code": "pdf_processing_failed",
        "message": "The PDF document could not be processed.",
    }
    assert "broken.pdf" not in response.text
    assert "PdfProcessingError" not in response.text
    assert "docuforge-" not in response.text
    assert "traceback" not in response.text.lower()


def test_encrypted_pdf_returns_safe_processing_error() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/split",
        files={"file": ("private.pdf", make_pdf(100, encrypted=True), "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "pdf_processing_failed"
    assert "private.pdf" not in response.text
    assert "password" not in response.text.lower()


def test_merge_requires_at_least_two_files() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/merge",
        files={"files": ("only.pdf", make_pdf(100), "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_pdf_request"


def test_single_file_operations_reject_repeated_file_fields() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/split",
        files=[
            ("file", ("first.pdf", make_pdf(100), "application/pdf")),
            ("file", ("second.pdf", make_pdf(200), "application/pdf")),
        ],
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_pdf_request"


def test_non_pdf_extension_is_rejected_without_trusting_mime_type() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/split",
        files={"file": ("report.txt", make_pdf(100), "application/pdf")},
    )

    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_file_extension"


def test_oversized_pdf_upload_uses_transport_limit() -> None:
    settings = ApiSettings(
        max_upload_file_bytes=100,
        max_upload_request_bytes=200,
        upload_chunk_bytes=16,
    )
    response = TestClient(create_app(settings)).post(
        "/api/v1/pdf/split",
        files={"file": ("large.pdf", make_pdf(100), "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "upload_too_large"


def test_too_many_merge_files_uses_transport_limit() -> None:
    settings = ApiSettings(max_upload_files=2)
    response = TestClient(create_app(settings)).post(
        "/api/v1/pdf/merge",
        files=[
            ("files", (f"{number}.pdf", make_pdf(number * 100), "application/pdf"))
            for number in range(1, 4)
        ],
    )

    assert response.status_code == 413
    assert response.json()["code"] == "too_many_files"


def test_rejected_request_cleans_workspace(monkeypatch) -> None:
    created_paths: list[Path] = []

    class RecordingWorkspace(RequestWorkspace):
        def __init__(self) -> None:
            super().__init__()
            created_paths.append(self.path)

    monkeypatch.setattr("docuforge.api.routes.pdf.RequestWorkspace", RecordingWorkspace)
    response = TestClient(create_app()).post(
        "/api/v1/pdf/split",
        files={"file": ("broken.pdf", b"not a pdf", "application/pdf")},
    )

    assert response.status_code == 422
    assert len(created_paths) == 1
    assert not created_paths[0].exists()


def test_converter_validation_failure_cleans_workspace(monkeypatch) -> None:
    created_paths: list[Path] = []

    class RecordingWorkspace(RequestWorkspace):
        def __init__(self) -> None:
            super().__init__()
            created_paths.append(self.path)

    monkeypatch.setattr("docuforge.api.routes.pdf.RequestWorkspace", RecordingWorkspace)
    response = TestClient(create_app()).post(
        "/api/v1/pdf/extract-pages",
        files=_single_file_fields("page", "4"),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_pdf_request"
    assert len(created_paths) == 1
    assert not created_paths[0].exists()

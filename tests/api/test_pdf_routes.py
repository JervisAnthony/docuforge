"""Successful PDF HTTP operation and OpenAPI coverage."""

import ast
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from docuforge.api import create_app
from docuforge.api.workspace import RequestWorkspace
from tests.api.pdf_test_support import make_pdf, page_rotations, page_widths


def test_merge_two_pdfs_preserves_file_and_page_order() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/merge",
        files=[
            ("files", ("first.pdf", make_pdf(101, 102), "text/plain")),
            ("files", ("second.pdf", make_pdf(201, 202), "image/png")),
        ],
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="merged.pdf"'
    assert page_widths(response.content) == [101, 102, 201, 202]


def test_merge_three_pdfs_and_uppercase_extension() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/merge",
        files=[
            ("files", ("one.PDF", make_pdf(100), "application/octet-stream")),
            ("files", ("two.pdf", make_pdf(200), "application/pdf")),
            ("files", ("three.pdf", make_pdf(300), "application/pdf")),
        ],
    )

    assert response.status_code == 200
    assert page_widths(response.content) == [100, 200, 300]


@pytest.mark.parametrize(
    ("widths", "expected_members"),
    [
        ((123,), ["report-page-0001.pdf"]),
        (
            (101, 202, 303),
            [
                "report-page-0001.pdf",
                "report-page-0002.pdf",
                "report-page-0003.pdf",
            ],
        ),
    ],
)
def test_split_returns_deterministic_safe_one_page_members(
    widths: tuple[int, ...],
    expected_members: list[str],
) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/split",
        files={"file": ("../../report.pdf", make_pdf(*widths), "application/pdf")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == (
        'attachment; filename="report-pages.zip"'
    )
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == expected_members
        assert all(not Path(name).is_absolute() and ".." not in name for name in archive.namelist())
        assert [page_widths(archive.read(name)) for name in archive.namelist()] == [
            [width] for width in widths
        ]
        assert all("docuforge-" not in name for name in archive.namelist())


def test_split_removes_parent_markers_from_derived_archive_names() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/split",
        files={"file": ("../../..report.pdf", make_pdf(123), "application/pdf")},
    )

    assert response.status_code == 200
    assert ".." not in response.headers["content-disposition"]
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == ["_report-page-0001.pdf"]
        assert ".." not in archive.namelist()[0]


def test_rotate_uses_one_based_pages_and_preserves_page_order() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/rotate",
        files=[
            ("file", ("report.pdf", make_pdf(101, 202, 303), "application/pdf")),
            ("rotate", (None, "1:90")),
            ("rotate", (None, "2:180")),
        ],
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="report-rotated.pdf"'
    )
    assert page_widths(response.content) == [101, 202, 303]
    assert page_rotations(response.content) == [90, 180, 0]


def test_rotate_page_two_by_270_leaves_other_pages_unchanged() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/rotate",
        files=[
            ("file", ("report.pdf", make_pdf(100, 200), "application/pdf")),
            ("rotate", (None, "2:270")),
        ],
    )

    assert response.status_code == 200
    assert page_rotations(response.content) == [0, 270]


def test_remove_pages_accepts_request_order_and_retains_source_order() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/remove-pages",
        files=[
            ("file", ("report.pdf", make_pdf(100, 200, 300, 400, 500), "application/pdf")),
            ("page", (None, "4")),
            ("page", (None, "2")),
        ],
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="report-trimmed.pdf"'
    )
    assert page_widths(response.content) == [100, 300, 500]


def test_extract_pages_preserves_exact_request_order() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/pdf/extract-pages",
        files=[
            ("file", ("report.pdf", make_pdf(100, 200, 300, 400, 500), "application/pdf")),
            ("page", (None, "4")),
            ("page", (None, "2")),
            ("page", (None, "5")),
        ],
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="report-extracted.pdf"'
    )
    assert page_widths(response.content) == [400, 200, 500]


def test_successful_pdf_download_cleans_workspace_after_consumption(monkeypatch) -> None:
    created_paths: list[Path] = []

    class RecordingWorkspace(RequestWorkspace):
        def __init__(self) -> None:
            super().__init__()
            created_paths.append(self.path)

    monkeypatch.setattr("docuforge.api.routes.pdf.RequestWorkspace", RecordingWorkspace)
    response = TestClient(create_app()).post(
        "/api/v1/pdf/merge",
        files=[
            ("files", ("first.pdf", make_pdf(100), "application/pdf")),
            ("files", ("second.pdf", make_pdf(200), "application/pdf")),
        ],
    )

    assert response.status_code == 200
    assert len(created_paths) == 1
    assert not created_paths[0].exists()


def test_openapi_documents_all_pdf_routes_and_binary_media_types() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    expected_media_types = {
        "/api/v1/pdf/merge": "application/pdf",
        "/api/v1/pdf/split": "application/zip",
        "/api/v1/pdf/rotate": "application/pdf",
        "/api/v1/pdf/remove-pages": "application/pdf",
        "/api/v1/pdf/extract-pages": "application/pdf",
    }

    for path, media_type in expected_media_types.items():
        assert set(schema["paths"][path]) == {"post"}
        content = schema["paths"][path]["post"]["responses"]["200"]["content"]
        assert media_type in content


def test_production_api_pdf_code_does_not_import_pypdf() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src" / "docuforge" / "api"
    for source_path in source_root.rglob("*.py"):
        syntax_tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules = {
            alias.name
            for node in ast.walk(syntax_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_modules.update(
            node.module
            for node in ast.walk(syntax_tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert not any(
            module == "pypdf" or module.startswith("pypdf.")
            for module in imported_modules
        ), f"direct PDF implementation dependency in {source_path}"

"""Successful image HTTP workflow and OpenAPI coverage."""

import ast
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from docuforge.api import create_app
from docuforge.api.workspace import RequestWorkspace
from tests.api.image_test_support import inspect_image, make_image


@pytest.mark.parametrize(
    ("source_format", "source_suffix", "target", "expected_format"),
    [
        ("JPEG", ".jpg", "png", "PNG"),
        ("PNG", ".png", "jpeg", "JPEG"),
        ("PNG", ".png", "webp", "WEBP"),
        ("WEBP", ".webp", "png", "PNG"),
        ("BMP", ".bmp", "tiff", "TIFF"),
        ("TIFF", ".tiff", "png", "PNG"),
        ("PNG", ".png", "PNG", "PNG"),
    ],
)
def test_convert_route_encodes_actual_requested_format(
    source_format: str,
    source_suffix: str,
    target: str,
    expected_format: str,
) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/convert",
        files=[
            ("file", (f"photo{source_suffix}", make_image(source_format), "text/plain")),
            ("format", (None, target)),
        ],
    )

    assert response.status_code == 200
    assert inspect_image(response.content)[0] == expected_format
    expected_suffix = {"JPEG": "jpg", "TIFF": "tiff"}.get(
        expected_format, expected_format.lower()
    )
    assert response.headers["content-disposition"] == (
        f'attachment; filename="photo-converted.{expected_suffix}"'
    )


def test_convert_route_accepts_uppercase_source_and_target_alias() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/convert",
        files=[
            ("file", ("PHOTO.PNG", make_image(), "application/octet-stream")),
            ("format", (None, "JPEG")),
        ],
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert inspect_image(response.content)[0] == "JPEG"


def test_convert_download_name_uses_safe_client_basename() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/convert",
        files=[
            ("file", ("../../..photo.png", make_image(), "image/png")),
            ("format", (None, "webp")),
        ],
    )

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition == 'attachment; filename="_photo-converted.webp"'
    assert "docuforge-" not in disposition
    assert ".." not in disposition


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"max_width": "60"}, (60, 40)),
        ({"max_height": "20"}, (30, 20)),
        ({"max_width": "70", "max_height": "30"}, (45, 30)),
    ],
)
def test_resize_route_preserves_aspect_ratio(
    fields: dict[str, str], expected: tuple[int, int]
) -> None:
    multipart = [
        ("file", ("photo.png", make_image(), "image/png")),
        ("format", (None, "png")),
        *((name, (None, value)) for name, value in fields.items()),
    ]
    response = TestClient(create_app()).post("/api/v1/images/resize", files=multipart)

    assert response.status_code == 200
    assert inspect_image(response.content)[:2] == ("PNG", expected)
    assert response.headers["content-disposition"] == (
        'attachment; filename="photo-resized.png"'
    )


def test_resize_route_does_not_upscale_without_explicit_true() -> None:
    client = TestClient(create_app())
    fields = [
        ("file", ("photo.png", make_image(size=(12, 8)), "image/png")),
        ("format", (None, "webp")),
        ("max_width", (None, "24")),
    ]
    unchanged = client.post("/api/v1/images/resize", files=fields)
    enlarged = client.post(
        "/api/v1/images/resize",
        files=[*fields, ("allow_upscale", (None, "TrUe"))],
    )

    assert inspect_image(unchanged.content)[1] == (12, 8)
    assert inspect_image(enlarged.content)[1] == (24, 16)


@pytest.mark.parametrize(("target", "quality"), [("jpg", "20"), ("jpg", "95"), ("webp", "60")])
def test_compress_route_fixed_quality_retains_dimensions(
    target: str, quality: str
) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/compress",
        files=[
            ("file", ("photo.png", make_image(), "image/png")),
            ("format", (None, target)),
            ("quality", (None, quality)),
        ],
    )

    assert response.status_code == 200
    expected_format = "JPEG" if target == "jpg" else "WEBP"
    assert inspect_image(response.content)[:2] == (expected_format, (120, 80))
    assert response.headers["content-type"] == f"image/{'jpeg' if target == 'jpg' else 'webp'}"


@pytest.mark.parametrize(
    ("target", "max_bytes", "expected_format"),
    [("jpg", 2500, "JPEG"), ("webp", 1800, "WEBP"), ("png", 3500, "PNG")],
)
def test_compress_route_enforces_actual_maximum_bytes(
    target: str, max_bytes: int, expected_format: str
) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/compress",
        files=[
            ("file", ("photo.png", make_image(), "image/png")),
            ("format", (None, target)),
            ("max_bytes", (None, str(max_bytes))),
        ],
    )

    assert response.status_code == 200
    assert len(response.content) <= max_bytes
    assert inspect_image(response.content)[0] == expected_format
    assert response.headers["content-disposition"].endswith(
        f'photo-compressed.{"jpg" if target == "jpg" else target}"'
    )


def test_images_to_pdf_one_image_returns_parseable_pdf() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/to-pdf",
        files={"files": ("photo.png", make_image(), "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="images.pdf"'
    assert len(PdfReader(BytesIO(response.content), strict=True).pages) == 1


def test_images_to_pdf_preserves_multipart_order_and_orientation() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/to-pdf",
        files=[
            ("files", ("portrait.PNG", make_image(size=(40, 80)), "image/png")),
            ("files", ("landscape.JPG", make_image("JPEG", size=(120, 60)), "image/jpeg")),
        ],
    )

    assert response.status_code == 200
    reader = PdfReader(BytesIO(response.content), strict=True)
    assert len(reader.pages) == 2
    first, second = reader.pages
    assert float(first.mediabox.height) > float(first.mediabox.width)
    assert float(second.mediabox.width) > float(second.mediabox.height)


def test_images_to_pdf_flattens_alpha_using_existing_converter_semantics() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/images/to-pdf",
        files={
            "files": ("transparent.png", make_image(mode="RGBA"), "image/png")
        },
    )

    assert response.status_code == 200
    assert len(PdfReader(BytesIO(response.content), strict=True).pages) == 1


def test_successful_image_download_cleans_workspace(monkeypatch) -> None:
    created_paths: list[Path] = []

    class RecordingWorkspace(RequestWorkspace):
        def __init__(self) -> None:
            super().__init__()
            created_paths.append(self.path)

    monkeypatch.setattr("docuforge.api.routes.images.RequestWorkspace", RecordingWorkspace)
    response = TestClient(create_app()).post(
        "/api/v1/images/convert",
        files=[
            ("file", ("photo.png", make_image(), "image/png")),
            ("format", (None, "webp")),
        ],
    )

    assert response.status_code == 200
    assert len(created_paths) == 1
    assert not created_paths[0].exists()


def test_openapi_documents_new_routes_and_preserves_existing_routes() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    new_paths = {
        "/api/v1/images/convert",
        "/api/v1/images/resize",
        "/api/v1/images/compress",
        "/api/v1/images/to-pdf",
        "/api/v1/pdf/to-images",
    }
    existing_paths = {
        "/api/v1/pdf/merge",
        "/api/v1/pdf/split",
        "/api/v1/pdf/rotate",
        "/api/v1/pdf/remove-pages",
        "/api/v1/pdf/extract-pages",
    }

    assert all(set(schema["paths"][path]) == {"post"} for path in new_paths)
    assert existing_paths <= set(schema["paths"])
    assert not any(path.endswith(("/upload", "/files", "/jobs", "/tasks")) for path in schema["paths"])


def test_production_api_has_no_image_or_pdf_render_implementation_imports() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src" / "docuforge" / "api"
    forbidden = {"PIL", "Pillow", "pypdfium2"}
    for source_path in source_root.rglob("*.py"):
        syntax_tree = ast.parse(source_path.read_text(encoding="utf-8"))
        modules = {
            alias.name
            for node in ast.walk(syntax_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        modules.update(
            node.module
            for node in ast.walk(syntax_tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert not any(
            module in forbidden or any(module.startswith(f"{name}.") for name in forbidden)
            for module in modules
        ), f"implementation dependency in {source_path}"

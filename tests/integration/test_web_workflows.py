"""Binary-semantic integration coverage for every web workflow."""

from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

from docuforge.api import create_app
from tests.api.image_test_support import inspect_image, make_image
from tests.api.pdf_test_support import make_pdf, page_rotations, page_widths


def _client() -> TestClient:
    return TestClient(create_app())


def test_merge_preserves_document_and_page_order() -> None:
    response = _client().post(
        "/api/v1/pdf/merge",
        files=[
            ("files", ("one.pdf", make_pdf(100, 110), "application/pdf")),
            ("files", ("two.pdf", make_pdf(200), "application/pdf")),
        ],
    )

    assert response.status_code == 200
    assert page_widths(response.content) == [100, 110, 200]


def test_split_returns_one_valid_pdf_per_page() -> None:
    response = _client().post(
        "/api/v1/pdf/split",
        files={"file": ("source.pdf", make_pdf(100, 200, 300), "application/pdf")},
    )

    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 3
        assert [page_widths(archive.read(name)) for name in archive.namelist()] == [
            [100],
            [200],
            [300],
        ]


def test_rotate_changes_only_selected_page_metadata() -> None:
    response = _client().post(
        "/api/v1/pdf/rotate",
        files=[
            ("file", ("source.pdf", make_pdf(100, 200, 300), "application/pdf")),
            ("rotate", (None, "2:90")),
        ],
    )

    assert response.status_code == 200
    assert page_rotations(response.content) == [0, 90, 0]


def test_remove_pages_retains_source_order() -> None:
    response = _client().post(
        "/api/v1/pdf/remove-pages",
        files=[
            ("file", ("source.pdf", make_pdf(100, 200, 300), "application/pdf")),
            ("page", (None, "2")),
        ],
    )

    assert response.status_code == 200
    assert page_widths(response.content) == [100, 300]


def test_extract_pages_preserves_requested_order() -> None:
    response = _client().post(
        "/api/v1/pdf/extract-pages",
        files=[
            ("file", ("source.pdf", make_pdf(100, 200, 300), "application/pdf")),
            ("page", (None, "3")),
            ("page", (None, "1")),
        ],
    )

    assert response.status_code == 200
    assert page_widths(response.content) == [300, 100]


def test_pdf_to_images_returns_decodable_png_per_page() -> None:
    response = _client().post(
        "/api/v1/pdf/to-images",
        files=[
            ("file", ("source.pdf", make_pdf(100, 200), "application/pdf")),
            ("format", (None, "png")),
            ("dpi", (None, "72")),
        ],
    )

    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 2
        for name in archive.namelist():
            with Image.open(BytesIO(archive.read(name))) as image:
                image.load()
                assert image.format == "PNG"


def test_convert_returns_the_requested_encoded_format() -> None:
    response = _client().post(
        "/api/v1/images/convert",
        files=[
            ("file", ("source.png", make_image(), "image/png")),
            ("format", (None, "webp")),
        ],
    )

    assert response.status_code == 200
    assert inspect_image(response.content)[:2] == ("WEBP", (120, 80))


def test_resize_preserves_aspect_ratio() -> None:
    response = _client().post(
        "/api/v1/images/resize",
        files=[
            ("file", ("source.png", make_image(size=(160, 90)), "image/png")),
            ("format", (None, "png")),
            ("max_width", (None, "80")),
        ],
    )

    assert response.status_code == 200
    assert inspect_image(response.content)[:2] == ("PNG", (80, 45))


def test_quality_compression_returns_valid_jpeg_at_original_dimensions() -> None:
    response = _client().post(
        "/api/v1/images/compress",
        files=[
            ("file", ("source.png", make_image(size=(160, 90)), "image/png")),
            ("format", (None, "jpeg")),
            ("quality", (None, "55")),
        ],
    )

    assert response.status_code == 200
    assert inspect_image(response.content)[:2] == ("JPEG", (160, 90))


def test_maximum_size_compression_obeys_strict_limit() -> None:
    maximum_bytes = 3_500
    response = _client().post(
        "/api/v1/images/compress",
        files=[
            ("file", ("source.png", make_image(), "image/png")),
            ("format", (None, "png")),
            ("max_bytes", (None, str(maximum_bytes))),
        ],
    )

    assert response.status_code == 200
    assert len(response.content) <= maximum_bytes
    assert inspect_image(response.content)[0] == "PNG"


def test_images_to_pdf_preserves_page_order_and_orientation() -> None:
    response = _client().post(
        "/api/v1/images/to-pdf",
        files=[
            ("files", ("portrait.png", make_image(size=(40, 80)), "image/png")),
            ("files", ("landscape.png", make_image(size=(120, 60)), "image/png")),
        ],
    )

    assert response.status_code == 200
    reader = PdfReader(BytesIO(response.content), strict=True)
    assert len(reader.pages) == 2
    assert float(reader.pages[0].mediabox.height) > float(
        reader.pages[0].mediabox.width
    )
    assert float(reader.pages[1].mediabox.width) > float(
        reader.pages[1].mediabox.height
    )

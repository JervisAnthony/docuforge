"""Tests for bounded transactional PDF page rendering."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from pypdf import PdfWriter

import docuforge.converters as converters_package
from docuforge.converters.pdf import (
    PdfProcessingError,
    PdfToImagesPathRequest,
    pdf_to_images_path,
)
from docuforge.core import DocumentFormat, InvalidConversionRequestError


def write_pdf(
    path: Path,
    *page_sizes: tuple[int, int],
    encrypted: bool = False,
    rotation: int | None = None,
) -> None:
    writer = PdfWriter()
    for width, height in page_sizes:
        page = writer.add_blank_page(width=width, height=height)
        if rotation is not None:
            page.rotate(rotation)
    if encrypted:
        writer.encrypt("secret")
    with path.open("wb") as output:
        writer.write(output)
    writer.close()


def inspect(path: Path) -> tuple[str | None, tuple[int, int], tuple[int, ...]]:
    with Image.open(path) as image:
        image.load()
        return image.format, image.size, image.convert("RGB").getpixel((0, 0))


def test_public_models_are_immutable_slotted_and_normalize_aliases() -> None:
    request = PdfToImagesPathRequest(
        Path("input.pdf"), Path("pages"), "JPEG", dpi=72  # type: ignore[arg-type]
    )

    assert request.output_format is DocumentFormat.JPG
    assert not hasattr(request, "__dict__")
    with pytest.raises(FrozenInstanceError):
        request.dpi = 100  # type: ignore[misc]


@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "72"])
def test_request_rejects_invalid_dpi(value: object) -> None:
    with pytest.raises((TypeError, InvalidConversionRequestError)):
        PdfToImagesPathRequest(
            Path("input.pdf"), Path("pages"), DocumentFormat.PNG, dpi=value  # type: ignore[arg-type]
        )


def test_request_rejects_dpi_above_hard_limit() -> None:
    with pytest.raises(InvalidConversionRequestError, match="600"):
        PdfToImagesPathRequest(
            Path("input.pdf"), Path("pages"), DocumentFormat.PNG, dpi=601
        )


@pytest.mark.parametrize("field", ["max_pages", "max_pixels_per_page"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1"])
def test_request_rejects_invalid_limits(field: str, value: object) -> None:
    with pytest.raises((TypeError, InvalidConversionRequestError)):
        PdfToImagesPathRequest(
            Path("input.pdf"),
            Path("pages"),
            DocumentFormat.PNG,
            **{field: value},  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("output_format", [DocumentFormat.PDF, DocumentFormat.GIF])
def test_request_rejects_unsupported_output_formats(
    output_format: DocumentFormat,
) -> None:
    with pytest.raises(InvalidConversionRequestError):
        PdfToImagesPathRequest(Path("input.pdf"), Path("pages"), output_format)


def test_one_page_render_has_exact_72_dpi_dimensions_and_white_background(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    write_pdf(source, (72, 144))

    result = pdf_to_images_path(
        PdfToImagesPathRequest(source, tmp_path / "pages", DocumentFormat.PNG, dpi=72)
    )

    assert result.page_count == 1
    assert result.output_paths == (tmp_path / "pages" / "page-0001.png",)
    assert inspect(result.output_paths[0]) == ("PNG", (72, 144), (255, 255, 255))


def test_multiple_pages_preserve_order_and_distinct_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    write_pdf(source, (72, 144), (144, 72), (100, 200))

    result = pdf_to_images_path(
        PdfToImagesPathRequest(source, tmp_path / "pages", DocumentFormat.PNG, dpi=72)
    )

    assert [inspect(path)[1] for path in result.output_paths] == [
        (72, 144),
        (144, 72),
        (100, 200),
    ]
    assert [path.name for path in result.output_paths] == [
        "page-0001.png",
        "page-0002.png",
        "page-0003.png",
    ]


@pytest.mark.parametrize(
    ("output_format", "expected_format", "expected_suffix"),
    [
        (DocumentFormat.JPG, "JPEG", ".jpg"),
        (DocumentFormat.PNG, "PNG", ".png"),
        (DocumentFormat.WEBP, "WEBP", ".webp"),
        (DocumentFormat.BMP, "BMP", ".bmp"),
        (DocumentFormat.TIFF, "TIFF", ".tiff"),
    ],
)
def test_all_supported_formats_reopen_as_actual_encoded_format(
    tmp_path: Path,
    output_format: DocumentFormat,
    expected_format: str,
    expected_suffix: str,
) -> None:
    source = tmp_path / "source.pdf"
    write_pdf(source, (80, 60))

    result = pdf_to_images_path(
        PdfToImagesPathRequest(source, tmp_path / "pages", output_format, dpi=72)
    )

    assert result.output_paths[0].suffix == expected_suffix
    assert inspect(result.output_paths[0])[:2] == (expected_format, (80, 60))


def test_higher_dpi_scales_dimensions_proportionally(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    write_pdf(source, (72, 144))

    result = pdf_to_images_path(
        PdfToImagesPathRequest(source, tmp_path / "pages", DocumentFormat.PNG, dpi=144)
    )

    assert inspect(result.output_paths[0])[1] == (144, 288)


def test_intrinsic_page_rotation_is_reflected_in_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    write_pdf(source, (72, 144), rotation=90)

    result = pdf_to_images_path(
        PdfToImagesPathRequest(source, tmp_path / "pages", DocumentFormat.PNG, dpi=72)
    )

    assert inspect(result.output_paths[0])[1] == (144, 72)


def test_page_count_limit_is_enforced_before_rendering(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    write_pdf(source, (72, 72), (72, 72))

    with patch(
        "docuforge.converters.pdf.to_images_path._render_page"
    ) as render_page, pytest.raises(InvalidConversionRequestError, match="page count"):
        pdf_to_images_path(
            PdfToImagesPathRequest(
                source,
                tmp_path / "pages",
                DocumentFormat.PNG,
                max_pages=1,
            )
        )

    render_page.assert_not_called()
    assert not (tmp_path / "pages").exists()


def test_pixel_limit_is_enforced_before_rendering(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    write_pdf(source, (100, 100))

    with patch(
        "docuforge.converters.pdf.to_images_path._render_page"
    ) as render_page, pytest.raises(InvalidConversionRequestError, match="pixel"):
        pdf_to_images_path(
            PdfToImagesPathRequest(
                source,
                tmp_path / "pages",
                DocumentFormat.PNG,
                dpi=72,
                max_pixels_per_page=9_999,
            )
        )

    render_page.assert_not_called()
    assert not (tmp_path / "pages").exists()


@pytest.mark.parametrize("content", [b"", b"not a pdf", b"%PDF truncated"])
def test_corrupt_pdf_uses_stable_processing_error(
    tmp_path: Path, content: bytes
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(content)

    with pytest.raises(PdfProcessingError, match="Unable to render"):
        pdf_to_images_path(
            PdfToImagesPathRequest(source, tmp_path / "pages", DocumentFormat.PNG)
        )
    assert not (tmp_path / "pages").exists()


def test_encrypted_pdf_uses_stable_processing_error(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    write_pdf(source, (72, 72), encrypted=True)

    with pytest.raises(PdfProcessingError, match="Unable to render"):
        pdf_to_images_path(
            PdfToImagesPathRequest(source, tmp_path / "pages", DocumentFormat.PNG)
        )


def test_page_failure_leaves_no_partial_directory_or_temp_sibling(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    write_pdf(source, (72, 72), (72, 72))
    real_render = converters_package.pdf_to_images_path.__globals__["_render_page"]

    def fail_second_page(*args: object, **kwargs: object) -> None:
        if args[1] == 1:
            raise OSError("injected page failure")
        real_render(*args, **kwargs)

    with patch(
        "docuforge.converters.pdf.to_images_path._render_page",
        side_effect=fail_second_page,
    ), pytest.raises(PdfProcessingError):
        pdf_to_images_path(
            PdfToImagesPathRequest(source, tmp_path / "pages", DocumentFormat.PNG)
        )

    assert not (tmp_path / "pages").exists()
    assert list(tmp_path.glob(".pages.*.tmp")) == []


def test_existing_output_directory_is_preserved(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "pages"
    output.mkdir()
    marker = output / "unrelated.txt"
    marker.write_text("keep", encoding="utf-8")
    write_pdf(source, (72, 72))

    with pytest.raises(InvalidConversionRequestError, match="must not already exist"):
        pdf_to_images_path(
            PdfToImagesPathRequest(source, output, DocumentFormat.PNG)
        )

    assert marker.read_text(encoding="utf-8") == "keep"


def test_public_package_export_performs_real_render(tmp_path: Path) -> None:
    source = tmp_path / "source.PDF"
    write_pdf(source, (72, 72))

    result = converters_package.pdf_to_images_path(
        converters_package.PdfToImagesPathRequest(
            source, tmp_path / "pages", DocumentFormat.PNG, dpi=72
        )
    )

    assert result.output_paths[0].is_file()

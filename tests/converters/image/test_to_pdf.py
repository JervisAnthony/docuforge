"""Tests for image-to-PDF conversion."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image
from pypdf import PdfReader

from docuforge.converters import (
    ImageInput,
    ImageProcessingError,
    ImageToPdfConverter,
    ImageToPdfRequest,
)
from docuforge.core import (
    ConversionOperation,
    ConverterRegistry,
    DocumentFormat,
    InvalidConversionRequestError,
)


def write_image(
    path: Path,
    image_format: str,
    mode: str = "RGB",
    size: tuple[int, int] = (40, 20),
    color: object = "red",
) -> None:
    """Write a generated image in the requested mode and format."""
    image = Image.new(mode, size, color)
    try:
        image.save(path, format=image_format)
    finally:
        image.close()


def image_request(
    images: tuple[tuple[Path, DocumentFormat], ...],
    output_path: Path,
) -> ImageToPdfRequest:
    """Create an image-to-PDF request from path/format pairs."""
    return ImageToPdfRequest(
        images=tuple(ImageInput(path, image_format) for path, image_format in images),
        output_path=output_path,
    )


def page_sizes(path: Path) -> list[tuple[float, float]]:
    """Return PDF page dimensions in request order."""
    return [
        (float(page.mediabox.width), float(page.mediabox.height))
        for page in PdfReader(path).pages
    ]


@pytest.mark.parametrize(
    "source_format",
    [
        DocumentFormat.JPG,
        DocumentFormat.PNG,
        DocumentFormat.BMP,
        DocumentFormat.TIFF,
    ],
)
def test_converter_identity(source_format: DocumentFormat) -> None:
    converter = ImageToPdfConverter(source_format)

    assert converter.operation is ConversionOperation.CONVERT
    assert converter.source_format is source_format
    assert converter.target_format is DocumentFormat.PDF


def test_convert_one_jpg_returns_output_and_preserves_dimensions(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    output = tmp_path / "output.pdf"
    write_image(input_path, "JPEG", size=(40, 20))

    result = ImageToPdfConverter().convert(
        image_request(((input_path, DocumentFormat.JPG),), output)
    )

    assert result == output
    assert page_sizes(output) == [(40, 20)]


def test_convert_multiple_jpgs_preserves_input_order(tmp_path: Path) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    third = tmp_path / "third.jpg"
    output = tmp_path / "output.pdf"
    write_image(first, "JPEG", size=(10, 20))
    write_image(second, "JPEG", size=(30, 40))
    write_image(third, "JPEG", size=(50, 60))

    ImageToPdfConverter().convert(
        image_request(
            (
                (first, DocumentFormat.JPG),
                (second, DocumentFormat.JPG),
                (third, DocumentFormat.JPG),
            ),
            output,
        )
    )

    assert page_sizes(output) == [(10, 20), (30, 40), (50, 60)]


def test_convert_mixed_jpg_and_png_inputs(tmp_path: Path) -> None:
    jpg = tmp_path / "first.jpg"
    png = tmp_path / "second.png"
    output = tmp_path / "output.pdf"
    write_image(jpg, "JPEG", size=(20, 30))
    write_image(png, "PNG", size=(40, 50))

    ImageToPdfConverter().convert(
        image_request(
            ((jpg, DocumentFormat.JPG), (png, DocumentFormat.PNG)),
            output,
        )
    )

    assert page_sizes(output) == [(20, 30), (40, 50)]


@pytest.mark.parametrize(
    ("image_format", "document_format", "suffix"),
    [
        ("BMP", DocumentFormat.BMP, ".bmp"),
        ("TIFF", DocumentFormat.TIFF, ".tiff"),
    ],
)
def test_convert_bmp_and_tiff_inputs(
    tmp_path: Path,
    image_format: str,
    document_format: DocumentFormat,
    suffix: str,
) -> None:
    input_path = tmp_path / f"input{suffix}"
    output = tmp_path / "output.pdf"
    write_image(input_path, image_format, size=(25, 35))

    ImageToPdfConverter(document_format).convert(
        image_request(((input_path, document_format),), output)
    )

    assert page_sizes(output) == [(25, 35)]


@pytest.mark.parametrize(
    ("mode", "color"),
    [
        ("RGB", "red"),
        ("L", 128),
        ("RGBA", (255, 0, 0, 128)),
        ("P", 1),
    ],
)
def test_convert_supported_image_modes(tmp_path: Path, mode: str, color: object) -> None:
    input_path = tmp_path / f"input-{mode}.png"
    output = tmp_path / f"output-{mode}.pdf"
    write_image(input_path, "PNG", mode=mode, color=color)

    ImageToPdfConverter(DocumentFormat.PNG).convert(
        image_request(((input_path, DocumentFormat.PNG),), output)
    )

    assert page_sizes(output) == [(40, 20)]


def test_transparency_is_flattened_against_white(tmp_path: Path) -> None:
    input_path = tmp_path / "transparent.png"
    image = Image.new("RGBA", (2, 1), (255, 0, 0, 255))
    try:
        image.putpixel((1, 0), (0, 0, 255, 0))
        image.save(input_path, format="PNG")
    finally:
        image.close()

    page = ImageToPdfConverter._load_page(ImageInput(input_path, DocumentFormat.PNG))
    try:
        assert page.mode == "RGB"
        assert page.getpixel((0, 0)) == (255, 0, 0)
        assert page.getpixel((1, 0)) == (255, 255, 255)
    finally:
        page.close()


def test_exif_orientation_is_applied_before_pdf_creation(tmp_path: Path) -> None:
    input_path = tmp_path / "oriented.jpg"
    output = tmp_path / "output.pdf"
    image = Image.new("RGB", (40, 20), "red")
    exif = Image.Exif()
    exif[274] = 6
    try:
        image.save(input_path, format="JPEG", exif=exif)
    finally:
        image.close()

    ImageToPdfConverter().convert(
        image_request(((input_path, DocumentFormat.JPG),), output)
    )

    assert page_sizes(output) == [(20, 40)]


def test_exif_transposed_intermediate_image_is_closed(tmp_path: Path) -> None:
    input_path = tmp_path / "oriented.jpg"
    write_image(input_path, "JPEG")
    oriented = MagicMock(spec=Image.Image)
    oriented.mode = "RGB"
    converted = Image.new("RGB", (40, 20), "red")
    oriented.convert.return_value = converted

    try:
        with patch(
            "docuforge.converters.image.to_pdf.ImageOps.exif_transpose",
            return_value=oriented,
        ):
            result = ImageToPdfConverter._load_page(
                ImageInput(input_path, DocumentFormat.JPG)
            )

        assert result is converted
        oriented.close.assert_called_once_with()
    finally:
        converted.close()


def test_conversion_replaces_existing_output(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    output = tmp_path / "output.pdf"
    write_image(input_path, "JPEG", size=(40, 20))
    output.write_bytes(b"old output")

    ImageToPdfConverter().convert(
        image_request(((input_path, DocumentFormat.JPG),), output)
    )

    assert page_sizes(output) == [(40, 20)]


def test_request_rejects_no_input_images(tmp_path: Path) -> None:
    with pytest.raises(InvalidConversionRequestError):
        ImageToPdfRequest(images=(), output_path=tmp_path / "output.pdf")


def test_conversion_rejects_missing_input(tmp_path: Path) -> None:
    with pytest.raises(InvalidConversionRequestError):
        ImageToPdfConverter().convert(
            image_request(
                ((tmp_path / "missing.jpg", DocumentFormat.JPG),),
                tmp_path / "output.pdf",
            )
        )


def test_conversion_rejects_directory_input(tmp_path: Path) -> None:
    input_directory = tmp_path / "input"
    input_directory.mkdir()

    with pytest.raises(InvalidConversionRequestError):
        ImageToPdfConverter(DocumentFormat.PNG).convert(
            image_request(
                ((input_directory, DocumentFormat.PNG),),
                tmp_path / "output.pdf",
            )
        )


def test_conversion_translates_malformed_image_error(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    output = tmp_path / "output.pdf"
    input_path.write_bytes(b"not an image")

    with pytest.raises(ImageProcessingError) as exc_info:
        ImageToPdfConverter().convert(
            image_request(((input_path, DocumentFormat.JPG),), output)
        )

    assert exc_info.value.__cause__ is not None
    assert not output.exists()


def test_request_rejects_gif_as_unsupported(tmp_path: Path) -> None:
    with pytest.raises(InvalidConversionRequestError, match="Unsupported image format"):
        ImageInput(tmp_path / "input.gif", DocumentFormat.GIF)


def test_conversion_rejects_declared_format_mismatch(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    write_image(input_path, "PNG")

    with pytest.raises(InvalidConversionRequestError, match="does not match"):
        ImageToPdfConverter().convert(
            image_request(((input_path, DocumentFormat.JPG),), tmp_path / "output.pdf")
        )


def test_conversion_rejects_duplicate_resolved_inputs(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    nested = tmp_path / "nested"
    write_image(input_path, "JPEG")
    nested.mkdir()

    with pytest.raises(InvalidConversionRequestError, match="resolve to the same"):
        ImageToPdfConverter().convert(
            image_request(
                (
                    (input_path, DocumentFormat.JPG),
                    (nested / ".." / input_path.name, DocumentFormat.JPG),
                ),
                tmp_path / "output.pdf",
            )
        )


def test_conversion_rejects_missing_output_parent(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    write_image(input_path, "JPEG")

    with pytest.raises(InvalidConversionRequestError):
        ImageToPdfConverter().convert(
            image_request(
                ((input_path, DocumentFormat.JPG),),
                tmp_path / "missing" / "output.pdf",
            )
        )


def test_conversion_rejects_output_resolving_to_input(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    nested = tmp_path / "nested"
    write_image(input_path, "JPEG")
    nested.mkdir()

    with pytest.raises(InvalidConversionRequestError):
        ImageToPdfConverter().convert(
            image_request(
                ((input_path, DocumentFormat.JPG),),
                nested / ".." / input_path.name,
            )
        )


def test_conversion_rejects_directory_output(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    output_directory = tmp_path / "output"
    write_image(input_path, "JPEG")
    output_directory.mkdir()

    with pytest.raises(InvalidConversionRequestError):
        ImageToPdfConverter().convert(
            image_request(((input_path, DocumentFormat.JPG),), output_directory)
        )


def test_write_failure_preserves_output_and_removes_temporary_file(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    output = tmp_path / "output.pdf"
    write_image(input_path, "JPEG")
    output.write_bytes(b"old output")
    write_error = OSError("write failed")

    with (
        patch("PIL.Image.Image.save", side_effect=write_error),
        pytest.raises(ImageProcessingError) as exc_info,
    ):
        ImageToPdfConverter().convert(
            image_request(((input_path, DocumentFormat.JPG),), output)
        )

    assert exc_info.value.__cause__ is write_error
    assert output.read_bytes() == b"old output"
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_replace_failure_preserves_output_and_removes_temporary_file(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    output = tmp_path / "output.pdf"
    write_image(input_path, "JPEG")
    output.write_bytes(b"old output")
    replace_error = OSError("replace failed")

    with (
        patch("docuforge.converters.image.to_pdf.os.replace", side_effect=replace_error),
        pytest.raises(ImageProcessingError) as exc_info,
    ):
        ImageToPdfConverter().convert(
            image_request(((input_path, DocumentFormat.JPG),), output)
        )

    assert exc_info.value.__cause__ is replace_error
    assert output.read_bytes() == b"old output"
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_all_converted_pages_are_closed_after_success(tmp_path: Path) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    output = tmp_path / "output.pdf"
    write_image(first, "JPEG")
    write_image(second, "JPEG")
    converter = ImageToPdfConverter()
    created_pages: list[Image.Image] = []
    load_page = converter._load_page

    def track_page(image_input: ImageInput) -> Image.Image:
        page = load_page(image_input)
        created_pages.append(page)
        return page

    with patch.object(converter, "_load_page", side_effect=track_page):
        converter.convert(
            image_request(
                (
                    (first, DocumentFormat.JPG),
                    (second, DocumentFormat.JPG),
                ),
                output,
            )
        )

    assert len(created_pages) == 2
    for page in created_pages:
        with pytest.raises(ValueError, match="closed image"):
            page.getpixel((0, 0))


def test_later_malformed_input_closes_prior_page_and_leaves_no_artifacts(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "valid.jpg"
    malformed = tmp_path / "malformed.jpg"
    output = tmp_path / "output.pdf"
    write_image(valid, "JPEG")
    malformed.write_bytes(b"not an image")
    converter = ImageToPdfConverter()
    created_pages: list[Image.Image] = []
    load_page = converter._load_page

    def track_page(image_input: ImageInput) -> Image.Image:
        page = load_page(image_input)
        created_pages.append(page)
        return page

    with (
        patch.object(converter, "_load_page", side_effect=track_page),
        pytest.raises(ImageProcessingError) as exc_info,
    ):
        converter.convert(
            image_request(
                (
                    (valid, DocumentFormat.JPG),
                    (malformed, DocumentFormat.JPG),
                ),
                output,
            )
        )

    assert exc_info.value.__cause__ is not None
    assert len(created_pages) == 1
    with pytest.raises(ValueError, match="closed image"):
        created_pages[0].getpixel((0, 0))
    assert not output.exists()
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_registry_lookup_uses_leading_image_format(tmp_path: Path) -> None:
    input_path = tmp_path / "input.png"
    request = image_request(
        ((input_path, DocumentFormat.PNG),),
        tmp_path / "output.pdf",
    )
    registry = ConverterRegistry()
    converter = ImageToPdfConverter(DocumentFormat.PNG)

    registry.register(converter)

    assert registry.get_converter_for(request) is converter

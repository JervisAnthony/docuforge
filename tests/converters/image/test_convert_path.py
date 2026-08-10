"""Tests for reusable path-based raster format conversion."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

import docuforge.converters as converters_package
import docuforge.converters.image as image_package
from docuforge.converters.image import (
    ImageConvertPathRequest,
    ImageConvertPathResult,
    ImageProcessingError,
    convert_image_path,
)
from docuforge.core import (
    DocumentFormat,
    InvalidConversionRequestError,
    InvalidFormatError,
    UnsupportedConversionError,
)

PILLOW_NAME = {
    DocumentFormat.JPG: "JPEG",
    DocumentFormat.PNG: "PNG",
    DocumentFormat.WEBP: "WEBP",
    DocumentFormat.BMP: "BMP",
    DocumentFormat.TIFF: "TIFF",
}


def write_image(
    path: Path,
    image_format: str,
    *,
    mode: str = "RGB",
    color: object = (200, 50, 20),
    size: tuple[int, int] = (8, 6),
) -> None:
    """Write one small deterministic synthetic image."""
    image = Image.new(mode, size, color)
    try:
        image.save(path, format=image_format)
    finally:
        image.close()


def inspect_image(path: Path) -> tuple[str | None, tuple[int, int], str]:
    """Return decoded output identity after forcing a complete load."""
    with Image.open(path) as image:
        image.load()
        return image.format, image.size, image.mode


def test_path_models_are_frozen_slotted_and_preserve_paths() -> None:
    input_path = Path("source.png")
    output_path = Path("result.webp")
    request = ImageConvertPathRequest(input_path, output_path)
    result = ImageConvertPathResult(
        input_path,
        output_path,
        DocumentFormat.PNG,
        DocumentFormat.WEBP,
    )

    assert request.input_path is input_path
    assert request.output_path is output_path
    assert result.input_path is input_path
    assert result.output_path is output_path
    assert not hasattr(request, "__dict__")
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        request.output_path = Path("other.png")  # type: ignore[misc]


@pytest.mark.parametrize("model_type", [ImageConvertPathRequest, ImageConvertPathResult])
def test_path_models_require_path_instances(model_type: type[object]) -> None:
    arguments: tuple[object, ...] = ("source.png", Path("output.jpg"))
    if model_type is ImageConvertPathResult:
        arguments += (DocumentFormat.PNG, DocumentFormat.JPG)

    with pytest.raises(TypeError, match="input_path must be a Path object"):
        model_type(*arguments)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("jpg", DocumentFormat.JPG),
        ("jpeg", DocumentFormat.JPG),
        ("JPG", DocumentFormat.JPG),
        (".JPEG", DocumentFormat.JPG),
        ("png", DocumentFormat.PNG),
        (".PnG", DocumentFormat.PNG),
        ("webp", DocumentFormat.WEBP),
        (".WEBP", DocumentFormat.WEBP),
        ("bmp", DocumentFormat.BMP),
        (".BMP", DocumentFormat.BMP),
        ("tif", DocumentFormat.TIFF),
        (".TIF", DocumentFormat.TIFF),
        ("tiff", DocumentFormat.TIFF),
        (".TIFF", DocumentFormat.TIFF),
    ],
)
def test_supported_format_aliases_normalize(
    value: str,
    expected: DocumentFormat,
) -> None:
    assert DocumentFormat.normalize(value) is expected


@pytest.mark.parametrize("value", ["svg", "ico", "heic"])
def test_unsupported_format_names_reject(value: str) -> None:
    with pytest.raises(InvalidFormatError):
        DocumentFormat.normalize(value)


@pytest.mark.parametrize(
    ("source_format", "source_suffix", "target_suffix", "expected_target"),
    [
        (DocumentFormat.JPG, ".jpg", ".png", DocumentFormat.PNG),
        (DocumentFormat.PNG, ".png", ".jpg", DocumentFormat.JPG),
        (DocumentFormat.PNG, ".png", ".webp", DocumentFormat.WEBP),
        (DocumentFormat.PNG, ".png", ".bmp", DocumentFormat.BMP),
        (DocumentFormat.PNG, ".png", ".tiff", DocumentFormat.TIFF),
        (DocumentFormat.WEBP, ".webp", ".png", DocumentFormat.PNG),
        (DocumentFormat.BMP, ".bmp", ".jpeg", DocumentFormat.JPG),
        (DocumentFormat.TIFF, ".tif", ".png", DocumentFormat.PNG),
        (DocumentFormat.JPG, ".jpeg", ".webp", DocumentFormat.WEBP),
    ],
)
def test_representative_conversion_matrix(
    tmp_path: Path,
    source_format: DocumentFormat,
    source_suffix: str,
    target_suffix: str,
    expected_target: DocumentFormat,
) -> None:
    input_path = tmp_path / f"source{source_suffix}"
    output_path = tmp_path / f"result{target_suffix}"
    write_image(input_path, PILLOW_NAME[source_format])

    result = convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert result == ImageConvertPathResult(
        input_path,
        output_path,
        source_format,
        expected_target,
    )
    assert inspect_image(output_path) == (
        PILLOW_NAME[expected_target],
        (8, 6),
        "RGB",
    )
    with Image.open(output_path) as converted:
        converted.load()
        red, green, blue = converted.convert("RGB").getpixel((4, 3))
        assert red > 150
        assert green < 100
        assert blue < 80


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        (".JPG", "JPEG"),
        (".JPEG", "JPEG"),
        (".PNG", "PNG"),
        (".WEBP", "WEBP"),
        (".BMP", "BMP"),
        (".TIF", "TIFF"),
        (".TIFF", "TIFF"),
    ],
)
def test_uppercase_output_aliases_select_actual_encoder(
    tmp_path: Path,
    suffix: str,
    expected: str,
) -> None:
    input_path = tmp_path / "source.data"
    output_path = tmp_path / f"result{suffix}"
    write_image(input_path, "PNG")

    convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert inspect_image(output_path)[0] == expected


def test_misleading_input_extension_uses_decoded_content(tmp_path: Path) -> None:
    input_path = tmp_path / "actually-png.jpg"
    output_path = tmp_path / "result.bmp"
    write_image(input_path, "PNG")

    result = convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert result.source_format is DocumentFormat.PNG
    assert result.target_format is DocumentFormat.BMP
    assert inspect_image(output_path)[0] == "BMP"


def test_same_format_conversion_is_a_supported_reencode(tmp_path: Path) -> None:
    input_path = tmp_path / "source.png"
    output_path = tmp_path / "reencoded.png"
    write_image(input_path, "PNG", size=(9, 7))

    result = convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert result.source_format is DocumentFormat.PNG
    assert result.target_format is DocumentFormat.PNG
    assert output_path != input_path
    assert inspect_image(output_path) == ("PNG", (9, 7), "RGB")


@pytest.mark.parametrize("target_suffix", [".png", ".webp"])
def test_alpha_capable_outputs_preserve_transparency(
    tmp_path: Path,
    target_suffix: str,
) -> None:
    input_path = tmp_path / "transparent.png"
    output_path = tmp_path / f"result{target_suffix}"
    image = Image.new("RGBA", (2, 1), (255, 0, 0, 255))
    try:
        image.putpixel((1, 0), (0, 0, 255, 0))
        image.save(input_path, format="PNG")
    finally:
        image.close()

    convert_image_path(ImageConvertPathRequest(input_path, output_path))

    with Image.open(output_path) as converted:
        converted.load()
        rgba = converted.convert("RGBA")
        try:
            assert rgba.getpixel((0, 0))[3] >= 250
            assert rgba.getpixel((1, 0))[3] <= 5
        finally:
            rgba.close()


@pytest.mark.parametrize("target_suffix", [".jpg", ".bmp"])
def test_non_alpha_outputs_flatten_transparency_against_white(
    tmp_path: Path,
    target_suffix: str,
) -> None:
    input_path = tmp_path / "transparent.png"
    output_path = tmp_path / f"result{target_suffix}"
    image = Image.new("RGBA", (20, 10), (255, 0, 0, 255))
    try:
        for x in range(10, 20):
            for y in range(10):
                image.putpixel((x, y), (0, 0, 255, 0))
        image.save(input_path, format="PNG")
    finally:
        image.close()

    convert_image_path(ImageConvertPathRequest(input_path, output_path))

    with Image.open(output_path) as converted:
        converted.load()
        assert converted.mode == "RGB"
        opaque = converted.getpixel((3, 5))
        transparent = converted.getpixel((16, 5))
        assert opaque[0] > 220 and opaque[1] < 40 and opaque[2] < 40
        assert all(channel > 235 for channel in transparent)


def test_palette_transparency_is_preserved_in_png(tmp_path: Path) -> None:
    input_path = tmp_path / "palette.png"
    output_path = tmp_path / "result.png"
    image = Image.new("P", (2, 1))
    image.putpalette([255, 0, 0, 0, 0, 255] + [0, 0, 0] * 254)
    image.putdata([0, 1])
    image.info["transparency"] = 1
    try:
        image.save(input_path, format="PNG", transparency=1)
    finally:
        image.close()

    convert_image_path(ImageConvertPathRequest(input_path, output_path))

    with Image.open(output_path) as converted:
        converted.load()
        assert converted.convert("RGBA").getpixel((1, 0))[3] == 0


@pytest.mark.parametrize(
    ("mode", "color", "target_suffix"),
    [
        ("RGB", (1, 2, 3), ".png"),
        ("RGBA", (1, 2, 3, 4), ".tiff"),
        ("L", 128, ".jpg"),
        ("LA", (128, 64), ".webp"),
        ("P", 1, ".png"),
    ],
)
def test_representative_color_modes_convert(
    tmp_path: Path,
    mode: str,
    color: object,
    target_suffix: str,
) -> None:
    input_path = tmp_path / f"source-{mode}.png"
    output_path = tmp_path / f"result-{mode}{target_suffix}"
    write_image(input_path, "PNG", mode=mode, color=color)

    convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert inspect_image(output_path)[1] == (8, 6)


def test_cmyk_jpeg_converts_to_rgb_png(tmp_path: Path) -> None:
    input_path = tmp_path / "source.jpg"
    output_path = tmp_path / "result.png"
    write_image(input_path, "JPEG", mode="CMYK", color=(0, 255, 255, 0))

    convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert inspect_image(output_path) == ("PNG", (8, 6), "RGB")


def test_exif_orientation_is_materialized_into_output_pixels(tmp_path: Path) -> None:
    input_path = tmp_path / "oriented.jpg"
    output_path = tmp_path / "oriented.png"
    image = Image.new("RGB", (40, 20), "red")
    for x in range(20, 40):
        for y in range(20):
            image.putpixel((x, y), (0, 0, 255))
    exif = Image.Exif()
    exif[274] = 6
    try:
        image.save(input_path, format="JPEG", exif=exif)
    finally:
        image.close()

    convert_image_path(ImageConvertPathRequest(input_path, output_path))

    with Image.open(output_path) as converted:
        converted.load()
        assert converted.size == (20, 40)
        top = converted.convert("RGB").getpixel((10, 5))
        bottom = converted.convert("RGB").getpixel((10, 35))
        assert top[0] > 200 and top[2] < 50
        assert bottom[2] > 200 and bottom[0] < 50


def test_multiframe_tiff_is_rejected_without_output(tmp_path: Path) -> None:
    input_path = tmp_path / "multipage.tiff"
    output_path = tmp_path / "result.png"
    first = Image.new("RGB", (4, 3), "red")
    second = Image.new("RGB", (4, 3), "blue")
    try:
        first.save(input_path, format="TIFF", save_all=True, append_images=[second])
    finally:
        first.close()
        second.close()

    with pytest.raises(UnsupportedConversionError, match="single-frame"):
        convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert not output_path.exists()


def test_animated_webp_is_rejected_when_encoder_supports_it(tmp_path: Path) -> None:
    input_path = tmp_path / "animated.webp"
    output_path = tmp_path / "result.png"
    first = Image.new("RGB", (4, 3), "red")
    second = Image.new("RGB", (4, 3), "blue")
    try:
        try:
            first.save(
                input_path,
                format="WEBP",
                save_all=True,
                append_images=[second],
                duration=100,
                loop=0,
            )
        except OSError:
            pytest.skip("installed Pillow build cannot encode animated WebP")
    finally:
        first.close()
        second.close()

    with Image.open(input_path) as animated:
        if getattr(animated, "n_frames", 1) == 1:
            pytest.skip("installed Pillow build encoded only one WebP frame")
    with pytest.raises(UnsupportedConversionError, match="single-frame"):
        convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert not output_path.exists()


@pytest.mark.parametrize("content", [b"", b"not an image", b"\x89PNG\r\n\x1a\ntruncated"])
def test_corrupt_inputs_raise_processing_error_without_partial_output(
    tmp_path: Path,
    content: bytes,
) -> None:
    input_path = tmp_path / "broken.png"
    output_path = tmp_path / "result.jpg"
    input_path.write_bytes(content)

    with pytest.raises(ImageProcessingError) as captured:
        convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert str(captured.value) == "Unable to convert the requested raster image."
    assert captured.value.__cause__ is not None
    assert not output_path.exists()
    assert list(tmp_path.glob(f".{output_path.name}.*")) == []


def test_valid_gif_is_rejected_as_unsupported_source(tmp_path: Path) -> None:
    input_path = tmp_path / "source.gif"
    output_path = tmp_path / "result.png"
    write_image(input_path, "GIF")

    with pytest.raises(UnsupportedConversionError, match="source image format"):
        convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert not output_path.exists()


@pytest.mark.parametrize("suffix", [".svg", ".gif", ".ico", ""])
def test_unsupported_output_suffix_is_rejected(
    tmp_path: Path,
    suffix: str,
) -> None:
    input_path = tmp_path / "source.png"
    output_path = tmp_path / f"result{suffix}"
    write_image(input_path, "PNG")

    with pytest.raises(UnsupportedConversionError, match="Output file must use"):
        convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert not output_path.exists()


def test_missing_and_directory_inputs_are_invalid_requests(tmp_path: Path) -> None:
    missing = tmp_path / "missing.png"
    directory = tmp_path / "directory.png"
    directory.mkdir()

    with pytest.raises(InvalidConversionRequestError, match="does not exist"):
        convert_image_path(
            ImageConvertPathRequest(missing, tmp_path / "missing-output.jpg")
        )
    with pytest.raises(InvalidConversionRequestError, match="not a file"):
        convert_image_path(
            ImageConvertPathRequest(directory, tmp_path / "directory-output.jpg")
        )


def test_output_parent_must_exist_and_is_not_created(tmp_path: Path) -> None:
    input_path = tmp_path / "source.png"
    missing_parent = tmp_path / "missing"
    write_image(input_path, "PNG")

    with pytest.raises(InvalidConversionRequestError, match="parent directory"):
        convert_image_path(
            ImageConvertPathRequest(input_path, missing_parent / "result.jpg")
        )

    assert not missing_parent.exists()


def test_directory_output_is_invalid_request(tmp_path: Path) -> None:
    input_path = tmp_path / "source.png"
    output_path = tmp_path / "result.png"
    write_image(input_path, "PNG")
    output_path.mkdir()

    with pytest.raises(InvalidConversionRequestError, match="is a directory"):
        convert_image_path(ImageConvertPathRequest(input_path, output_path))


def test_same_resolved_path_is_rejected_without_changing_source(tmp_path: Path) -> None:
    input_path = tmp_path / "source.png"
    nested = tmp_path / "nested"
    nested.mkdir()
    write_image(input_path, "PNG")
    original_bytes = input_path.read_bytes()
    alias = nested / ".." / input_path.name

    with pytest.raises(InvalidConversionRequestError, match="resolve to the input"):
        convert_image_path(ImageConvertPathRequest(input_path, alias))

    assert input_path.read_bytes() == original_bytes


def test_successful_conversion_atomically_replaces_existing_output(tmp_path: Path) -> None:
    input_path = tmp_path / "source.png"
    output_path = tmp_path / "result.jpg"
    write_image(input_path, "PNG", size=(11, 9))
    output_path.write_bytes(b"existing output")

    convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert inspect_image(output_path) == ("JPEG", (11, 9), "RGB")
    assert list(tmp_path.glob(f".{output_path.name}.*")) == []


def test_encoder_failure_preserves_existing_output_and_removes_temporary_file(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "source.png"
    output_path = tmp_path / "result.jpg"
    write_image(input_path, "PNG")
    output_path.write_bytes(b"existing output")
    failure = OSError("encoder failed")

    with (
        patch("PIL.Image.Image.save", side_effect=failure),
        pytest.raises(ImageProcessingError) as captured,
    ):
        convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert captured.value.__cause__ is failure
    assert output_path.read_bytes() == b"existing output"
    assert list(tmp_path.glob(f".{output_path.name}.*")) == []


def test_replace_failure_preserves_existing_output_and_removes_temporary_file(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "source.png"
    output_path = tmp_path / "result.jpg"
    write_image(input_path, "PNG")
    output_path.write_bytes(b"existing output")
    failure = OSError("replace failed")

    with (
        patch("docuforge.converters.image.convert_path.os.replace", side_effect=failure),
        pytest.raises(ImageProcessingError) as captured,
    ):
        convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert captured.value.__cause__ is failure
    assert output_path.read_bytes() == b"existing output"
    assert list(tmp_path.glob(f".{output_path.name}.*")) == []


@pytest.mark.parametrize(
    "failure",
    [
        Image.DecompressionBombError("image is too large"),
        Image.DecompressionBombWarning("image may be too large"),
    ],
)
def test_decompression_bomb_failure_uses_processing_contract(
    tmp_path: Path,
    failure: Exception,
) -> None:
    input_path = tmp_path / "source.png"
    output_path = tmp_path / "result.jpg"
    write_image(input_path, "PNG")
    with (
        patch("docuforge.converters.image.convert_path.Image.open", side_effect=failure),
        pytest.raises(ImageProcessingError) as captured,
    ):
        convert_image_path(ImageConvertPathRequest(input_path, output_path))

    assert captured.value.__cause__ is failure
    assert not output_path.exists()


def test_public_package_exports_perform_real_conversion(tmp_path: Path) -> None:
    input_path = tmp_path / "source.png"
    output_path = tmp_path / "result.jpg"
    write_image(input_path, "PNG")

    for package in (image_package, converters_package):
        assert package.ImageConvertPathRequest is ImageConvertPathRequest
        assert package.ImageConvertPathResult is ImageConvertPathResult
        assert package.convert_image_path is convert_image_path

    result = image_package.convert_image_path(
        image_package.ImageConvertPathRequest(input_path, output_path)
    )

    assert result.output_path == output_path
    assert inspect_image(output_path)[0] == "JPEG"
    assert "_FORMAT_BY_SUFFIX" not in image_package.__all__


def test_convert_requires_public_request_type() -> None:
    with pytest.raises(TypeError, match="ImageConvertPathRequest"):
        convert_image_path(object())  # type: ignore[arg-type]

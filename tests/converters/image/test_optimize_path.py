"""Tests for reusable path-based raster resizing and compression."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

import docuforge.converters as converters_package
import docuforge.converters.image.optimize_path as optimize_module
from docuforge.converters.image import (
    ImageCompressPathRequest,
    ImageProcessingError,
    ImageResizePathRequest,
    compress_image_path,
    resize_image_path,
)
from docuforge.core import InvalidConversionRequestError, UnsupportedConversionError


def write_image(
    path: Path,
    image_format: str = "PNG",
    *,
    mode: str = "RGB",
    size: tuple[int, int] = (120, 80),
) -> None:
    """Write a deterministic, nontrivial raster image."""
    image = Image.new(mode, size)
    for y in range(size[1]):
        for x in range(size[0]):
            if mode == "RGBA":
                color: int | tuple[int, ...] = (
                    x * 17 % 256,
                    y * 23 % 256,
                    (x + y) * 11 % 256,
                    96,
                )
            else:
                color = (x * 17 % 256, y * 23 % 256, (x + y) * 11 % 256)
            image.putpixel((x, y), color)
    try:
        image.save(path, format=image_format)
    finally:
        image.close()


def inspect(path: Path) -> tuple[str | None, tuple[int, int], str]:
    with Image.open(path) as image:
        image.load()
        return image.format, image.size, image.mode


def test_request_models_are_frozen_slotted_and_preserve_paths() -> None:
    source = Path("source.png")
    output = Path("output.webp")
    resize = ImageResizePathRequest(source, output, max_width=50)
    compress = ImageCompressPathRequest(source, output, quality=80)

    assert resize.input_path is source
    assert compress.output_path is output
    assert not hasattr(resize, "__dict__")
    assert not hasattr(compress, "__dict__")
    with pytest.raises(FrozenInstanceError):
        resize.max_width = 60  # type: ignore[misc]


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "10"])
def test_resize_rejects_invalid_dimensions(value: object) -> None:
    with pytest.raises((TypeError, InvalidConversionRequestError)):
        ImageResizePathRequest(Path("in.png"), Path("out.png"), max_width=value)  # type: ignore[arg-type]


def test_resize_requires_a_bound_and_boolean_upscale() -> None:
    with pytest.raises(InvalidConversionRequestError):
        ImageResizePathRequest(Path("in.png"), Path("out.png"))
    with pytest.raises(TypeError):
        ImageResizePathRequest(
            Path("in.png"), Path("out.png"), max_width=10, allow_upscale=1  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        ({"max_width": 60}, (60, 40)),
        ({"max_height": 20}, (30, 20)),
        ({"max_width": 70, "max_height": 30}, (45, 30)),
    ],
)
def test_resize_preserves_aspect_ratio(
    tmp_path: Path, bounds: dict[str, int], expected: tuple[int, int]
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    write_image(source)

    result = resize_image_path(ImageResizePathRequest(source, output, **bounds))

    assert result.input_dimensions == (120, 80)
    assert result.output_dimensions == expected
    assert result.output_size_bytes == output.stat().st_size
    assert inspect(output)[:2] == ("PNG", expected)


def test_resize_does_not_upscale_unless_requested(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    unchanged = tmp_path / "unchanged.png"
    enlarged = tmp_path / "enlarged.png"
    write_image(source, size=(12, 8))

    first = resize_image_path(ImageResizePathRequest(source, unchanged, max_width=24))
    second = resize_image_path(
        ImageResizePathRequest(source, enlarged, max_width=24, allow_upscale=True)
    )

    assert first.output_dimensions == (12, 8)
    assert second.output_dimensions == (24, 16)


@pytest.mark.parametrize(
    ("size", "bound", "expected"),
    [((60, 100), {"max_height": 50}, (30, 50)), ((40, 40), {"max_width": 20}, (20, 20))],
)
def test_resize_portrait_and_square_geometry(
    tmp_path: Path,
    size: tuple[int, int],
    bound: dict[str, int],
    expected: tuple[int, int],
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    write_image(source, size=size)

    result = resize_image_path(ImageResizePathRequest(source, output, **bound))

    assert result.output_dimensions == expected


def test_resize_never_rounds_a_dimension_to_zero(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    write_image(source, size=(100, 1))

    result = resize_image_path(ImageResizePathRequest(source, output, max_width=1))

    assert result.output_dimensions == (1, 1)


@pytest.mark.parametrize(
    ("suffix", "pillow_format"),
    [
        (".jpg", "JPEG"),
        (".png", "PNG"),
        (".webp", "WEBP"),
        (".bmp", "BMP"),
        (".tif", "TIFF"),
    ],
)
def test_resize_uses_destination_format(
    tmp_path: Path, suffix: str, pillow_format: str
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / f"output{suffix}"
    write_image(source)

    resize_image_path(ImageResizePathRequest(source, output, max_width=30))

    assert inspect(output)[:2] == (pillow_format, (30, 20))


def test_resize_preserves_or_flattens_transparency(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    png_output = tmp_path / "alpha.png"
    jpg_output = tmp_path / "flat.jpg"
    webp_output = tmp_path / "alpha.webp"
    bmp_output = tmp_path / "flat.bmp"
    write_image(source, mode="RGBA", size=(20, 10))

    resize_image_path(ImageResizePathRequest(source, png_output, max_width=10))
    resize_image_path(ImageResizePathRequest(source, jpg_output, max_width=10))
    resize_image_path(ImageResizePathRequest(source, webp_output, max_width=10))
    resize_image_path(ImageResizePathRequest(source, bmp_output, max_width=10))

    with Image.open(png_output) as png:
        assert "A" in png.getbands()
        assert png.getpixel((5, 2))[3] == 96
    with Image.open(jpg_output) as jpg:
        red, green, blue = jpg.convert("RGB").getpixel((5, 2))
        assert red > 100 and green > 100 and blue > 100
    with Image.open(webp_output) as webp:
        assert "A" in webp.getbands()
        assert abs(webp.getpixel((5, 2))[3] - 96) <= 2
    with Image.open(bmp_output) as bmp:
        red, green, blue = bmp.convert("RGB").getpixel((5, 2))
        assert red > 100 and green > 100 and blue > 100


def test_resize_applies_exif_orientation_before_geometry(tmp_path: Path) -> None:
    source = tmp_path / "rotated.jpg"
    output = tmp_path / "output.png"
    image = Image.new("RGB", (40, 20), "red")
    for x in range(20, 40):
        for y in range(20):
            image.putpixel((x, y), (0, 0, 255))
    exif = Image.Exif()
    exif[274] = 6
    image.save(source, format="JPEG", exif=exif)
    image.close()

    result = resize_image_path(ImageResizePathRequest(source, output, max_width=10))

    assert result.input_dimensions == (20, 40)
    assert result.output_dimensions == (10, 20)
    with Image.open(output) as oriented:
        top_red, _, top_blue = oriented.getpixel((5, 2))
        bottom_red, _, bottom_blue = oriented.getpixel((5, 17))
    assert top_red > top_blue
    assert bottom_blue > bottom_red


def test_resize_path_and_decode_failures_are_safe(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    write_image(source)
    original = source.read_bytes()
    with pytest.raises(InvalidConversionRequestError):
        resize_image_path(ImageResizePathRequest(source, source, max_width=30))
    with pytest.raises(UnsupportedConversionError):
        resize_image_path(
            ImageResizePathRequest(source, tmp_path / "output.gif", max_width=30)
        )
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not an image")
    with pytest.raises(ImageProcessingError):
        resize_image_path(
            ImageResizePathRequest(corrupt, tmp_path / "output.png", max_width=30)
        )
    assert source.read_bytes() == original


@pytest.mark.parametrize("quality", [1, 20, 60, 95])
@pytest.mark.parametrize(("suffix", "format_name"), [(".jpg", "JPEG"), (".webp", "WEBP")])
def test_fixed_quality_compression(
    tmp_path: Path, quality: int, suffix: str, format_name: str
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / f"output{suffix}"
    write_image(source)

    result = compress_image_path(
        ImageCompressPathRequest(source, output, quality=quality)
    )

    assert result.quality_used == quality
    assert result.input_dimensions == result.output_dimensions == (120, 80)
    assert result.output_size_bytes == output.stat().st_size
    assert inspect(output)[:2] == (format_name, (120, 80))


def test_fixed_quality_changes_encoded_size_on_textured_jpeg(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    low = tmp_path / "low.jpg"
    high = tmp_path / "high.jpg"
    write_image(source, size=(240, 160))

    compress_image_path(ImageCompressPathRequest(source, low, quality=20))
    compress_image_path(ImageCompressPathRequest(source, high, quality=95))

    assert low.stat().st_size < high.stat().st_size


def test_fixed_quality_webp_preserves_alpha(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.webp"
    write_image(source, mode="RGBA")

    compress_image_path(ImageCompressPathRequest(source, output, quality=60))

    with Image.open(output) as image:
        assert "A" in image.getbands()
        assert abs(image.getpixel((60, 40))[3] - 96) <= 2


@pytest.mark.parametrize("suffix", [".png", ".bmp", ".tiff"])
def test_fixed_quality_rejects_formats_without_quality_control(
    tmp_path: Path, suffix: str
) -> None:
    source = tmp_path / "source.png"
    write_image(source)
    with pytest.raises(UnsupportedConversionError):
        compress_image_path(
            ImageCompressPathRequest(source, tmp_path / f"output{suffix}", quality=60)
        )


@pytest.mark.parametrize("arguments", [{}, {"quality": 60, "max_bytes": 1000}])
def test_compression_requires_exactly_one_mode(arguments: dict[str, int]) -> None:
    with pytest.raises(InvalidConversionRequestError):
        ImageCompressPathRequest(Path("in.png"), Path("out.jpg"), **arguments)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quality", True),
        ("quality", 0),
        ("quality", 96),
        ("max_bytes", True),
        ("max_bytes", 0),
    ],
)
def test_compression_rejects_invalid_constraints(field: str, value: object) -> None:
    with pytest.raises((TypeError, InvalidConversionRequestError)):
        ImageCompressPathRequest(Path("in.png"), Path("out.jpg"), **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("suffix", "format_name", "target"),
    [
        (".jpg", "JPEG", 2500),
        (".webp", "WEBP", 1800),
        (".png", "PNG", 3500),
        (".bmp", "BMP", 3000),
        (".tiff", "TIFF", 4000),
    ],
)
def test_maximum_size_compression_meets_actual_byte_limit(
    tmp_path: Path, suffix: str, format_name: str, target: int
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / f"output{suffix}"
    write_image(source)

    result = compress_image_path(
        ImageCompressPathRequest(source, output, max_bytes=target)
    )

    assert 0 < output.stat().st_size <= target
    assert result.output_size_bytes == output.stat().st_size
    assert result.output_dimensions[0] <= 120
    assert result.output_dimensions[1] <= 80
    if suffix in {".jpg", ".webp"}:
        assert result.quality_used is not None
        assert 20 <= result.quality_used <= 95
    else:
        assert result.quality_used is None
    assert inspect(output)[0] == format_name


@pytest.mark.parametrize(("suffix", "target"), [(".jpg", 1000), (".webp", 700)])
def test_maximum_size_reduces_dimensions_when_quality_floor_cannot_fit(
    tmp_path: Path, suffix: str, target: int
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / f"output{suffix}"
    write_image(source, size=(300, 200))

    result = compress_image_path(
        ImageCompressPathRequest(source, output, max_bytes=target)
    )

    assert result.output_size_bytes <= target
    assert result.output_dimensions[0] < 300
    assert result.output_dimensions[1] < 200


@pytest.mark.parametrize(
    ("suffix", "target"), [(".png", 200), (".bmp", 1000), (".tiff", 1500)]
)
def test_nonquality_target_size_reduces_dimensions_when_needed(
    tmp_path: Path, suffix: str, target: int
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / f"output{suffix}"
    write_image(source, size=(300, 200))

    result = compress_image_path(
        ImageCompressPathRequest(source, output, max_bytes=target)
    )

    assert result.output_size_bytes <= target
    assert result.output_dimensions[0] < 300
    assert result.output_dimensions[1] < 200
    assert result.quality_used is None


@pytest.mark.parametrize(("suffix", "format_name"), [(".jpg", "JPEG"), (".webp", "WEBP")])
def test_generous_target_preserves_dimensions(
    tmp_path: Path, suffix: str, format_name: str
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / f"output{suffix}"
    write_image(source)

    result = compress_image_path(
        ImageCompressPathRequest(source, output, max_bytes=1_000_000)
    )

    assert result.output_dimensions == (120, 80)
    assert result.quality_used == 95
    assert inspect(output)[0] == format_name


def test_target_size_png_preserves_alpha_without_palette_conversion(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    write_image(source, mode="RGBA")

    result = compress_image_path(
        ImageCompressPathRequest(source, output, max_bytes=1_000_000)
    )

    assert result.output_dimensions == (120, 80)
    with Image.open(output) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((60, 40))[3] == 96


def test_target_size_webp_preserves_alpha(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.webp"
    write_image(source, mode="RGBA")

    result = compress_image_path(
        ImageCompressPathRequest(source, output, max_bytes=1_000_000)
    )

    assert result.output_dimensions == (120, 80)
    with Image.open(output) as image:
        assert "A" in image.getbands()
        assert abs(image.getpixel((60, 40))[3] - 96) <= 2


def test_misleading_source_suffix_uses_decoded_content(tmp_path: Path) -> None:
    source = tmp_path / "actually-png.jpg"
    output = tmp_path / "output.webp"
    write_image(source, "PNG")

    result = resize_image_path(ImageResizePathRequest(source, output, max_width=30))

    assert result.source_format.value == "png"
    assert result.target_format.value == "webp"


@pytest.mark.parametrize("operation", ["resize", "compress"])
def test_multiframe_tiff_is_rejected(tmp_path: Path, operation: str) -> None:
    source = tmp_path / "multi.tiff"
    output = tmp_path / "output.png"
    first = Image.new("RGB", (10, 10), "red")
    second = Image.new("RGB", (10, 10), "blue")
    first.save(source, format="TIFF", save_all=True, append_images=[second])
    first.close()
    second.close()

    with pytest.raises(UnsupportedConversionError):
        if operation == "resize":
            resize_image_path(ImageResizePathRequest(source, output, max_width=5))
        else:
            compress_image_path(
                ImageCompressPathRequest(source, output, max_bytes=1000)
            )
    assert not output.exists()


def test_animated_webp_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "animated.webp"
    output = tmp_path / "output.png"
    first = Image.new("RGB", (10, 10), "red")
    second = Image.new("RGB", (10, 10), "blue")
    try:
        try:
            first.save(
                source,
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
    with Image.open(source) as animated:
        if getattr(animated, "n_frames", 1) == 1:
            pytest.skip("installed Pillow build encoded only one WebP frame")

    with pytest.raises(UnsupportedConversionError, match="single-frame"):
        compress_image_path(
            ImageCompressPathRequest(source, output, max_bytes=1000)
        )


@pytest.mark.parametrize("suffix", [".jpg", ".webp", ".png", ".bmp", ".tiff"])
def test_impossible_target_without_destination_leaves_no_artifacts(
    tmp_path: Path, suffix: str
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / f"output{suffix}"
    write_image(source)

    with pytest.raises(InvalidConversionRequestError):
        compress_image_path(ImageCompressPathRequest(source, output, max_bytes=1))

    assert not output.exists()
    assert list(tmp_path.glob(f".{output.name}.*")) == []


def test_impossible_target_preserves_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    write_image(source)
    output.write_bytes(b"existing destination")

    with pytest.raises(InvalidConversionRequestError):
        compress_image_path(ImageCompressPathRequest(source, output, max_bytes=1))

    assert output.read_bytes() == b"existing destination"
    assert list(tmp_path.glob(".output.png.*")) == []


def test_replace_failure_preserves_destination_and_removes_temp(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    write_image(source)
    output.write_bytes(b"existing destination")

    with patch(
        "docuforge.converters.image.optimize_path.os.replace",
        side_effect=OSError("replace failed"),
    ), pytest.raises(ImageProcessingError):
        resize_image_path(ImageResizePathRequest(source, output, max_width=30))

    assert output.read_bytes() == b"existing destination"
    assert list(tmp_path.glob(".output.png.*")) == []


@pytest.mark.parametrize(
    "failure",
    [
        Image.DecompressionBombError("image is too large"),
        Image.DecompressionBombWarning("image may be too large"),
    ],
)
@pytest.mark.parametrize("operation", ["resize", "compress"])
def test_decompression_bomb_failures_use_processing_contract(
    tmp_path: Path, failure: Exception, operation: str
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.jpg"
    write_image(source)
    with (
        patch(
            "docuforge.converters.image.convert_path.Image.open",
            side_effect=failure,
        ),
        pytest.raises(ImageProcessingError) as captured,
    ):
        if operation == "resize":
            resize_image_path(ImageResizePathRequest(source, output, max_width=30))
        else:
            compress_image_path(
                ImageCompressPathRequest(source, output, quality=60)
            )
    assert captured.value.__cause__ is failure
    assert not output.exists()


@pytest.mark.parametrize("failure_point", ["encode", "validation"])
def test_pre_replace_failures_preserve_destination_and_remove_temp(
    tmp_path: Path, failure_point: str
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    write_image(source)
    output.write_bytes(b"existing destination")
    patch_target = (
        "docuforge.converters.image.optimize_path._encode"
        if failure_point == "encode"
        else "docuforge.converters.image.optimize_path._validate_encoded_output"
    )
    with patch(patch_target, side_effect=OSError("injected failure")), pytest.raises(
        ImageProcessingError
    ):
        resize_image_path(ImageResizePathRequest(source, output, max_width=30))

    assert output.read_bytes() == b"existing destination"
    assert list(tmp_path.glob(".output.png.*")) == []


def test_target_size_dimension_loop_is_hard_bounded(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    write_image(source)

    with (
        patch.object(optimize_module, "_MAX_DIMENSION_ATTEMPTS", 2),
        patch.object(optimize_module, "_encode", return_value=b"x" * 100) as encode,
        pytest.raises(InvalidConversionRequestError),
    ):
        compress_image_path(ImageCompressPathRequest(source, output, max_bytes=1))

    assert encode.call_count == 2
    assert not output.exists()


def test_public_top_level_exports_perform_optimization(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    resized = tmp_path / "resized.png"
    compressed = tmp_path / "compressed.jpg"
    write_image(source)

    resize_result = converters_package.resize_image_path(
        converters_package.ImageResizePathRequest(source, resized, max_width=30)
    )
    compress_result = converters_package.compress_image_path(
        converters_package.ImageCompressPathRequest(source, compressed, quality=70)
    )

    assert resize_result.output_dimensions == (30, 20)
    assert compress_result.quality_used == 70

"""Integration and trust-boundary tests for batch image processing."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

import docuforge.batch.image as image_module
from docuforge.batch import (
    BatchId,
    BatchImageCompressRequest,
    BatchImageConvertRequest,
    BatchImageInput,
    BatchImageResizeRequest,
    BatchProcessingError,
    BatchStatus,
    InvalidBatchDefinitionError,
    batch_compress_images,
    batch_convert_images,
    batch_resize_images,
)
from docuforge.converters.image import ImageConvertPathResult, ImageProcessingError
from docuforge.core import (
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)


def write_image(path: Path, image_format: str = "PNG", size: tuple[int, int] = (60, 40)) -> None:
    with Image.new("RGB", size, "cornflowerblue") as image:
        image.save(path, format=image_format)


def assert_no_workspace(directory: Path) -> None:
    assert list(directory.glob(".docuforge-batch-images-*")) == []


def test_convert_mixed_images_preserves_batch_identity_order_and_names(tmp_path: Path) -> None:
    sources = [tmp_path / "photo.jpg", tmp_path / "photo.png", tmp_path / "høliday.bmp"]
    for source, image_format in zip(sources, ("JPEG", "PNG", "BMP"), strict=True):
        write_image(source, image_format)
    output = tmp_path / "output"
    output.mkdir()
    batch_id = BatchId.new()
    inputs = tuple(BatchImageInput(path) for path in sources)

    result = batch_convert_images(
        BatchImageConvertRequest(inputs, output, DocumentFormat.WEBP, batch_id)
    )

    assert result.batch.id == batch_id
    assert result.batch.operation == "image.convert"
    assert result.batch.status is BatchStatus.COMPLETED
    assert [item.id for item in result.batch.items] == [item.id for item in inputs]
    assert [item.position for item in result.batch.items] == [0, 1, 2]
    assert [item.descriptor for item in result.batch.items] == [path.name for path in sources]
    assert [entry.output_path.name for entry in result.outputs] == [
        "0001-photo.webp",
        "0002-photo.webp",
        "0003-høliday.webp",
    ]
    assert [item.result.descriptor for item in result.batch.items] == [
        entry.output_path.name for entry in result.outputs
    ]
    for entry in result.outputs:
        with Image.open(entry.output_path) as converted:
            assert converted.format == "WEBP"
    assert_no_workspace(output)


def test_resize_propagates_bounds_and_upscale(tmp_path: Path) -> None:
    source = tmp_path / "small image.png"
    write_image(source, size=(30, 20))
    output = tmp_path / "output"
    output.mkdir()

    result = batch_resize_images(
        BatchImageResizeRequest(
            (BatchImageInput(source),),
            output,
            DocumentFormat.PNG,
            max_width=60,
            max_height=60,
            allow_upscale=True,
        )
    )

    assert result.batch.operation == "image.resize"
    assert result.outputs[0].output_path.name == "0001-small image.png"
    with Image.open(result.outputs[0].output_path) as resized:
        assert resized.size == (60, 40)
    assert_no_workspace(output)


@pytest.mark.parametrize(
    ("target", "suffix"),
    [(DocumentFormat.JPG, ".jpg"), (DocumentFormat.WEBP, ".webp")],
)
def test_compress_propagates_fixed_quality(
    tmp_path: Path, target: DocumentFormat, suffix: str
) -> None:
    source = tmp_path / "source.png"
    write_image(source)
    output = tmp_path / "output"
    output.mkdir()
    result = batch_compress_images(
        BatchImageCompressRequest((BatchImageInput(source),), output, target, quality=55)
    )
    assert result.batch.operation == "image.compress"
    assert result.outputs[0].output_path.suffix == suffix
    assert result.outputs[0].output_path.stat().st_size > 0


def test_compress_propagates_maximum_size(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    write_image(source, size=(120, 80))
    output = tmp_path / "output"
    output.mkdir()
    result = batch_compress_images(
        BatchImageCompressRequest(
            (BatchImageInput(source),), output, DocumentFormat.PNG, max_bytes=3500
        )
    )
    assert result.outputs[0].output_path.stat().st_size <= 3500


def test_partial_batch_continues_after_missing_and_corrupt_items(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    missing = tmp_path / "missing.png"
    corrupt = tmp_path / "corrupt.png"
    last = tmp_path / "last.png"
    write_image(first)
    corrupt.write_bytes(b"not an image")
    write_image(last)
    output = tmp_path / "output"
    output.mkdir()

    result = batch_convert_images(
        BatchImageConvertRequest(
            tuple(BatchImageInput(path) for path in (first, missing, corrupt, last)),
            output,
            DocumentFormat.JPG,
        )
    )

    assert result.batch.status is BatchStatus.PARTIAL
    assert result.batch.completed_count == 2
    assert result.batch.failed_count == 2
    assert result.batch.processed_count == 4
    assert result.batch.remaining_count == 0
    assert [entry.position for entry in result.outputs] == [0, 3]
    assert [entry.output_path.name for entry in result.outputs] == [
        "0001-first.jpg",
        "0004-last.jpg",
    ]
    assert result.batch.items[1].failure.code == "invalid_image_request"
    assert result.batch.items[2].failure.code == "image_processing_failed"
    assert str(tmp_path) not in result.batch.items[1].failure.message
    assert_no_workspace(output)


def test_all_failed_returns_terminal_result(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"bad")
    output = tmp_path / "output"
    output.mkdir()
    result = batch_convert_images(
        BatchImageConvertRequest(
            (BatchImageInput(tmp_path / "missing.png"), BatchImageInput(corrupt)),
            output,
            DocumentFormat.PNG,
        )
    )
    assert result.batch.status is BatchStatus.FAILED
    assert result.batch.is_terminal
    assert result.outputs == ()
    assert_no_workspace(output)


def test_failure_preserves_existing_destination_and_success_replaces_it(tmp_path: Path) -> None:
    missing = tmp_path / "same.png"
    good_directory = tmp_path / "nested"
    good_directory.mkdir()
    good = good_directory / "same.png"
    write_image(good)
    output = tmp_path / "output"
    output.mkdir()
    failed_destination = output / "0001-same.jpg"
    successful_destination = output / "0002-same.jpg"
    failed_destination.write_bytes(b"OLD FAILED")
    successful_destination.write_bytes(b"OLD SUCCESS")
    result = batch_convert_images(
        BatchImageConvertRequest(
            (BatchImageInput(missing), BatchImageInput(good)), output, DocumentFormat.JPG
        )
    )
    assert result.batch.status is BatchStatus.PARTIAL
    assert failed_destination.read_bytes() == b"OLD FAILED"
    assert successful_destination.read_bytes() != b"OLD SUCCESS"


def test_invalid_output_directory_is_a_global_request_failure(tmp_path: Path) -> None:
    request = BatchImageConvertRequest(
        (BatchImageInput(tmp_path / "source.png"),),
        tmp_path / "missing-output",
        DocumentFormat.PNG,
    )
    with pytest.raises(InvalidBatchDefinitionError):
        batch_convert_images(request)


def test_publication_failure_isolated_and_later_item_runs(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    write_image(first)
    write_image(second)
    output = tmp_path / "output"
    output.mkdir()
    old = output / "0001-first.png"
    old.write_bytes(b"OLD")
    real_replace = os.replace

    def selective_replace(source: Path, destination: Path) -> None:
        if Path(destination) == old:
            raise OSError("private filesystem detail")
        real_replace(source, destination)

    with patch.object(image_module.os, "replace", side_effect=selective_replace):
        result = batch_convert_images(
            BatchImageConvertRequest(
                (BatchImageInput(first), BatchImageInput(second)), output, DocumentFormat.PNG
            )
        )
    assert result.batch.status is BatchStatus.PARTIAL
    assert result.batch.items[0].failure.code == "image_output_publish_failed"
    assert result.batch.items[1].status.value == "completed"
    assert old.read_bytes() == b"OLD"
    assert_no_workspace(output)


@pytest.mark.parametrize(
    "case",
    [
        "wrong-type",
        "wrong-input",
        "wrong-output",
        "wrong-target",
        "missing",
        "malformed",
        "wrong-content",
    ],
)
def test_invalid_staged_artifacts_fail_only_the_item(tmp_path: Path, case: str) -> None:
    bad = tmp_path / "bad.png"
    good = tmp_path / "good.png"
    write_image(bad)
    write_image(good)
    output = tmp_path / "output"
    output.mkdir()
    real_processor = image_module.convert_image_path
    calls = 0

    def processor(request: object) -> object:
        nonlocal calls
        calls += 1
        converted = real_processor(request)  # type: ignore[arg-type]
        if calls == 2:
            return converted
        if case == "wrong-type":
            return object()
        if case == "wrong-input":
            return ImageConvertPathResult(
                tmp_path / "other.png",
                converted.output_path,
                converted.source_format,
                converted.target_format,
            )
        if case == "wrong-output":
            return ImageConvertPathResult(
                converted.input_path,
                tmp_path / "other.png",
                converted.source_format,
                converted.target_format,
            )
        if case == "wrong-target":
            return ImageConvertPathResult(
                converted.input_path,
                converted.output_path,
                converted.source_format,
                DocumentFormat.JPG,
            )
        if case == "missing":
            converted.output_path.unlink()
        elif case == "malformed":
            converted.output_path.write_bytes(b"bad")
        elif case == "wrong-content":
            write_image(converted.output_path, "JPEG")
        return converted

    with patch.object(image_module, "convert_image_path", side_effect=processor):
        result = batch_convert_images(
            BatchImageConvertRequest(
                (BatchImageInput(bad), BatchImageInput(good)), output, DocumentFormat.PNG
            )
        )
    assert result.batch.status is BatchStatus.PARTIAL
    assert result.batch.items[0].failure.code == "invalid_image_output"
    assert result.batch.items[1].status.value == "completed"
    assert [entry.position for entry in result.outputs] == [1]
    assert_no_workspace(output)


def test_staged_directory_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    write_image(source)
    output = tmp_path / "output"
    output.mkdir()

    def processor(request: object) -> ImageConvertPathResult:
        path = request.output_path  # type: ignore[attr-defined]
        path.mkdir()
        return ImageConvertPathResult(
            request.input_path,  # type: ignore[attr-defined]
            path,
            DocumentFormat.PNG,
            DocumentFormat.PNG,
        )

    with patch.object(image_module, "convert_image_path", side_effect=processor):
        result = batch_convert_images(
            BatchImageConvertRequest((BatchImageInput(source),), output, DocumentFormat.PNG)
        )
    assert result.batch.status is BatchStatus.FAILED
    assert result.batch.items[0].failure.code == "invalid_image_output"
    assert_no_workspace(output)


@pytest.mark.parametrize("target_location", ["inside", "outside"])
def test_staged_symlink_is_rejected(tmp_path: Path, target_location: str) -> None:
    source = tmp_path / "source.png"
    write_image(source)
    output = tmp_path / "output"
    output.mkdir()

    def processor(request: object) -> ImageConvertPathResult:
        output_path = request.output_path  # type: ignore[attr-defined]
        target = (
            output_path.parent / "target.png"
            if target_location == "inside"
            else tmp_path / "outside.png"
        )
        write_image(target)
        try:
            output_path.symlink_to(target)
        except OSError as error:
            pytest.skip(f"symlink creation is unavailable: {error}")
        return ImageConvertPathResult(
            request.input_path,  # type: ignore[attr-defined]
            output_path,
            DocumentFormat.PNG,
            DocumentFormat.PNG,
        )

    with patch.object(image_module, "convert_image_path", side_effect=processor):
        result = batch_convert_images(
            BatchImageConvertRequest((BatchImageInput(source),), output, DocumentFormat.PNG)
        )
    assert result.batch.status is BatchStatus.FAILED
    assert result.batch.items[0].failure.code == "invalid_image_output"
    assert_no_workspace(output)


@pytest.mark.parametrize(
    ("failure", "code", "message"),
    [
        (
            InvalidConversionRequestError("C:/secret/source.png"),
            "invalid_image_request",
            "The image request is invalid.",
        ),
        (
            UnsupportedConversionError("private Pillow detail"),
            "unsupported_image_conversion",
            "The requested image conversion is not supported.",
        ),
        (
            ImageProcessingError("private workspace path"),
            "image_processing_failed",
            "The image could not be processed.",
        ),
    ],
)
def test_expected_converter_errors_use_safe_failure_mapping(
    tmp_path: Path, failure: Exception, code: str, message: str
) -> None:
    source = tmp_path / "source.png"
    write_image(source)
    output = tmp_path / "output"
    output.mkdir()
    with patch.object(image_module, "convert_image_path", side_effect=failure):
        result = batch_convert_images(
            BatchImageConvertRequest((BatchImageInput(source),), output, DocumentFormat.PNG)
        )
    assert result.batch.items[0].failure.code == code
    assert result.batch.items[0].failure.message == message
    assert_no_workspace(output)


def test_unexpected_processor_error_surfaces_and_workspace_is_removed(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    write_image(source)
    output = tmp_path / "output"
    output.mkdir()
    with (
        patch.object(image_module, "convert_image_path", side_effect=RuntimeError("bug")),
        pytest.raises(RuntimeError, match="bug"),
    ):
        batch_convert_images(
            BatchImageConvertRequest((BatchImageInput(source),), output, DocumentFormat.PNG)
        )
    assert_no_workspace(output)


def test_workspace_creation_failure_uses_safe_batch_error(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    request = BatchImageConvertRequest(
        (BatchImageInput(tmp_path / "source.png"),), output, DocumentFormat.PNG
    )
    with (
        patch.object(image_module, "TemporaryDirectory", side_effect=OSError("private path")),
        pytest.raises(BatchProcessingError, match="Unable to process the image batch"),
    ):
        batch_convert_images(request)


def test_source_is_never_overwritten(tmp_path: Path) -> None:
    first_source = tmp_path / "photo.jpg"
    write_image(first_source, "JPEG")
    output = tmp_path / "output"
    output.mkdir()
    later_source = output / "0001-photo.png"
    write_image(later_source)
    original = later_source.read_bytes()
    request = BatchImageConvertRequest(
        (BatchImageInput(first_source), BatchImageInput(later_source)),
        output,
        DocumentFormat.PNG,
    )
    result = batch_convert_images(request)
    assert result.batch.status is BatchStatus.PARTIAL
    assert result.batch.items[0].failure.code == "invalid_image_request"
    assert result.batch.items[1].status.value == "completed"
    assert later_source.read_bytes() == original
    assert_no_workspace(output)

"""Validation coverage for immutable batch image workflow values."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from docuforge.batch import (
    Batch,
    BatchId,
    BatchImageCompressRequest,
    BatchImageConvertRequest,
    BatchImageInput,
    BatchImageOutput,
    BatchImageResizeRequest,
    BatchImageResult,
    BatchItemFailure,
    BatchItemId,
    BatchItemRequest,
    BatchItemResult,
    BatchRequest,
    InvalidBatchDefinitionError,
)
from docuforge.core import DocumentFormat
from docuforge.jobs import OperationKey


def item(path: str = "photo.png", **kwargs: object) -> BatchImageInput:
    return BatchImageInput(Path(path), **kwargs)  # type: ignore[arg-type]


def test_image_input_normalizes_identity_and_descriptor_without_filesystem_access() -> None:
    identity = BatchItemId.new()
    value = item("missing/photo.png", id=str(identity), descriptor="  portrait  ")
    assert value.id == identity
    assert value.descriptor == "portrait"
    assert item("missing/photo.png").descriptor == "photo.png"
    assert item("   ").descriptor == "image"
    with pytest.raises(FrozenInstanceError):
        value.descriptor = "changed"  # type: ignore[misc]
    assert not hasattr(value, "__dict__")


@pytest.mark.parametrize("descriptor", ["", "  ", 4])
def test_image_input_rejects_invalid_descriptors(descriptor: object) -> None:
    with pytest.raises(InvalidBatchDefinitionError):
        item(descriptor=descriptor)


def test_image_input_requires_path_but_allows_duplicate_paths_and_descriptors() -> None:
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageInput("photo.png")  # type: ignore[arg-type]
    first = item(descriptor="same")
    second = item(descriptor="same")
    request = BatchImageConvertRequest((first, second), Path("out"), "PNG")
    assert request.target_format is DocumentFormat.PNG


@pytest.mark.parametrize("items", [[], (), (object(),)])
def test_common_request_rejects_invalid_item_collections(items: object) -> None:
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageConvertRequest(items, Path("out"), DocumentFormat.PNG)  # type: ignore[arg-type]


def test_common_request_rejects_duplicate_ids_and_invalid_output_or_target() -> None:
    identity = BatchItemId.new()
    duplicate = (item("a.png", id=identity), item("b.png", id=identity))
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageConvertRequest(duplicate, Path("out"), DocumentFormat.PNG)
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageConvertRequest((item(),), "out", DocumentFormat.PNG)  # type: ignore[arg-type]
    for target in (DocumentFormat.PDF, DocumentFormat.GIF, "unknown"):
        with pytest.raises(InvalidBatchDefinitionError):
            BatchImageConvertRequest((item(),), Path("out"), target)  # type: ignore[arg-type]


def test_requests_generate_or_normalize_batch_ids_and_are_frozen_slotted() -> None:
    identity = BatchId.new()
    request = BatchImageConvertRequest((item(),), Path("out"), "jpeg", str(identity))
    assert request.batch_id == identity
    assert request.target_format is DocumentFormat.JPG
    assert not hasattr(request, "__dict__")
    with pytest.raises(FrozenInstanceError):
        request.target_format = DocumentFormat.PNG  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"max_width": 0},
        {"max_width": -1},
        {"max_width": True},
        {"max_width": 1.5},
        {"max_width": 1, "allow_upscale": 1},
    ],
)
def test_resize_request_rejects_invalid_configuration(kwargs: dict[str, object]) -> None:
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageResizeRequest(
            (item(),), Path("out"), DocumentFormat.PNG, **kwargs  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "kwargs",
    [{"max_width": 10}, {"max_height": 20}, {"max_width": 10, "max_height": 20}],
)
def test_resize_request_accepts_valid_bounds(kwargs: dict[str, int]) -> None:
    request = BatchImageResizeRequest((item(),), Path("out"), "webp", **kwargs)
    assert request.target_format is DocumentFormat.WEBP


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"quality": 50, "max_bytes": 1000},
        {"quality": 0},
        {"quality": 96},
        {"quality": True},
        {"max_bytes": 0},
        {"max_bytes": True},
    ],
)
def test_compress_request_rejects_invalid_constraints(kwargs: dict[str, object]) -> None:
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageCompressRequest(
            (item(),), Path("out"), DocumentFormat.JPG, **kwargs  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("target", [DocumentFormat.PNG, DocumentFormat.BMP, DocumentFormat.TIFF])
def test_fixed_quality_is_rejected_for_nonquality_targets(target: DocumentFormat) -> None:
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageCompressRequest((item(),), Path("out"), target, quality=50)


@pytest.mark.parametrize("target", list(DocumentFormat))
def test_max_bytes_accepts_exactly_supported_raster_targets(target: DocumentFormat) -> None:
    if target in {
        DocumentFormat.JPG,
        DocumentFormat.PNG,
        DocumentFormat.WEBP,
        DocumentFormat.BMP,
        DocumentFormat.TIFF,
    }:
        BatchImageCompressRequest((item(),), Path("out"), target, max_bytes=1000)
    else:
        with pytest.raises(InvalidBatchDefinitionError):
            BatchImageCompressRequest((item(),), Path("out"), target, max_bytes=1000)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"position": -1},
        {"position": True},
        {"input_path": "in.png"},
        {"output_path": "out.png"},
        {"source_format": DocumentFormat.PDF},
        {"target_format": DocumentFormat.GIF},
    ],
)
def test_image_output_rejects_invalid_metadata(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "item_id": BatchItemId.new(),
        "position": 0,
        "input_path": Path("in.png"),
        "output_path": Path("out.png"),
        "source_format": DocumentFormat.PNG,
        "target_format": DocumentFormat.PNG,
    }
    values.update(kwargs)
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageOutput(**values)  # type: ignore[arg-type]


def completed_batch(*, descriptor: str = "out.png") -> tuple[Batch, BatchImageOutput]:
    identity = BatchItemId.new()
    batch = Batch(
        BatchRequest(
            BatchId.new(),
            OperationKey("image.convert"),
            (BatchItemRequest(identity, 0, "in.png"),),
        )
    )
    batch = batch.start_item(identity).complete_item(identity, BatchItemResult(descriptor))
    output = BatchImageOutput(
        identity,
        0,
        Path("in.png"),
        Path("out.png"),
        DocumentFormat.PNG,
        DocumentFormat.PNG,
    )
    return batch, output


def test_image_result_requires_terminal_consistent_completed_outputs() -> None:
    batch, output = completed_batch()
    result = BatchImageResult(batch, Path("out"), (output,))
    assert result.outputs == (output,)
    pending = Batch(batch.request)
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageResult(pending, Path("out"), ())
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageResult(batch, Path("out"), ())
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageResult(batch, Path("out"), [output])  # type: ignore[arg-type]


def test_image_result_rejects_descriptor_mismatch_or_failed_item_output() -> None:
    mismatched_batch, output = completed_batch(descriptor="different.png")
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageResult(mismatched_batch, Path("out"), (output,))

    identity = BatchItemId.new()
    failed = Batch(
        BatchRequest(
            BatchId.new(),
            OperationKey("image.convert"),
            (BatchItemRequest(identity, 0, "in.png"),),
        )
    ).fail_item(identity, BatchItemFailure("failed", "Failed safely."))
    failed_output = BatchImageOutput(
        identity,
        0,
        Path("in.png"),
        Path("out.png"),
        DocumentFormat.PNG,
        DocumentFormat.PNG,
    )
    assert BatchImageResult(failed, Path("out"), ()).outputs == ()
    with pytest.raises(InvalidBatchDefinitionError):
        BatchImageResult(failed, Path("out"), (failed_output,))

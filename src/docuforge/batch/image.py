"""Sequential multi-file image workflows built on the immutable batch domain."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image, UnidentifiedImageError

from docuforge.batch.exceptions import BatchProcessingError, InvalidBatchDefinitionError
from docuforge.batch.models import (
    Batch,
    BatchId,
    BatchItemFailure,
    BatchItemId,
    BatchItemRequest,
    BatchItemResult,
    BatchItemStatus,
    BatchRequest,
)
from docuforge.converters.image import (
    ImageCompressPathRequest,
    ImageCompressPathResult,
    ImageConvertPathRequest,
    ImageConvertPathResult,
    ImageProcessingError,
    ImageResizePathRequest,
    ImageResizePathResult,
    compress_image_path,
    convert_image_path,
    resize_image_path,
)
from docuforge.converters.image.models import SUPPORTED_RASTER_FORMATS
from docuforge.core import (
    DocumentFormat,
    InvalidConversionRequestError,
    InvalidFormatError,
    UnsupportedConversionError,
)
from docuforge.jobs import OperationKey

_CONVERT_OPERATION = OperationKey("image.convert")
_RESIZE_OPERATION = OperationKey("image.resize")
_COMPRESS_OPERATION = OperationKey("image.compress")

_SUFFIX_BY_FORMAT = {
    DocumentFormat.JPG: ".jpg",
    DocumentFormat.PNG: ".png",
    DocumentFormat.WEBP: ".webp",
    DocumentFormat.BMP: ".bmp",
    DocumentFormat.TIFF: ".tiff",
}
_FORMAT_BY_PILLOW_NAME = {
    "JPEG": DocumentFormat.JPG,
    "PNG": DocumentFormat.PNG,
    "WEBP": DocumentFormat.WEBP,
    "BMP": DocumentFormat.BMP,
    "TIFF": DocumentFormat.TIFF,
}

_INVALID_REQUEST_FAILURE = BatchItemFailure(
    "invalid_image_request", "The image request is invalid."
)
_UNSUPPORTED_FAILURE = BatchItemFailure(
    "unsupported_image_conversion", "The requested image conversion is not supported."
)
_PROCESSING_FAILURE = BatchItemFailure(
    "image_processing_failed", "The image could not be processed."
)
_INVALID_OUTPUT_FAILURE = BatchItemFailure(
    "invalid_image_output", "The converted image output was invalid."
)
_PUBLISH_FAILURE = BatchItemFailure(
    "image_output_publish_failed", "The converted image could not be published."
)


def _normalize_raster_format(value: object, *, name: str) -> DocumentFormat:
    try:
        normalized = DocumentFormat.normalize(value)  # type: ignore[arg-type]
    except InvalidFormatError:
        raise InvalidBatchDefinitionError(f"{name} must be a supported raster format.") from None
    if normalized not in SUPPORTED_RASTER_FORMATS:
        raise InvalidBatchDefinitionError(f"{name} must be a supported raster format.")
    return normalized


def _positive_integer(value: int | None, *, name: str) -> None:
    if value is not None and (type(value) is not int or value <= 0):
        raise InvalidBatchDefinitionError(f"{name} must be a positive integer.")


@dataclass(frozen=True, slots=True)
class BatchImageInput:
    """One source image with stable batch identity and a safe display label."""

    input_path: Path
    id: BatchItemId = field(default_factory=BatchItemId.new)
    descriptor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.input_path, Path):
            raise InvalidBatchDefinitionError("Image input path must be a Path.")
        object.__setattr__(self, "id", BatchItemId(self.id))
        descriptor = self.descriptor
        if descriptor is None:
            descriptor = self.input_path.name
            if not descriptor.strip():
                descriptor = "image"
        if not isinstance(descriptor, str) or not descriptor.strip():
            raise InvalidBatchDefinitionError("Image descriptor must be a nonblank string.")
        object.__setattr__(self, "descriptor", descriptor.strip())


def _validate_common_request(request: Any) -> None:
    if not isinstance(request.items, tuple) or not request.items:
        raise InvalidBatchDefinitionError("A batch image request requires a nonempty item tuple.")
    if any(not isinstance(item, BatchImageInput) for item in request.items):
        raise InvalidBatchDefinitionError("Batch image items must be BatchImageInput values.")
    item_ids = tuple(item.id for item in request.items)
    if len(set(item_ids)) != len(item_ids):
        raise InvalidBatchDefinitionError("Batch image item IDs must be unique.")
    if not isinstance(request.output_directory, Path):
        raise InvalidBatchDefinitionError("Batch output directory must be a Path.")
    object.__setattr__(
        request,
        "target_format",
        _normalize_raster_format(request.target_format, name="Target format"),
    )
    object.__setattr__(request, "batch_id", BatchId(request.batch_id))


@dataclass(frozen=True, slots=True)
class BatchImageConvertRequest:
    """Configuration shared by every image-format conversion item."""

    items: tuple[BatchImageInput, ...]
    output_directory: Path
    target_format: DocumentFormat
    batch_id: BatchId = field(default_factory=BatchId.new)

    def __post_init__(self) -> None:
        _validate_common_request(self)


@dataclass(frozen=True, slots=True)
class BatchImageResizeRequest:
    """Configuration shared by every aspect-ratio-preserving resize item."""

    items: tuple[BatchImageInput, ...]
    output_directory: Path
    target_format: DocumentFormat
    max_width: int | None = None
    max_height: int | None = None
    allow_upscale: bool = False
    batch_id: BatchId = field(default_factory=BatchId.new)

    def __post_init__(self) -> None:
        _validate_common_request(self)
        _positive_integer(self.max_width, name="max_width")
        _positive_integer(self.max_height, name="max_height")
        if self.max_width is None and self.max_height is None:
            raise InvalidBatchDefinitionError("At least one resize bound is required.")
        if not isinstance(self.allow_upscale, bool):
            raise InvalidBatchDefinitionError("allow_upscale must be a bool.")


@dataclass(frozen=True, slots=True)
class BatchImageCompressRequest:
    """Configuration shared by every image compression item."""

    items: tuple[BatchImageInput, ...]
    output_directory: Path
    target_format: DocumentFormat
    quality: int | None = None
    max_bytes: int | None = None
    batch_id: BatchId = field(default_factory=BatchId.new)

    def __post_init__(self) -> None:
        _validate_common_request(self)
        _positive_integer(self.quality, name="quality")
        _positive_integer(self.max_bytes, name="max_bytes")
        if (self.quality is None) == (self.max_bytes is None):
            raise InvalidBatchDefinitionError("Exactly one compression constraint is required.")
        if self.quality is not None:
            if self.quality > 95:
                raise InvalidBatchDefinitionError("quality must be between 1 and 95.")
            if self.target_format not in {DocumentFormat.JPG, DocumentFormat.WEBP}:
                raise InvalidBatchDefinitionError(
                    "Fixed quality is supported only for JPG and WEBP targets."
                )


@dataclass(frozen=True, slots=True)
class BatchImageOutput:
    """Concrete path metadata for one successfully published image."""

    item_id: BatchItemId
    position: int
    input_path: Path
    output_path: Path
    source_format: DocumentFormat
    target_format: DocumentFormat

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", BatchItemId(self.item_id))
        if type(self.position) is not int or self.position < 0:
            raise InvalidBatchDefinitionError("Image output position must be non-negative.")
        if not isinstance(self.input_path, Path) or not isinstance(self.output_path, Path):
            raise InvalidBatchDefinitionError("Image output paths must be Path values.")
        object.__setattr__(
            self,
            "source_format",
            _normalize_raster_format(self.source_format, name="Source format"),
        )
        object.__setattr__(
            self,
            "target_format",
            _normalize_raster_format(self.target_format, name="Target format"),
        )


@dataclass(frozen=True, slots=True)
class BatchImageResult:
    """Terminal batch state and ordered metadata for successful image items."""

    batch: Batch
    output_directory: Path
    outputs: tuple[BatchImageOutput, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.batch, Batch) or not self.batch.is_terminal:
            raise InvalidBatchDefinitionError("An image result requires a terminal Batch.")
        if not isinstance(self.output_directory, Path):
            raise InvalidBatchDefinitionError("Image result output directory must be a Path.")
        if not isinstance(self.outputs, tuple) or any(
            not isinstance(output, BatchImageOutput) for output in self.outputs
        ):
            raise InvalidBatchDefinitionError("Image result outputs must be a tuple of outputs.")
        positions = tuple(output.position for output in self.outputs)
        item_ids = tuple(output.item_id for output in self.outputs)
        if positions != tuple(sorted(positions)):
            raise InvalidBatchDefinitionError("Image result outputs must retain item order.")
        if len(set(positions)) != len(positions) or len(set(item_ids)) != len(item_ids):
            raise InvalidBatchDefinitionError("Image result outputs must be unique.")
        by_id = {item.id: item for item in self.batch.items}
        for output in self.outputs:
            item = by_id.get(output.item_id)
            if (
                item is None
                or item.status is not BatchItemStatus.COMPLETED
                or item.position != output.position
                or item.result is None
                or item.result.descriptor != output.output_path.name
            ):
                raise InvalidBatchDefinitionError("Image output does not match its batch item.")
        completed_ids = {
            item.id for item in self.batch.items if item.status is BatchItemStatus.COMPLETED
        }
        if set(item_ids) != completed_ids:
            raise InvalidBatchDefinitionError("Every completed image item requires one output.")


def batch_convert_images(request: BatchImageConvertRequest) -> BatchImageResult:
    """Convert an ordered image batch while isolating expected item failures."""
    if not isinstance(request, BatchImageConvertRequest):
        raise TypeError("request must be a BatchImageConvertRequest")
    return _process_image_batch(
        request,
        operation=_CONVERT_OPERATION,
        request_builder=lambda item, output: ImageConvertPathRequest(item.input_path, output),
        processor=convert_image_path,
        expected_result_type=ImageConvertPathResult,
    )


def batch_resize_images(request: BatchImageResizeRequest) -> BatchImageResult:
    """Resize an ordered image batch while isolating expected item failures."""
    if not isinstance(request, BatchImageResizeRequest):
        raise TypeError("request must be a BatchImageResizeRequest")
    return _process_image_batch(
        request,
        operation=_RESIZE_OPERATION,
        request_builder=lambda item, output: ImageResizePathRequest(
            item.input_path,
            output,
            max_width=request.max_width,
            max_height=request.max_height,
            allow_upscale=request.allow_upscale,
        ),
        processor=resize_image_path,
        expected_result_type=ImageResizePathResult,
    )


def batch_compress_images(request: BatchImageCompressRequest) -> BatchImageResult:
    """Compress an ordered image batch while isolating expected item failures."""
    if not isinstance(request, BatchImageCompressRequest):
        raise TypeError("request must be a BatchImageCompressRequest")
    return _process_image_batch(
        request,
        operation=_COMPRESS_OPERATION,
        request_builder=lambda item, output: ImageCompressPathRequest(
            item.input_path,
            output,
            quality=request.quality,
            max_bytes=request.max_bytes,
        ),
        processor=compress_image_path,
        expected_result_type=ImageCompressPathResult,
    )


def _process_image_batch(
    request: BatchImageConvertRequest | BatchImageResizeRequest | BatchImageCompressRequest,
    *,
    operation: OperationKey,
    request_builder: Callable[[BatchImageInput, Path], object],
    processor: Callable[[object], object],
    expected_result_type: type,
) -> BatchImageResult:
    _validate_output_directory(request.output_directory)
    batch = Batch(
        BatchRequest(
            request.batch_id,
            operation,
            tuple(
                BatchItemRequest(item.id, position, item.descriptor)
                for position, item in enumerate(request.items)
            ),
        )
    )
    outputs: list[BatchImageOutput] = []
    temporary_directory: TemporaryDirectory[str] | None = None
    try:
        try:
            temporary_directory = TemporaryDirectory(
                dir=request.output_directory, prefix=".docuforge-batch-images-"
            )
        except OSError as error:
            raise BatchProcessingError("Unable to process the image batch.") from error
        workspace = Path(temporary_directory.name)
        for position, item in enumerate(request.items):
            batch = batch.start_item(item.id)
            item_workspace = workspace / f"item-{position + 1:04d}"
            final_output = request.output_directory / _output_name(
                item.input_path, position, request.target_format
            )
            try:
                if any(
                    _paths_resolve_equal(source.input_path, final_output)
                    for source in request.items
                ):
                    batch = batch.fail_item(item.id, _INVALID_REQUEST_FAILURE)
                    continue
                item_workspace.mkdir()
            except OSError:
                batch = batch.fail_item(item.id, _INVALID_OUTPUT_FAILURE)
                continue
            staged_output = item_workspace / final_output.name
            try:
                converter_result = processor(request_builder(item, staged_output))
            except InvalidConversionRequestError:
                batch = batch.fail_item(item.id, _INVALID_REQUEST_FAILURE)
                continue
            except UnsupportedConversionError:
                batch = batch.fail_item(item.id, _UNSUPPORTED_FAILURE)
                continue
            except ImageProcessingError:
                batch = batch.fail_item(item.id, _PROCESSING_FAILURE)
                continue
            if not _valid_staged_result(
                converter_result,
                expected_result_type=expected_result_type,
                source_path=item.input_path,
                staged_output=staged_output,
                item_workspace=item_workspace,
                target_format=request.target_format,
            ):
                batch = batch.fail_item(item.id, _INVALID_OUTPUT_FAILURE)
                continue
            try:
                os.replace(staged_output, final_output)
            except OSError:
                batch = batch.fail_item(item.id, _PUBLISH_FAILURE)
                continue
            output = BatchImageOutput(
                item.id,
                position,
                item.input_path,
                final_output,
                converter_result.source_format,
                converter_result.target_format,
            )
            outputs.append(output)
            batch = batch.complete_item(item.id, BatchItemResult(final_output.name))
        return BatchImageResult(batch, request.output_directory, tuple(outputs))
    finally:
        if temporary_directory is not None:
            try:
                temporary_directory.cleanup()
            except OSError as error:
                raise BatchProcessingError("Unable to process the image batch.") from error


def _validate_output_directory(output_directory: Path) -> None:
    try:
        valid = output_directory.exists() and output_directory.is_dir()
    except OSError:
        valid = False
    if not valid:
        raise InvalidBatchDefinitionError("Batch output directory must exist and be a directory.")


def _output_name(input_path: Path, position: int, target_format: DocumentFormat) -> str:
    stem = input_path.stem
    if not stem.strip() or stem in {".", ".."}:
        stem = "image"
    return f"{position + 1:04d}-{stem}{_SUFFIX_BY_FORMAT[target_format]}"


def _paths_resolve_equal(first: Path, second: Path) -> bool:
    try:
        return first.resolve(strict=False) == second.resolve(strict=False)
    except OSError:
        return False


def _valid_staged_result(
    result: object,
    *,
    expected_result_type: type,
    source_path: Path,
    staged_output: Path,
    item_workspace: Path,
    target_format: DocumentFormat,
) -> bool:
    if not isinstance(result, expected_result_type):
        return False
    try:
        if result.input_path.resolve(strict=False) != source_path.resolve(strict=False):
            return False
        if result.output_path.resolve(strict=False) != staged_output.resolve(strict=False):
            return False
        if result.target_format is not target_format:
            return False
        if result.source_format not in SUPPORTED_RASTER_FORMATS:
            return False
        node = staged_output.lstat()
        if not stat.S_ISREG(node.st_mode) or staged_output.is_symlink():
            return False
        if not staged_output.resolve(strict=True).is_relative_to(
            item_workspace.resolve(strict=True)
        ):
            return False
        with Image.open(staged_output) as image:
            image.load()
            actual_format = _FORMAT_BY_PILLOW_NAME.get(image.format or "")
            frame_count = getattr(image, "n_frames", 1)
        return actual_format is target_format and frame_count == 1
    except (
        OSError,
        RuntimeError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        return False

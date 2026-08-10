"""Immutable request models for image conversion."""

from dataclasses import dataclass
from pathlib import Path

from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    DocumentFormat,
    InvalidConversionRequestError,
)

SUPPORTED_IMAGE_FORMATS = frozenset(
    {
        DocumentFormat.JPG,
        DocumentFormat.PNG,
        DocumentFormat.BMP,
        DocumentFormat.TIFF,
    }
)

SUPPORTED_RASTER_FORMATS = frozenset(
    {
        DocumentFormat.JPG,
        DocumentFormat.PNG,
        DocumentFormat.WEBP,
        DocumentFormat.BMP,
        DocumentFormat.TIFF,
    }
)


def _validate_path_request_fields(
    input_paths: tuple[Path, ...],
    output_path: Path,
) -> None:
    """Validate path-model structure without reconstructing caller values."""
    if not isinstance(input_paths, tuple):
        raise TypeError("input_paths must be a tuple of Path objects")
    if not input_paths:
        raise InvalidConversionRequestError("At least one input path is required.")
    if any(not isinstance(input_path, Path) for input_path in input_paths):
        raise TypeError("input_paths must contain only Path objects")
    if not isinstance(output_path, Path):
        raise TypeError("output_path must be a Path object")


@dataclass(frozen=True, slots=True)
class ImageToPdfPathRequest:
    """An immutable request for suffix-inferred image-path conversion."""

    input_paths: tuple[Path, ...]
    output_path: Path

    def __post_init__(self) -> None:
        """Validate structure while preserving every caller-supplied object."""
        _validate_path_request_fields(self.input_paths, self.output_path)


@dataclass(frozen=True, slots=True)
class ImageToPdfPathResult:
    """The identity-preserving result of path-based image conversion."""

    input_paths: tuple[Path, ...]
    output_path: Path

    def __post_init__(self) -> None:
        """Validate structure while preserving every supplied object."""
        _validate_path_request_fields(self.input_paths, self.output_path)


def _validate_convert_path_fields(input_path: Path, output_path: Path) -> None:
    """Validate image-format path model structure without filesystem access."""
    if not isinstance(input_path, Path):
        raise TypeError("input_path must be a Path object")
    if not isinstance(output_path, Path):
        raise TypeError("output_path must be a Path object")


def _validate_positive_integer(value: int | None, field_name: str) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise TypeError(f"{field_name} must be an integer")
    if value is not None and value <= 0:
        raise InvalidConversionRequestError(f"{field_name} must be positive.")


@dataclass(frozen=True, slots=True)
class ImageConvertPathRequest:
    """One path-based raster format conversion request."""

    input_path: Path
    output_path: Path

    def __post_init__(self) -> None:
        """Validate structure while preserving caller-supplied paths."""
        _validate_convert_path_fields(self.input_path, self.output_path)


@dataclass(frozen=True, slots=True)
class ImageConvertPathResult:
    """The detected formats and paths from one raster conversion."""

    input_path: Path
    output_path: Path
    source_format: DocumentFormat
    target_format: DocumentFormat

    def __post_init__(self) -> None:
        """Validate paths and normalize supported source and target formats."""
        _validate_convert_path_fields(self.input_path, self.output_path)
        source_format = DocumentFormat.normalize(self.source_format)
        target_format = DocumentFormat.normalize(self.target_format)
        if source_format not in SUPPORTED_RASTER_FORMATS:
            raise InvalidConversionRequestError(
                f"Unsupported raster source format: {source_format.value}."
            )
        if target_format not in SUPPORTED_RASTER_FORMATS:
            raise InvalidConversionRequestError(
                f"Unsupported raster target format: {target_format.value}."
            )
        object.__setattr__(self, "source_format", source_format)
        object.__setattr__(self, "target_format", target_format)


@dataclass(frozen=True, slots=True)
class ImageResizePathRequest:
    """One aspect-ratio-preserving raster resize request."""

    input_path: Path
    output_path: Path
    max_width: int | None = None
    max_height: int | None = None
    allow_upscale: bool = False

    def __post_init__(self) -> None:
        """Validate resize bounds without accessing the filesystem."""
        _validate_convert_path_fields(self.input_path, self.output_path)
        _validate_positive_integer(self.max_width, "max_width")
        _validate_positive_integer(self.max_height, "max_height")
        if self.max_width is None and self.max_height is None:
            raise InvalidConversionRequestError(
                "At least one of max_width or max_height is required."
            )
        if not isinstance(self.allow_upscale, bool):
            raise TypeError("allow_upscale must be a bool")


@dataclass(frozen=True, slots=True)
class ImageResizePathResult:
    """Metadata describing one completed raster resize."""

    input_path: Path
    output_path: Path
    source_format: DocumentFormat
    target_format: DocumentFormat
    input_dimensions: tuple[int, int]
    output_dimensions: tuple[int, int]
    output_size_bytes: int

    def __post_init__(self) -> None:
        """Validate result metadata and normalize format values."""
        _validate_optimization_result(self)


@dataclass(frozen=True, slots=True)
class ImageCompressPathRequest:
    """One fixed-quality or maximum-size raster compression request."""

    input_path: Path
    output_path: Path
    quality: int | None = None
    max_bytes: int | None = None

    def __post_init__(self) -> None:
        """Require exactly one valid compression constraint."""
        _validate_convert_path_fields(self.input_path, self.output_path)
        _validate_positive_integer(self.quality, "quality")
        _validate_positive_integer(self.max_bytes, "max_bytes")
        if (self.quality is None) == (self.max_bytes is None):
            raise InvalidConversionRequestError(
                "Exactly one of quality or max_bytes is required."
            )
        if self.quality is not None and self.quality > 95:
            raise InvalidConversionRequestError("quality must be between 1 and 95.")


@dataclass(frozen=True, slots=True)
class ImageCompressPathResult:
    """Metadata describing one completed raster compression."""

    input_path: Path
    output_path: Path
    source_format: DocumentFormat
    target_format: DocumentFormat
    input_dimensions: tuple[int, int]
    output_dimensions: tuple[int, int]
    output_size_bytes: int
    quality_used: int | None

    def __post_init__(self) -> None:
        """Validate result metadata and normalize format values."""
        _validate_optimization_result(self)
        _validate_positive_integer(self.quality_used, "quality_used")
        if self.quality_used is not None and self.quality_used > 95:
            raise InvalidConversionRequestError(
                "quality_used must be between 1 and 95."
            )


def _validate_optimization_result(
    result: ImageResizePathResult | ImageCompressPathResult,
) -> None:
    _validate_convert_path_fields(result.input_path, result.output_path)
    source_format = DocumentFormat.normalize(result.source_format)
    target_format = DocumentFormat.normalize(result.target_format)
    if source_format not in SUPPORTED_RASTER_FORMATS:
        raise InvalidConversionRequestError(
            f"Unsupported raster source format: {source_format.value}."
        )
    if target_format not in SUPPORTED_RASTER_FORMATS:
        raise InvalidConversionRequestError(
            f"Unsupported raster target format: {target_format.value}."
        )
    for field_name, dimensions in (
        ("input_dimensions", result.input_dimensions),
        ("output_dimensions", result.output_dimensions),
    ):
        if (
            not isinstance(dimensions, tuple)
            or len(dimensions) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in dimensions)
        ):
            raise TypeError(f"{field_name} must be a two-integer tuple")
        if any(value <= 0 for value in dimensions):
            raise InvalidConversionRequestError(
                f"{field_name} values must be positive."
            )
    _validate_positive_integer(result.output_size_bytes, "output_size_bytes")
    object.__setattr__(result, "source_format", source_format)
    object.__setattr__(result, "target_format", target_format)


@dataclass(frozen=True, slots=True)
class ImageInput:
    """One ordered image input and its declared document format."""

    path: Path
    format: DocumentFormat

    def __post_init__(self) -> None:
        """Normalize the path and reject unsupported image formats."""
        path = Path(self.path)
        image_format = DocumentFormat.normalize(self.format)
        if image_format not in SUPPORTED_IMAGE_FORMATS:
            raise InvalidConversionRequestError(
                f"Unsupported image format: {image_format.value}."
            )
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "format", image_format)


@dataclass(frozen=True, slots=True, init=False)
class ImageToPdfRequest(ConversionRequest):
    """An immutable request for ordered, potentially mixed image inputs."""

    images: tuple[ImageInput, ...]

    def __init__(self, images: tuple[ImageInput, ...], output_path: Path) -> None:
        """Initialize an image-to-PDF request without weakening the core model."""
        normalized_images = tuple(images)
        if not normalized_images:
            raise InvalidConversionRequestError("At least one input image is required.")
        if any(not isinstance(image, ImageInput) for image in normalized_images):
            raise InvalidConversionRequestError("images must contain ImageInput instances.")

        ConversionRequest.__init__(
            self,
            input_paths=tuple(image.path for image in normalized_images),
            output_path=Path(output_path),
            source_format=normalized_images[0].format,
            target_format=DocumentFormat.PDF,
            operation=ConversionOperation.CONVERT,
        )
        object.__setattr__(self, "images", normalized_images)

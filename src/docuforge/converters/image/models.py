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

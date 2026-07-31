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

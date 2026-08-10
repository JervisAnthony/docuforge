"""Document-format definitions and normalization."""

from __future__ import annotations

from enum import Enum

from docuforge.core.exceptions import InvalidFormatError


class DocumentFormat(str, Enum):
    """A supported document format represented by its canonical extension."""

    PDF = "pdf"
    DOCX = "docx"
    JPG = "jpg"
    PNG = "png"
    GIF = "gif"
    BMP = "bmp"
    TIFF = "tiff"
    WEBP = "webp"
    TXT = "txt"

    @classmethod
    def normalize(cls, value: str | DocumentFormat) -> DocumentFormat:
        """Return the canonical format for a user-provided value."""
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise InvalidFormatError(f"Document format must be a string, got {type(value).__name__}.")

        normalized = value.strip().lower().removeprefix(".")
        if normalized == "jpeg":
            normalized = cls.JPG.value
        if normalized == "tif":
            normalized = cls.TIFF.value
        if not normalized:
            raise InvalidFormatError("Document format cannot be empty.")

        member = cls._value2member_map_.get(normalized)
        if member is None:
            raise InvalidFormatError(f"Unsupported document format: {value!r}.")
        return member

    @classmethod
    def _missing_(cls, value: object) -> DocumentFormat:
        """Normalize non-canonical values passed to the enum constructor."""
        if isinstance(value, str):
            return cls.normalize(value)
        raise InvalidFormatError(f"Document format must be a string, got {type(value).__name__}.")

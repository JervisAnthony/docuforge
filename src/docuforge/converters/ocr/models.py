"""Immutable, backend-neutral OCR engine intent and artifact identity."""

import re
from dataclasses import dataclass
from pathlib import Path

from docuforge.core import DocumentFormat, InvalidConversionRequestError, InvalidFormatError

_OUTPUT_FORMATS = frozenset({DocumentFormat.TXT, DocumentFormat.PDF})
_LANGUAGE_PATTERN = re.compile(r"[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*(?:\+[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*)*")
_MAX_LANGUAGE_LENGTH = 128


def _validate_path(value: Path, name: str) -> None:
    if not isinstance(value, Path):
        raise TypeError(f"{name} must be a Path object")


def _normalize_output_format(value: DocumentFormat | str) -> DocumentFormat:
    try:
        output_format = DocumentFormat.normalize(value)
    except InvalidFormatError as error:
        raise InvalidConversionRequestError("OCR output format must be TXT or PDF.") from error
    if output_format not in _OUTPUT_FORMATS:
        raise InvalidConversionRequestError("OCR output format must be TXT or PDF.")
    return output_format


def _validate_language(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_LANGUAGE_LENGTH
        or _LANGUAGE_PATTERN.fullmatch(value) is None
    ):
        raise InvalidConversionRequestError("Invalid OCR language selector.")


@dataclass(frozen=True, slots=True)
class OcrEngineRequest:
    """Request one OCR artifact from one raster input."""

    input_path: Path
    output_directory: Path
    output_format: DocumentFormat
    language: str = "eng"

    def __post_init__(self) -> None:
        _validate_path(self.input_path, "input_path")
        _validate_path(self.output_directory, "output_directory")
        object.__setattr__(self, "output_format", _normalize_output_format(self.output_format))
        _validate_language(self.language)


@dataclass(frozen=True, slots=True)
class OcrEngineResult:
    """Identity of one validated OCR artifact; it does not contain OCR text."""

    input_path: Path
    output_path: Path
    output_format: DocumentFormat
    language: str

    def __post_init__(self) -> None:
        _validate_path(self.input_path, "input_path")
        _validate_path(self.output_path, "output_path")
        object.__setattr__(self, "output_format", _normalize_output_format(self.output_format))
        _validate_language(self.language)

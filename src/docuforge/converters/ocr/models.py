"""Immutable, backend-neutral OCR engine intent and artifact identity."""

import re
from dataclasses import dataclass
from pathlib import Path

from docuforge.core import DocumentFormat, InvalidConversionRequestError, InvalidFormatError

_OUTPUT_FORMATS = frozenset({DocumentFormat.TXT, DocumentFormat.PDF})
_IMAGE_SOURCE_FORMATS = frozenset(
    {DocumentFormat.JPG, DocumentFormat.PNG, DocumentFormat.WEBP, DocumentFormat.BMP, DocumentFormat.TIFF}
)
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


def _validate_dpi(value: int | None, *, required: bool = False, limit: int | None = None) -> None:
    if value is None and not required:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or (
        limit is not None and value > limit
    ):
        raise InvalidConversionRequestError("Invalid OCR DPI setting.")


def _validate_scanned_request(
    input_path: Path,
    output_path: Path,
    language: str,
    dpi: int,
    max_pages: int,
    max_pixels_per_page: int,
) -> None:
    _validate_path(input_path, "input_path")
    _validate_path(output_path, "output_path")
    _validate_language(language)
    _validate_dpi(dpi, required=True, limit=600)
    for value, name in ((max_pages, "max_pages"), (max_pixels_per_page, "max_pixels_per_page")):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise InvalidConversionRequestError(f"Invalid OCR {name} setting.")


@dataclass(frozen=True, slots=True)
class OcrEngineRequest:
    """Request one OCR artifact from one raster input."""

    input_path: Path
    output_directory: Path
    output_format: DocumentFormat
    language: str = "eng"
    dpi: int | None = None

    def __post_init__(self) -> None:
        _validate_path(self.input_path, "input_path")
        _validate_path(self.output_directory, "output_directory")
        object.__setattr__(self, "output_format", _normalize_output_format(self.output_format))
        _validate_language(self.language)
        _validate_dpi(self.dpi)


@dataclass(frozen=True, slots=True)
class OcrEngineResult:
    """Identity of one validated OCR artifact; it does not contain OCR text."""

    input_path: Path
    output_path: Path
    output_format: DocumentFormat
    language: str
    dpi: int | None = None

    def __post_init__(self) -> None:
        _validate_path(self.input_path, "input_path")
        _validate_path(self.output_path, "output_path")
        object.__setattr__(self, "output_format", _normalize_output_format(self.output_format))
        _validate_language(self.language)
        _validate_dpi(self.dpi)


@dataclass(frozen=True, slots=True)
class ImageToTextRequest:
    """Request exact UTF-8 text output from one raster source."""

    input_path: Path
    output_path: Path
    language: str = "eng"

    def __post_init__(self) -> None:
        _validate_path(self.input_path, "input_path")
        _validate_path(self.output_path, "output_path")
        _validate_language(self.language)


@dataclass(frozen=True, slots=True)
class ImageToTextResult:
    """Published OCR text and its validated source identity."""

    input_path: Path
    output_path: Path
    text: str
    source_format: DocumentFormat
    language: str

    def __post_init__(self) -> None:
        _validate_path(self.input_path, "input_path")
        _validate_path(self.output_path, "output_path")
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        try:
            source_format = DocumentFormat.normalize(self.source_format)
        except InvalidFormatError as error:
            raise InvalidConversionRequestError("Unsupported OCR source format.") from error
        if source_format not in _IMAGE_SOURCE_FORMATS:
            raise InvalidConversionRequestError("Unsupported OCR source format.")
        object.__setattr__(self, "source_format", source_format)
        _validate_language(self.language)


@dataclass(frozen=True, slots=True)
class ScannedPdfToTextRequest:
    """Bounded intent to OCR every PDF page into exact aggregate text."""

    input_path: Path
    output_path: Path
    language: str = "eng"
    dpi: int = 300
    max_pages: int = 100
    max_pixels_per_page: int = 40_000_000

    def __post_init__(self) -> None:
        _validate_scanned_request(
            self.input_path, self.output_path, self.language, self.dpi,
            self.max_pages, self.max_pixels_per_page,
        )


@dataclass(frozen=True, slots=True)
class ScannedPdfToTextResult:
    """Exact page texts and their form-feed aggregate published at one path."""

    input_path: Path
    output_path: Path
    text: str
    page_texts: tuple[str, ...]
    page_count: int
    language: str
    dpi: int

    def __post_init__(self) -> None:
        _validate_path(self.input_path, "input_path")
        _validate_path(self.output_path, "output_path")
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        if not isinstance(self.page_texts, tuple) or any(
            not isinstance(page_text, str) for page_text in self.page_texts
        ):
            raise TypeError("page_texts must be a tuple of strings")
        if isinstance(self.page_count, bool) or not isinstance(self.page_count, int) or self.page_count <= 0:
            raise InvalidConversionRequestError("OCR page_count must be positive.")
        if len(self.page_texts) != self.page_count:
            raise InvalidConversionRequestError("OCR page_texts count must match page_count.")
        _validate_language(self.language)
        _validate_dpi(self.dpi, required=True, limit=600)


@dataclass(frozen=True, slots=True)
class ScannedPdfToSearchablePdfRequest:
    """Bounded intent to OCR every PDF page into a searchable PDF."""

    input_path: Path
    output_path: Path
    language: str = "eng"
    dpi: int = 300
    max_pages: int = 100
    max_pixels_per_page: int = 40_000_000

    def __post_init__(self) -> None:
        _validate_scanned_request(
            self.input_path, self.output_path, self.language, self.dpi,
            self.max_pages, self.max_pixels_per_page,
        )


@dataclass(frozen=True, slots=True)
class ScannedPdfToSearchablePdfResult:
    """Identity of one completed scanned-PDF searchable artifact."""

    input_path: Path
    output_path: Path
    page_count: int
    language: str
    dpi: int

    def __post_init__(self) -> None:
        _validate_path(self.input_path, "input_path")
        _validate_path(self.output_path, "output_path")
        if isinstance(self.page_count, bool) or not isinstance(self.page_count, int) or self.page_count <= 0:
            raise InvalidConversionRequestError("OCR page_count must be positive.")
        _validate_language(self.language)
        _validate_dpi(self.dpi, required=True, limit=600)

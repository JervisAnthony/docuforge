"""Immutable models for low-level Office-to-PDF conversion."""

from dataclasses import dataclass
from pathlib import Path

from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    DocumentFormat,
    InvalidConversionRequestError,
)

SUPPORTED_OFFICE_SOURCE_FORMATS = frozenset(
    {
        DocumentFormat.DOCX,
        DocumentFormat.PPTX,
        DocumentFormat.XLSX,
    }
)


@dataclass(frozen=True, slots=True, init=False)
class DocxToPdfRequest(ConversionRequest):
    """An immutable request to convert one DOCX to one exact PDF path."""

    def __init__(self, input_path: Path, output_path: Path) -> None:
        """Initialize the intrinsic DOCX-to-PDF conversion identity."""
        ConversionRequest.__init__(
            self,
            input_paths=(Path(input_path),),
            output_path=Path(output_path),
            source_format=DocumentFormat.DOCX,
            target_format=DocumentFormat.PDF,
            operation=ConversionOperation.CONVERT,
        )

    @property
    def input_path(self) -> Path:
        """Return the request's single DOCX source path."""
        return self.input_paths[0]


def _validate_path(value: Path, *, field_name: str) -> None:
    if not isinstance(value, Path):
        raise TypeError(f"{field_name} must be a Path object")


@dataclass(frozen=True, slots=True)
class OfficeConversionRequest:
    """Low-level intent to render one supported Office file into a directory."""

    input_path: Path
    output_directory: Path

    def __post_init__(self) -> None:
        _validate_path(self.input_path, field_name="input_path")
        _validate_path(self.output_directory, field_name="output_directory")


@dataclass(frozen=True, slots=True)
class OfficeConversionResult:
    """Paths and formats for one completed Office-to-PDF conversion."""

    input_path: Path
    output_path: Path
    source_format: DocumentFormat
    target_format: DocumentFormat = DocumentFormat.PDF

    def __post_init__(self) -> None:
        _validate_path(self.input_path, field_name="input_path")
        _validate_path(self.output_path, field_name="output_path")
        source_format = DocumentFormat.normalize(self.source_format)
        target_format = DocumentFormat.normalize(self.target_format)
        if source_format not in SUPPORTED_OFFICE_SOURCE_FORMATS:
            raise InvalidConversionRequestError(
                f"Unsupported Office source format: {source_format.value}."
            )
        if target_format is not DocumentFormat.PDF:
            raise InvalidConversionRequestError("Office conversion target must be PDF.")
        object.__setattr__(self, "source_format", source_format)
        object.__setattr__(self, "target_format", target_format)

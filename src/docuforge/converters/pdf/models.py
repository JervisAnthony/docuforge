"""Immutable request models for PDF splitting."""

from dataclasses import dataclass
from pathlib import Path

from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    DocumentFormat,
    InvalidConversionRequestError,
)


@dataclass(frozen=True, slots=True)
class PdfSplitDirectoryRequest:
    """A request to split every PDF page into a deterministic directory output."""

    input_path: Path
    output_directory: Path


@dataclass(frozen=True, slots=True)
class PdfSplitDirectoryResult:
    """The ordered outputs produced by a directory-based PDF split."""

    input_path: Path
    output_directory: Path
    output_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class PageGroup:
    """An ordered collection of zero-based pages for one split output."""

    page_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        """Normalize and validate page indices independent of a PDF."""
        page_indices = tuple(self.page_indices)
        object.__setattr__(self, "page_indices", page_indices)

        if not page_indices:
            raise InvalidConversionRequestError("Page groups must not be empty.")
        if any(not isinstance(index, int) or isinstance(index, bool) for index in page_indices):
            raise InvalidConversionRequestError("Page indices must be integers.")
        if any(index < 0 for index in page_indices):
            raise InvalidConversionRequestError("Page indices must not be negative.")


@dataclass(frozen=True, slots=True, init=False)
class PdfSplitRequest(ConversionRequest):
    """An immutable PDF split request with one ordered output per page group."""

    output_paths: tuple[Path, ...]
    page_groups: tuple[PageGroup, ...]

    def __init__(
        self,
        input_path: Path,
        output_paths: tuple[Path, ...],
        page_groups: tuple[PageGroup, ...],
    ) -> None:
        """Initialize and validate a PDF split request."""
        normalized_input = Path(input_path)
        normalized_outputs = tuple(Path(path) for path in output_paths)
        normalized_groups = tuple(page_groups)

        if not normalized_outputs:
            raise InvalidConversionRequestError("At least one output path is required.")
        if len(set(normalized_outputs)) != len(normalized_outputs):
            raise InvalidConversionRequestError("Output paths must not contain duplicates.")
        if normalized_input in normalized_outputs:
            raise InvalidConversionRequestError("Output paths must differ from the input path.")
        if not normalized_groups:
            raise InvalidConversionRequestError("At least one page group is required.")
        if any(not isinstance(group, PageGroup) for group in normalized_groups):
            raise InvalidConversionRequestError("page_groups must contain PageGroup instances.")
        if len(normalized_outputs) != len(normalized_groups):
            raise InvalidConversionRequestError(
                "Output path count must match page-group count."
            )

        ConversionRequest.__init__(
            self,
            input_paths=(normalized_input,),
            output_path=normalized_outputs[0],
            source_format=DocumentFormat.PDF,
            target_format=DocumentFormat.PDF,
            operation=ConversionOperation.SPLIT,
        )
        object.__setattr__(self, "output_paths", normalized_outputs)
        object.__setattr__(self, "page_groups", normalized_groups)

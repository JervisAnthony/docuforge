"""Immutable request models for PDF operations."""

from dataclasses import dataclass
from pathlib import Path

from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    DocumentFormat,
    InvalidConversionRequestError,
)


@dataclass(frozen=True, slots=True)
class PageRotation:
    """One clockwise rotation for a zero-based PDF page index."""

    page_index: int
    degrees: int

    def __post_init__(self) -> None:
        """Validate the page index and supported clockwise rotation."""
        if not isinstance(self.page_index, int) or isinstance(self.page_index, bool):
            raise TypeError("page_index must be an integer")
        if self.page_index < 0:
            raise InvalidConversionRequestError("page_index must be non-negative")
        if not isinstance(self.degrees, int) or isinstance(self.degrees, bool):
            raise TypeError("degrees must be an integer")
        if self.degrees not in {90, 180, 270}:
            raise InvalidConversionRequestError(
                "degrees must be one of 90, 180, or 270"
            )


@dataclass(frozen=True, slots=True, init=False)
class PdfRotateRequest(ConversionRequest):
    """An immutable request to rotate selected pages in one PDF."""

    output_paths: tuple[Path, ...]
    rotations: tuple[PageRotation, ...]

    def __init__(
        self,
        input_paths: tuple[Path, ...],
        output_paths: tuple[Path, ...],
        rotations: tuple[PageRotation, ...],
    ) -> None:
        """Validate structure while preserving every supplied object."""
        if not isinstance(input_paths, tuple):
            raise TypeError("input_paths must be a tuple of Path objects")
        if len(input_paths) != 1:
            raise InvalidConversionRequestError(
                "PDF rotation requires exactly one input path."
            )
        if any(not isinstance(path, Path) for path in input_paths):
            raise TypeError("input_paths must contain only Path objects")
        if not isinstance(output_paths, tuple):
            raise TypeError("output_paths must be a tuple of Path objects")
        if len(output_paths) != 1:
            raise InvalidConversionRequestError(
                "PDF rotation requires exactly one output path."
            )
        if any(not isinstance(path, Path) for path in output_paths):
            raise TypeError("output_paths must contain only Path objects")
        if not isinstance(rotations, tuple):
            raise TypeError("rotations must be a tuple of PageRotation objects")
        if not rotations:
            raise InvalidConversionRequestError(
                "At least one page rotation is required."
            )
        if any(not isinstance(rotation, PageRotation) for rotation in rotations):
            raise TypeError("rotations must contain only PageRotation objects")

        seen_page_indices: set[int] = set()
        for rotation in rotations:
            if rotation.page_index in seen_page_indices:
                raise InvalidConversionRequestError(
                    "Each page may have only one rotation instruction: "
                    f"{rotation.page_index}"
                )
            seen_page_indices.add(rotation.page_index)

        object.__setattr__(self, "input_paths", input_paths)
        object.__setattr__(self, "output_path", output_paths[0])
        object.__setattr__(self, "source_format", DocumentFormat.PDF)
        object.__setattr__(self, "target_format", DocumentFormat.PDF)
        object.__setattr__(self, "operation", ConversionOperation.SPLIT)
        object.__setattr__(self, "output_paths", output_paths)
        object.__setattr__(self, "rotations", rotations)


@dataclass(frozen=True, slots=True, init=False)
class PdfExtractPagesRequest(ConversionRequest):
    """An immutable request to extract selected pages from one PDF."""

    output_paths: tuple[Path, ...]
    page_indices: tuple[int, ...]

    def __init__(
        self,
        input_paths: tuple[Path, ...],
        output_paths: tuple[Path, ...],
        page_indices: tuple[int, ...],
    ) -> None:
        """Validate structure while preserving every supplied object."""
        if not isinstance(input_paths, tuple):
            raise TypeError("input_paths must be a tuple of Path objects")
        if len(input_paths) != 1:
            raise InvalidConversionRequestError(
                "PDF page extraction requires exactly one input path."
            )
        if any(not isinstance(path, Path) for path in input_paths):
            raise TypeError("input_paths must contain only Path objects")
        if not isinstance(output_paths, tuple):
            raise TypeError("output_paths must be a tuple of Path objects")
        if len(output_paths) != 1:
            raise InvalidConversionRequestError(
                "PDF page extraction requires exactly one output path."
            )
        if any(not isinstance(path, Path) for path in output_paths):
            raise TypeError("output_paths must contain only Path objects")
        if not isinstance(page_indices, tuple):
            raise TypeError("page_indices must be a tuple of integers")
        if not page_indices:
            raise InvalidConversionRequestError("At least one page index is required.")
        if any(
            not isinstance(page_index, int) or isinstance(page_index, bool)
            for page_index in page_indices
        ):
            raise TypeError("page_indices must contain only integers")
        if any(page_index < 0 for page_index in page_indices):
            raise InvalidConversionRequestError("Page indices must be non-negative.")

        seen_page_indices: set[int] = set()
        for page_index in page_indices:
            if page_index in seen_page_indices:
                raise InvalidConversionRequestError(
                    f"Each page may be extracted only once: {page_index}"
                )
            seen_page_indices.add(page_index)

        object.__setattr__(self, "input_paths", input_paths)
        object.__setattr__(self, "output_path", output_paths[0])
        object.__setattr__(self, "source_format", DocumentFormat.PDF)
        object.__setattr__(self, "target_format", DocumentFormat.PDF)
        object.__setattr__(self, "operation", ConversionOperation.SPLIT)
        object.__setattr__(self, "output_paths", output_paths)
        object.__setattr__(self, "page_indices", page_indices)


@dataclass(frozen=True, slots=True, init=False)
class PdfRemovePagesRequest(ConversionRequest):
    """An immutable request to remove selected pages from one PDF."""

    output_paths: tuple[Path, ...]
    page_indices: tuple[int, ...]

    def __init__(
        self,
        input_paths: tuple[Path, ...],
        output_paths: tuple[Path, ...],
        page_indices: tuple[int, ...],
    ) -> None:
        """Validate structure while preserving every supplied object."""
        if not isinstance(input_paths, tuple):
            raise TypeError("input_paths must be a tuple of Path objects")
        if len(input_paths) != 1:
            raise InvalidConversionRequestError(
                "PDF page removal requires exactly one input path."
            )
        if any(not isinstance(path, Path) for path in input_paths):
            raise TypeError("input_paths must contain only Path objects")
        if not isinstance(output_paths, tuple):
            raise TypeError("output_paths must be a tuple of Path objects")
        if len(output_paths) != 1:
            raise InvalidConversionRequestError(
                "PDF page removal requires exactly one output path."
            )
        if any(not isinstance(path, Path) for path in output_paths):
            raise TypeError("output_paths must contain only Path objects")
        if not isinstance(page_indices, tuple):
            raise TypeError("page_indices must be a tuple of integers")
        if not page_indices:
            raise InvalidConversionRequestError(
                "At least one page index is required."
            )
        if any(
            not isinstance(page_index, int) or isinstance(page_index, bool)
            for page_index in page_indices
        ):
            raise TypeError("page_indices must contain only integers")
        if any(page_index < 0 for page_index in page_indices):
            raise InvalidConversionRequestError("Page indices must be non-negative.")

        seen_page_indices: set[int] = set()
        for page_index in page_indices:
            if page_index in seen_page_indices:
                raise InvalidConversionRequestError(
                    f"Each page may be removed only once: {page_index}"
                )
            seen_page_indices.add(page_index)

        object.__setattr__(self, "input_paths", input_paths)
        object.__setattr__(self, "output_path", output_paths[0])
        object.__setattr__(self, "source_format", DocumentFormat.PDF)
        object.__setattr__(self, "target_format", DocumentFormat.PDF)
        object.__setattr__(self, "operation", ConversionOperation.SPLIT)
        object.__setattr__(self, "output_paths", output_paths)
        object.__setattr__(self, "page_indices", page_indices)


def _validate_extract_pages_path_fields(
    input_path: Path,
    output_path: Path,
    page_indices: tuple[int, ...],
) -> None:
    """Validate high-level extraction model structure without rebuilding values."""
    if not isinstance(input_path, Path):
        raise TypeError("input_path must be a Path object")
    if not isinstance(output_path, Path):
        raise TypeError("output_path must be a Path object")
    if not isinstance(page_indices, tuple):
        raise TypeError("page_indices must be a tuple of integers")
    if not page_indices:
        raise InvalidConversionRequestError("At least one page index is required.")
    if any(
        not isinstance(page_index, int) or isinstance(page_index, bool)
        for page_index in page_indices
    ):
        raise TypeError("page_indices must contain only integers")
    if any(page_index < 0 for page_index in page_indices):
        raise InvalidConversionRequestError("Page indices must be non-negative.")

    seen_page_indices: set[int] = set()
    for page_index in page_indices:
        if page_index in seen_page_indices:
            raise InvalidConversionRequestError(
                f"Each page may be extracted only once: {page_index}"
            )
        seen_page_indices.add(page_index)


@dataclass(frozen=True, slots=True)
class PdfExtractPagesPathRequest:
    """An immutable high-level request for extracting selected PDF pages."""

    input_path: Path
    output_path: Path
    page_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        """Validate structure while preserving all caller-supplied objects."""
        _validate_extract_pages_path_fields(
            self.input_path,
            self.output_path,
            self.page_indices,
        )


@dataclass(frozen=True, slots=True)
class PdfExtractPagesPathResult:
    """The identity-preserving result of high-level PDF page extraction."""

    input_path: Path
    output_path: Path
    page_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        """Validate structure while preserving all supplied objects."""
        _validate_extract_pages_path_fields(
            self.input_path,
            self.output_path,
            self.page_indices,
        )


def _validate_remove_pages_path_fields(
    input_path: Path,
    output_path: Path,
    page_indices: tuple[int, ...],
) -> None:
    """Validate high-level removal model structure without rebuilding values."""
    if not isinstance(input_path, Path):
        raise TypeError("input_path must be a Path object")
    if not isinstance(output_path, Path):
        raise TypeError("output_path must be a Path object")
    if not isinstance(page_indices, tuple):
        raise TypeError("page_indices must be a tuple of integers")
    if not page_indices:
        raise InvalidConversionRequestError("At least one page index is required.")
    if any(
        not isinstance(page_index, int) or isinstance(page_index, bool)
        for page_index in page_indices
    ):
        raise TypeError("page_indices must contain only integers")
    if any(page_index < 0 for page_index in page_indices):
        raise InvalidConversionRequestError("Page indices must be non-negative.")

    seen_page_indices: set[int] = set()
    for page_index in page_indices:
        if page_index in seen_page_indices:
            raise InvalidConversionRequestError(
                f"Each page may be removed only once: {page_index}"
            )
        seen_page_indices.add(page_index)


@dataclass(frozen=True, slots=True)
class PdfRemovePagesPathRequest:
    """An immutable high-level request for removing selected PDF pages."""

    input_path: Path
    output_path: Path
    page_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        """Validate structure while preserving all caller-supplied objects."""
        _validate_remove_pages_path_fields(
            self.input_path,
            self.output_path,
            self.page_indices,
        )


@dataclass(frozen=True, slots=True)
class PdfRemovePagesPathResult:
    """The identity-preserving result of high-level PDF page removal."""

    input_path: Path
    output_path: Path
    page_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        """Validate structure while preserving all supplied objects."""
        _validate_remove_pages_path_fields(
            self.input_path,
            self.output_path,
            self.page_indices,
        )


def _validate_rotate_path_fields(
    input_path: Path,
    output_path: Path,
    rotations: tuple[PageRotation, ...],
) -> None:
    """Validate high-level rotation model structure without rebuilding values."""
    if not isinstance(input_path, Path):
        raise TypeError("input_path must be a Path object")
    if not isinstance(output_path, Path):
        raise TypeError("output_path must be a Path object")
    if not isinstance(rotations, tuple):
        raise TypeError("rotations must be a tuple of PageRotation objects")
    if not rotations:
        raise InvalidConversionRequestError(
            "At least one rotation instruction is required."
        )
    if any(not isinstance(rotation, PageRotation) for rotation in rotations):
        raise TypeError("rotations must contain only PageRotation objects")

    seen_page_indices: set[int] = set()
    for rotation in rotations:
        if rotation.page_index in seen_page_indices:
            raise InvalidConversionRequestError(
                "Each page may have only one rotation instruction: "
                f"{rotation.page_index}"
            )
        seen_page_indices.add(rotation.page_index)


@dataclass(frozen=True, slots=True)
class PdfRotatePathRequest:
    """An immutable high-level request for rotating selected PDF pages."""

    input_path: Path
    output_path: Path
    rotations: tuple[PageRotation, ...]

    def __post_init__(self) -> None:
        """Validate structure while preserving all caller-supplied objects."""
        _validate_rotate_path_fields(
            self.input_path,
            self.output_path,
            self.rotations,
        )


@dataclass(frozen=True, slots=True)
class PdfRotatePathResult:
    """The identity-preserving result of high-level PDF page rotation."""

    input_path: Path
    output_path: Path
    rotations: tuple[PageRotation, ...]

    def __post_init__(self) -> None:
        """Validate structure while preserving all supplied objects."""
        _validate_rotate_path_fields(
            self.input_path,
            self.output_path,
            self.rotations,
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

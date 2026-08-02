"""High-level PDF splitting into deterministic directory outputs."""

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from docuforge.converters.pdf.exceptions import PdfProcessingError
from docuforge.converters.pdf.models import (
    PageGroup,
    PdfSplitDirectoryRequest,
    PdfSplitDirectoryResult,
    PdfSplitRequest,
)
from docuforge.converters.pdf.split import PdfSplitConverter
from docuforge.core import InvalidConversionRequestError


def split_pdf_to_directory(
    request: PdfSplitDirectoryRequest,
) -> PdfSplitDirectoryResult:
    """Split every source page into an ordered, deterministically named PDF."""
    if not isinstance(request, PdfSplitDirectoryRequest):
        raise TypeError("request must be an instance of PdfSplitDirectoryRequest")

    input_path = request.input_path
    output_directory = request.output_directory
    _validate_paths(input_path, output_directory)
    page_count = _read_page_count(input_path)
    if page_count == 0:
        raise InvalidConversionRequestError("PDF splitting requires at least one page.")

    try:
        output_directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PdfProcessingError(
            f"Unable to create output directory: {output_directory}."
        ) from error

    output_paths = tuple(
        output_directory / f"{input_path.stem}-page-{page_number:04d}.pdf"
        for page_number in range(1, page_count + 1)
    )
    page_groups = tuple(PageGroup((page_index,)) for page_index in range(page_count))
    split_request = PdfSplitRequest(
        input_path=input_path,
        output_paths=output_paths,
        page_groups=page_groups,
    )
    converted_paths = PdfSplitConverter().convert(split_request)
    return PdfSplitDirectoryResult(
        input_path=input_path,
        output_directory=output_directory,
        output_paths=converted_paths,
    )


def _validate_paths(input_path: Path, output_directory: Path) -> None:
    """Validate high-level paths before inspecting or creating files."""
    if input_path.suffix.lower() != ".pdf":
        raise InvalidConversionRequestError(
            f"Input file must use the .pdf extension: {input_path}"
        )
    if not input_path.exists():
        raise InvalidConversionRequestError(f"Input file does not exist: {input_path}.")
    if not input_path.is_file():
        raise InvalidConversionRequestError(f"Input path is not a file: {input_path}.")
    try:
        input_path.resolve(strict=True)
    except OSError as error:
        raise InvalidConversionRequestError(
            f"Unable to resolve input file: {input_path}."
        ) from error

    if output_directory.exists() and not output_directory.is_dir():
        raise InvalidConversionRequestError(
            f"Output path is not a directory: {output_directory}."
        )


def _read_page_count(input_path: Path) -> int:
    """Strictly inspect a PDF and translate expected read failures."""
    try:
        with input_path.open("rb") as input_stream:
            reader = PdfReader(input_stream, strict=True)
            if reader.is_encrypted:
                raise PdfProcessingError(
                    f"Encrypted PDF requires a password: {input_path}."
                )
            return len(reader.pages)
    except PdfProcessingError:
        raise
    except (OSError, EOFError, PyPdfError) as error:
        raise PdfProcessingError("Unable to inspect the requested PDF document.") from error

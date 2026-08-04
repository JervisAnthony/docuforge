"""Low-level converter for removing selected pages from one PDF."""

import os
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError

from docuforge.converters.pdf.exceptions import PdfProcessingError
from docuforge.converters.pdf.models import PdfRemovePagesRequest
from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    Converter,
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)


class PdfRemovePagesConverter(Converter):
    """Remove explicitly selected pages while preserving retained-page order."""

    def __init__(self) -> None:
        """Initialize the PDF-to-PDF page-removal converter."""
        super().__init__(
            ConversionOperation.SPLIT,
            DocumentFormat.PDF,
            DocumentFormat.PDF,
        )

    def convert(self, request: ConversionRequest) -> tuple[Path, ...]:
        """Remove requested pages and atomically replace the single output."""
        self._validate_request(request)
        assert isinstance(request, PdfRemovePagesRequest)

        input_path = request.input_paths[0]
        output_path = request.output_paths[0]
        writer = PdfWriter()
        temporary_path: Path | None = None
        try:
            with input_path.open("rb") as input_stream:
                reader = PdfReader(input_stream, strict=True)
                if reader.is_encrypted:
                    raise PdfProcessingError(
                        f"Encrypted PDF requires a password: {input_path}."
                    )

                page_count = len(reader.pages)
                self._validate_page_indices(request, page_count)
                if len(request.page_indices) == page_count:
                    raise InvalidConversionRequestError(
                        "At least one PDF page must remain after removal."
                    )

                removed_page_indices = set(request.page_indices)
                for page_index, page in enumerate(reader.pages):
                    if page_index not in removed_page_indices:
                        writer.add_page(page)

                with NamedTemporaryFile(
                    mode="w+b",
                    dir=output_path.parent,
                    prefix=f".{output_path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                    writer.write(temporary_file)
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())

            os.replace(temporary_path, output_path)
            temporary_path = None
            return request.output_paths
        except PdfProcessingError:
            raise
        except (OSError, EOFError, PyPdfError) as error:
            raise PdfProcessingError(
                "Unable to remove pages from the requested PDF document."
            ) from error
        finally:
            writer.close()
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_request(request: ConversionRequest) -> None:
        """Validate request identity and paths before opening the PDF."""
        if not isinstance(request, ConversionRequest):
            raise TypeError("request must be an instance of ConversionRequest")
        if (
            request.operation is not ConversionOperation.SPLIT
            or request.source_format is not DocumentFormat.PDF
            or request.target_format is not DocumentFormat.PDF
        ):
            raise UnsupportedConversionError(
                "PdfRemovePagesConverter requires a PDF page-removal request."
            )
        if not isinstance(request, PdfRemovePagesRequest):
            raise InvalidConversionRequestError(
                "PDF page removal requires a PdfRemovePagesRequest."
            )

        input_path = request.input_paths[0]
        output_path = request.output_paths[0]
        if input_path.suffix.lower() != ".pdf":
            raise InvalidConversionRequestError(
                f"Input file must use the .pdf extension: {input_path}"
            )
        if output_path.suffix.lower() != ".pdf":
            raise InvalidConversionRequestError(
                f"Output file must use the .pdf extension: {output_path}"
            )
        if not input_path.exists():
            raise InvalidConversionRequestError(
                f"Input file does not exist: {input_path}."
            )
        if not input_path.is_file():
            raise InvalidConversionRequestError(
                f"Input path is not a file: {input_path}."
            )

        output_parent = output_path.parent
        if not output_parent.exists():
            raise InvalidConversionRequestError(
                f"Output parent directory does not exist: {output_parent}."
            )
        if not output_parent.is_dir():
            raise InvalidConversionRequestError(
                f"Output parent directory does not exist: {output_parent}."
            )
        if output_path.exists() and output_path.is_dir():
            raise InvalidConversionRequestError(
                f"Output path is a directory: {output_path}."
            )

        try:
            resolved_input = input_path.resolve(strict=True)
        except OSError as error:
            raise InvalidConversionRequestError(
                f"Unable to resolve input file: {input_path}."
            ) from error
        try:
            resolved_output = output_path.resolve(strict=False)
        except OSError as error:
            raise InvalidConversionRequestError(
                f"Unable to resolve output path: {output_path}."
            ) from error
        if resolved_output == resolved_input:
            raise InvalidConversionRequestError(
                "Output path must not resolve to the input file."
            )

    @staticmethod
    def _validate_page_indices(
        request: PdfRemovePagesRequest,
        page_count: int,
    ) -> None:
        """Reject the first requested page index beyond the parsed document."""
        for page_index in request.page_indices:
            if page_index >= page_count:
                raise InvalidConversionRequestError(
                    f"Page index is out of range: {page_index}"
                )

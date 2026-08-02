"""PDF split converter implementation."""

import os
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError

from docuforge.converters.pdf.exceptions import PdfProcessingError
from docuforge.converters.pdf.models import PdfSplitRequest
from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    Converter,
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)


class PdfSplitConverter(Converter):
    """Write ordered groups of pages from one PDF to multiple PDFs."""

    def __init__(self) -> None:
        """Initialize the PDF-to-PDF split converter."""
        super().__init__(
            ConversionOperation.SPLIT,
            DocumentFormat.PDF,
            DocumentFormat.PDF,
        )

    def convert(self, request: ConversionRequest) -> tuple[Path, ...]:
        """Split one PDF into the outputs declared by a PDF split request."""
        self._validate_request(request)
        assert isinstance(request, PdfSplitRequest)

        temporary_paths: list[Path] = []
        try:
            with request.input_paths[0].open("rb") as input_stream:
                reader = PdfReader(input_stream, strict=True)
                if reader.is_encrypted:
                    raise PdfProcessingError(
                        f"Encrypted PDF requires a password: {request.input_paths[0]}."
                    )
                self._validate_page_indices(request, len(reader.pages))

                for output_path, page_group in zip(
                    request.output_paths,
                    request.page_groups,
                    strict=True,
                ):
                    writer = PdfWriter()
                    try:
                        for page_index in page_group.page_indices:
                            writer.add_page(reader.pages[page_index])
                        with NamedTemporaryFile(
                            mode="w+b",
                            dir=output_path.parent,
                            prefix=f".{output_path.name}.",
                            suffix=".tmp",
                            delete=False,
                        ) as temporary_file:
                            temporary_path = Path(temporary_file.name)
                            temporary_paths.append(temporary_path)
                            writer.write(temporary_file)
                            temporary_file.flush()
                            os.fsync(temporary_file.fileno())
                    finally:
                        writer.close()

            for temporary_path, output_path in zip(
                tuple(temporary_paths),
                request.output_paths,
                strict=True,
            ):
                os.replace(temporary_path, output_path)
                temporary_paths.remove(temporary_path)
            return request.output_paths
        except PdfProcessingError:
            raise
        except (OSError, EOFError, PyPdfError) as error:
            raise PdfProcessingError("Unable to split the requested PDF document.") from error
        finally:
            for temporary_path in temporary_paths:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_request(request: ConversionRequest) -> None:
        """Validate split-request type, identity, and filesystem paths."""
        if not isinstance(request, ConversionRequest):
            raise TypeError("request must be an instance of ConversionRequest")
        if (
            request.operation is not ConversionOperation.SPLIT
            or request.source_format is not DocumentFormat.PDF
            or request.target_format is not DocumentFormat.PDF
        ):
            raise UnsupportedConversionError("PdfSplitConverter requires a PDF split request.")
        if not isinstance(request, PdfSplitRequest):
            raise InvalidConversionRequestError("PDF splitting requires a PdfSplitRequest.")

        input_path = request.input_paths[0]
        if input_path.suffix.lower() != ".pdf":
            raise InvalidConversionRequestError(
                f"Input file must use the .pdf extension: {input_path}"
            )
        if not input_path.exists():
            raise InvalidConversionRequestError(f"Input file does not exist: {input_path}.")
        if not input_path.is_file():
            raise InvalidConversionRequestError(f"Input path is not a file: {input_path}.")
        try:
            resolved_input = input_path.resolve(strict=True)
        except OSError as error:
            raise InvalidConversionRequestError(
                f"Unable to resolve input file: {input_path}."
            ) from error

        resolved_outputs: set[Path] = set()
        for output_path in request.output_paths:
            output_parent = output_path.parent
            if not output_parent.exists() or not output_parent.is_dir():
                raise InvalidConversionRequestError(
                    f"Output parent directory does not exist: {output_parent}."
                )
            if output_path.exists() and output_path.is_dir():
                raise InvalidConversionRequestError(
                    f"Output path is a directory: {output_path}."
                )
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
            if resolved_output in resolved_outputs:
                raise InvalidConversionRequestError(
                    "Output paths must not resolve to the same file."
                )
            resolved_outputs.add(resolved_output)

    @staticmethod
    def _validate_page_indices(request: PdfSplitRequest, page_count: int) -> None:
        """Reject page indices outside the source document."""
        if any(
            page_index >= page_count
            for page_group in request.page_groups
            for page_index in page_group.page_indices
        ):
            raise InvalidConversionRequestError(
                f"Page index is out of range for a {page_count}-page PDF."
            )

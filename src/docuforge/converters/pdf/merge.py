"""PDF merge converter implementation."""

import os
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError

from docuforge.converters.pdf.exceptions import PdfProcessingError
from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    Converter,
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)


class PdfMergeConverter(Converter):
    """Merge two or more PDF documents into one PDF document."""

    def __init__(self) -> None:
        """Initialize the PDF-to-PDF merge converter."""
        super().__init__(
            ConversionOperation.MERGE,
            DocumentFormat.PDF,
            DocumentFormat.PDF,
        )

    def convert(self, request: ConversionRequest) -> Path:
        """Merge request inputs in order and atomically replace the output."""
        self._validate_request(request)

        writer = PdfWriter()
        temporary_path: Path | None = None
        try:
            for input_path in request.input_paths:
                with input_path.open("rb") as input_stream:
                    reader = PdfReader(input_stream)
                    if reader.is_encrypted:
                        raise PdfProcessingError(
                            f"Encrypted PDF requires a password: {input_path}."
                        )
                    writer.append(reader)

            with NamedTemporaryFile(
                mode="w+b",
                dir=request.output_path.parent,
                prefix=f".{request.output_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                writer.write(temporary_file)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, request.output_path)
            temporary_path = None
            return request.output_path
        except PdfProcessingError:
            raise
        except (OSError, EOFError, PyPdfError) as error:
            raise PdfProcessingError("Unable to merge the requested PDF documents.") from error
        finally:
            writer.close()
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_request(request: ConversionRequest) -> None:
        """Validate the request and filesystem paths before PDF processing."""
        if not isinstance(request, ConversionRequest):
            raise TypeError("request must be an instance of ConversionRequest")
        if (
            request.source_format is not DocumentFormat.PDF
            or request.target_format is not DocumentFormat.PDF
            or request.operation is not ConversionOperation.MERGE
        ):
            raise UnsupportedConversionError("PdfMergeConverter requires a PDF merge request.")
        if len(request.input_paths) < 2:
            raise InvalidConversionRequestError("PDF merge requires at least two input files.")

        resolved_inputs: set[Path] = set()
        for input_path in request.input_paths:
            if not input_path.exists():
                raise InvalidConversionRequestError(f"Input file does not exist: {input_path}.")
            if not input_path.is_file():
                raise InvalidConversionRequestError(f"Input path is not a file: {input_path}.")
            try:
                resolved_inputs.add(input_path.resolve(strict=True))
            except OSError as error:
                raise InvalidConversionRequestError(
                    f"Unable to resolve input file: {input_path}."
                ) from error

        output_parent = request.output_path.parent
        if not output_parent.exists() or not output_parent.is_dir():
            raise InvalidConversionRequestError(
                f"Output parent directory does not exist: {output_parent}."
            )
        try:
            resolved_output = request.output_path.resolve(strict=False)
        except OSError as error:
            raise InvalidConversionRequestError(
                f"Unable to resolve output path: {request.output_path}."
            ) from error
        if resolved_output in resolved_inputs:
            raise InvalidConversionRequestError("Output path must not resolve to an input file.")

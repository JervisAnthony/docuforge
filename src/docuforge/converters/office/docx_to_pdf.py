"""Concrete DOCX-to-PDF conversion workflow."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from docuforge.converters.office.engine import OfficeConversionEngine
from docuforge.converters.office.exceptions import OfficeConversionError
from docuforge.converters.office.models import (
    DocxToPdfRequest,
    OfficeConversionRequest,
    OfficeConversionResult,
)
from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    Converter,
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)


class DocxToPdfConverter(Converter):
    """Convert one DOCX into an exact PDF destination through an injected engine."""

    def __init__(self, engine: OfficeConversionEngine) -> None:
        """Initialize the converter without selecting a rendering implementation."""
        if not callable(getattr(engine, "convert_to_pdf", None)):
            raise TypeError("engine must implement OfficeConversionEngine")
        super().__init__(
            ConversionOperation.CONVERT,
            DocumentFormat.DOCX,
            DocumentFormat.PDF,
        )
        self._engine = engine

    def convert(self, request: ConversionRequest) -> Path:
        """Render, validate, and atomically publish a DOCX as the requested PDF."""
        resolved_input = self._validate_request(request)
        assert isinstance(request, DocxToPdfRequest)

        try:
            with tempfile.TemporaryDirectory(
                prefix=".docuforge-docx-",
                dir=request.output_path.parent,
            ) as workspace_value:
                workspace = Path(workspace_value)
                engine_result = self._engine.convert_to_pdf(
                    OfficeConversionRequest(
                        input_path=request.input_path,
                        output_directory=workspace,
                    )
                )
                engine_output = _validate_engine_result(
                    engine_result,
                    requested_input=resolved_input,
                    workspace=workspace,
                )
                try:
                    os.replace(engine_output, request.output_path)
                except OSError as error:
                    raise OfficeConversionError(
                        "Unable to publish the DOCX conversion output."
                    ) from error
        except OfficeConversionError:
            raise
        except OSError as error:
            raise OfficeConversionError(
                "Unable to create or clean up the DOCX conversion workspace."
            ) from error

        return request.output_path

    def _validate_request(self, request: ConversionRequest) -> Path:
        """Validate converter identity, request type, suffixes, and filesystem paths."""
        if not isinstance(request, ConversionRequest):
            raise TypeError("request must be an instance of ConversionRequest")
        if (
            request.operation is not ConversionOperation.CONVERT
            or request.source_format is not DocumentFormat.DOCX
            or request.target_format is not DocumentFormat.PDF
        ):
            raise UnsupportedConversionError(
                "DocxToPdfConverter supports only DOCX-to-PDF conversion."
            )
        if not isinstance(request, DocxToPdfRequest):
            raise InvalidConversionRequestError(
                "DOCX-to-PDF conversion requires a DocxToPdfRequest."
            )
        if len(request.input_paths) != 1:
            raise InvalidConversionRequestError(
                "DOCX-to-PDF conversion requires exactly one input file."
            )
        if request.input_path.suffix.lower() != ".docx":
            raise InvalidConversionRequestError("Input file must use the .docx extension.")
        if request.output_path.suffix.lower() != ".pdf":
            raise InvalidConversionRequestError("Output file must use the .pdf extension.")
        if not request.input_path.exists():
            raise InvalidConversionRequestError("The DOCX input file does not exist.")
        if not request.input_path.is_file():
            raise InvalidConversionRequestError("The DOCX input path is not a file.")

        output_parent = request.output_path.parent
        if not output_parent.exists() or not output_parent.is_dir():
            raise InvalidConversionRequestError(
                "The PDF output parent must be an existing directory."
            )
        if request.output_path.exists() and request.output_path.is_dir():
            raise InvalidConversionRequestError("The PDF output path is a directory.")

        try:
            resolved_input = request.input_path.resolve(strict=True)
            resolved_output = request.output_path.resolve(strict=False)
            same_file = request.output_path.exists() and os.path.samefile(
                request.input_path,
                request.output_path,
            )
        except OSError as error:
            raise InvalidConversionRequestError(
                "Unable to validate the DOCX conversion paths."
            ) from error
        if same_file or resolved_input == resolved_output:
            raise InvalidConversionRequestError(
                "The DOCX input and PDF output must be different files."
            )
        return resolved_input


def _validate_engine_result(
    result: object,
    *,
    requested_input: Path,
    workspace: Path,
) -> Path:
    """Return a trusted engine artifact contained by the workflow workspace."""
    if not isinstance(result, OfficeConversionResult):
        raise OfficeConversionError("The Office engine returned an invalid conversion result.")
    if (
        result.source_format is not DocumentFormat.DOCX
        or result.target_format is not DocumentFormat.PDF
    ):
        raise OfficeConversionError("The Office engine returned an inconsistent format result.")
    try:
        result_input = result.input_path.resolve(strict=True)
    except OSError as error:
        raise OfficeConversionError(
            "The Office engine returned an inconsistent input path."
        ) from error
    if result_input != requested_input:
        raise OfficeConversionError("The Office engine returned an inconsistent input path.")
    if not result.output_path.exists() or not result.output_path.is_file():
        raise OfficeConversionError("The Office engine did not produce a usable PDF artifact.")
    try:
        resolved_workspace = workspace.resolve(strict=True)
        resolved_output = result.output_path.resolve(strict=True)
        resolved_output.relative_to(resolved_workspace)
    except (OSError, ValueError) as error:
        raise OfficeConversionError(
            "The Office engine returned an output outside the conversion workspace."
        ) from error
    return result.output_path


def convert_docx_to_pdf(
    request: DocxToPdfRequest,
    *,
    engine: OfficeConversionEngine,
) -> Path:
    """Convert one DOCX by delegating to the concrete converter."""
    return DocxToPdfConverter(engine).convert(request)

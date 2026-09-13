"""Private shared Office workflow validation and publication mechanics."""

from __future__ import annotations

import os
import stat
import tempfile
import zipfile
from pathlib import Path

from docuforge.converters.office.engine import OfficeConversionEngine
from docuforge.converters.office.exceptions import OfficeConversionError
from docuforge.converters.office.models import OfficeConversionRequest, OfficeConversionResult
from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)


def validate_request(
    request: ConversionRequest,
    *,
    request_type: type[ConversionRequest],
    source_format: DocumentFormat,
    required_member: str,
) -> Path:
    """Validate format identity, source authenticity, and destination paths."""
    label = source_format.value.upper()
    if not isinstance(request, ConversionRequest):
        raise TypeError("request must be an instance of ConversionRequest")
    if (
        request.operation is not ConversionOperation.CONVERT
        or request.source_format is not source_format
        or request.target_format is not DocumentFormat.PDF
    ):
        raise UnsupportedConversionError(
            f"{request_type.__name__.replace('Request', 'Converter')} supports only {label}-to-PDF conversion."
        )
    if not isinstance(request, request_type):
        raise InvalidConversionRequestError(
            f"{label}-to-PDF conversion requires a {request_type.__name__}."
        )
    if len(request.input_paths) != 1:
        raise InvalidConversionRequestError(
            f"{label}-to-PDF conversion requires exactly one input file."
        )
    input_path = request.input_paths[0]
    if input_path.suffix.lower() != f".{source_format.value}":
        raise InvalidConversionRequestError(
            f"Input file must use the .{source_format.value} extension."
        )
    if request.output_path.suffix.lower() != ".pdf":
        raise InvalidConversionRequestError("Output file must use the .pdf extension.")
    if not input_path.exists():
        raise InvalidConversionRequestError(f"The {label} input file does not exist.")
    if not input_path.is_file():
        raise InvalidConversionRequestError(f"The {label} input path is not a file.")
    try:
        with zipfile.ZipFile(input_path) as archive:
            members = frozenset(archive.namelist())
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise InvalidConversionRequestError(
            f"Input file is not a valid {label} document."
        ) from error
    if not {"[Content_Types].xml", required_member}.issubset(members):
        raise InvalidConversionRequestError(f"Input file is not a valid {label} document.")
    output_parent = request.output_path.parent
    if not output_parent.exists() or not output_parent.is_dir():
        raise InvalidConversionRequestError(
            "The PDF output parent must be an existing directory."
        )
    if request.output_path.exists() and request.output_path.is_dir():
        raise InvalidConversionRequestError("The PDF output path is a directory.")
    try:
        resolved_input = input_path.resolve(strict=True)
        resolved_output = request.output_path.resolve(strict=False)
        same_file = request.output_path.exists() and os.path.samefile(
            input_path, request.output_path
        )
    except OSError as error:
        raise InvalidConversionRequestError(
            f"Unable to validate the {label} conversion paths."
        ) from error
    if same_file or resolved_input == resolved_output:
        raise InvalidConversionRequestError(
            f"The {label} input and PDF output must be different files."
        )
    return resolved_input


def validate_engine_result(
    result: object, *, requested_input: Path, workspace: Path, source_format: DocumentFormat
) -> Path:
    """Trust only a regular, non-symlink artifact in this workflow workspace."""
    if not isinstance(result, OfficeConversionResult):
        raise OfficeConversionError("The Office engine returned an invalid conversion result.")
    if result.source_format is not source_format or result.target_format is not DocumentFormat.PDF:
        raise OfficeConversionError("The Office engine returned an inconsistent format result.")
    try:
        result_input = result.input_path.resolve(strict=True)
    except OSError as error:
        raise OfficeConversionError(
            "The Office engine returned an inconsistent input path."
        ) from error
    if result_input != requested_input:
        raise OfficeConversionError("The Office engine returned an inconsistent input path.")
    try:
        artifact_mode = result.output_path.lstat().st_mode
    except OSError as error:
        raise OfficeConversionError(
            "The Office engine did not produce a usable PDF artifact."
        ) from error
    if stat.S_ISLNK(artifact_mode) or not stat.S_ISREG(artifact_mode):
        raise OfficeConversionError("The Office engine returned an invalid PDF artifact.")
    try:
        result.output_path.resolve(strict=True).relative_to(workspace.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise OfficeConversionError(
            "The Office engine returned an output outside the conversion workspace."
        ) from error
    return result.output_path


def publish_conversion(
    request: ConversionRequest,
    *,
    engine: OfficeConversionEngine,
    resolved_input: Path,
    source_format: DocumentFormat,
) -> Path:
    """Render in isolation, validate the engine result, then publish atomically."""
    label = source_format.value.upper()
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".docuforge-{source_format.value}-", dir=request.output_path.parent
        ) as workspace_value:
            workspace = Path(workspace_value)
            result = engine.convert_to_pdf(
                OfficeConversionRequest(
                    input_path=request.input_paths[0], output_directory=workspace
                )
            )
            output = validate_engine_result(
                result,
                requested_input=resolved_input,
                workspace=workspace,
                source_format=source_format,
            )
            try:
                os.replace(output, request.output_path)
            except OSError as error:
                raise OfficeConversionError(
                    f"Unable to publish the {label} conversion output."
                ) from error
    except OfficeConversionError:
        raise
    except OSError as error:
        raise OfficeConversionError(
            f"Unable to create or clean up the {label} conversion workspace."
        ) from error
    return request.output_path

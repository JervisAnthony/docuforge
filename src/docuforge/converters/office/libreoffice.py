"""LibreOffice-backed implementation of the Office conversion contract."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from docuforge.converters.office.exceptions import (
    OfficeConversionError,
    OfficeEngineExecutionError,
    OfficeEngineTimeoutError,
    OfficeEngineUnavailableError,
)
from docuforge.converters.office.models import OfficeConversionRequest, OfficeConversionResult
from docuforge.core import DocumentFormat, InvalidConversionRequestError, UnsupportedConversionError

DEFAULT_OFFICE_TIMEOUT_SECONDS = 90.0

ExecutableResolver = Callable[[str], str | None]

_FORMAT_BY_SUFFIX = {
    ".docx": DocumentFormat.DOCX,
    ".pptx": DocumentFormat.PPTX,
    ".xlsx": DocumentFormat.XLSX,
}


class ProcessRunner(Protocol):
    """Callable boundary matching the subprocess behavior used by the engine."""

    def __call__(
        self,
        args: Sequence[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
        shell: bool,
    ) -> subprocess.CompletedProcess[str]: ...


class LibreOfficeEngine:
    """Render supported Office files through an isolated headless LibreOffice process."""

    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        timeout_seconds: float = DEFAULT_OFFICE_TIMEOUT_SECONDS,
        executable_resolver: ExecutableResolver = shutil.which,
        process_runner: ProcessRunner = subprocess.run,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int | float):
            raise InvalidConversionRequestError("Office conversion timeout must be numeric.")
        if timeout_seconds <= 0:
            raise InvalidConversionRequestError("Office conversion timeout must be positive.")
        self._executable = _discover_executable(executable, resolver=executable_resolver)
        self._timeout_seconds = float(timeout_seconds)
        self._process_runner = process_runner

    @property
    def executable(self) -> str:
        """Return the resolved LibreOffice executable used by this engine."""
        return self._executable

    @property
    def timeout_seconds(self) -> float:
        """Return the finite process timeout in seconds."""
        return self._timeout_seconds

    def convert_to_pdf(self, request: OfficeConversionRequest) -> OfficeConversionResult:
        """Render one supported Office file and validate the produced PDF."""
        if not isinstance(request, OfficeConversionRequest):
            raise TypeError("request must be an OfficeConversionRequest")

        source_format = _validate_request(request)
        final_output_path = request.output_directory / f"{request.input_path.stem}.pdf"

        try:
            with (
                tempfile.TemporaryDirectory(
                    prefix=".docuforge-office-",
                    dir=request.output_directory,
                ) as staging_directory,
                tempfile.TemporaryDirectory(
                    prefix="docuforge-libreoffice-"
                ) as profile_directory,
            ):
                staging_path = Path(staging_directory)
                staged_output_path = staging_path / f"{request.input_path.stem}.pdf"
                args = _conversion_arguments(
                    executable=self._executable,
                    request=request,
                    output_directory=staging_path,
                    profile_path=Path(profile_directory),
                )
                self._run_process(args)
                _validate_pdf_output(staged_output_path)
                try:
                    os.replace(staged_output_path, final_output_path)
                except OSError as error:
                    raise OfficeConversionError(
                        "Unable to publish the Office conversion output."
                    ) from error
        except OfficeConversionError:
            raise
        except OSError as error:
            raise OfficeConversionError(
                "Unable to create or clean up the Office conversion workspace."
            ) from error

        return OfficeConversionResult(
            input_path=request.input_path,
            output_path=final_output_path,
            source_format=source_format,
        )

    def _run_process(self, args: Sequence[str]) -> None:
        try:
            completed = self._process_runner(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise OfficeEngineTimeoutError(
                "Office conversion exceeded its configured time limit."
            ) from error
        except OSError as error:
            raise OfficeEngineExecutionError("Unable to start the Office conversion engine.") from error

        if completed.returncode != 0:
            raise OfficeEngineExecutionError("The Office conversion engine reported a failure.")


def _discover_executable(
    explicit: str | Path | None,
    *,
    resolver: ExecutableResolver,
) -> str:
    if explicit is not None:
        executable_path = Path(explicit)
        if not executable_path.is_file():
            raise OfficeEngineUnavailableError(
                "The configured LibreOffice executable is unavailable."
            )
        return str(executable_path)

    for candidate in ("soffice", "libreoffice"):
        resolved = resolver(candidate)
        if resolved:
            return resolved
    raise OfficeEngineUnavailableError("LibreOffice is unavailable on this system.")


def _validate_request(request: OfficeConversionRequest) -> DocumentFormat:
    if not request.input_path.exists():
        raise InvalidConversionRequestError(
            f"Input file does not exist: {request.input_path}."
        )
    if not request.input_path.is_file():
        raise InvalidConversionRequestError(f"Input path is not a file: {request.input_path}.")
    if not request.output_directory.exists():
        raise InvalidConversionRequestError(
            f"Output directory does not exist: {request.output_directory}."
        )
    if not request.output_directory.is_dir():
        raise InvalidConversionRequestError(
            f"Output path is not a directory: {request.output_directory}."
        )

    source_format = _FORMAT_BY_SUFFIX.get(request.input_path.suffix.lower())
    if source_format is None:
        raise UnsupportedConversionError("Input file must use .docx, .pptx, or .xlsx.")
    return source_format


def _conversion_arguments(
    *,
    executable: str,
    request: OfficeConversionRequest,
    output_directory: Path,
    profile_path: Path,
) -> tuple[str, ...]:
    return (
        executable,
        "--headless",
        "--nologo",
        "--nodefault",
        f"-env:UserInstallation={profile_path.as_uri()}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_directory),
        str(request.input_path),
    )


def _validate_pdf_output(output_path: Path) -> None:
    if not output_path.exists():
        raise OfficeConversionError("The Office conversion engine did not produce a PDF.")
    if not output_path.is_file():
        raise OfficeConversionError("The Office conversion output is not a regular file.")
    try:
        with output_path.open("rb") as output_file:
            signature = output_file.read(5)
    except OSError as error:
        raise OfficeConversionError("Unable to validate the Office conversion output.") from error
    if not signature:
        raise OfficeConversionError("The Office conversion engine produced an empty PDF.")
    if signature != b"%PDF-":
        raise OfficeConversionError("The Office conversion engine produced an invalid PDF.")

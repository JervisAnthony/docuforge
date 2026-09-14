"""Isolated Tesseract CLI adapter for one raster-to-TXT/PDF artifact."""

from __future__ import annotations

import math
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from docuforge.converters.ocr.exceptions import (
    OcrEngineExecutionError,
    OcrEngineTimeoutError,
    OcrEngineUnavailableError,
    OcrOutputError,
)
from docuforge.converters.ocr.models import OcrEngineRequest, OcrEngineResult
from docuforge.core import DocumentFormat, InvalidConversionRequestError

DEFAULT_OCR_TIMEOUT_SECONDS = 60.0
ExecutableResolver = Callable[[str], str | None]
_RASTER_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"})


class ProcessRunner(Protocol):
    """Injectable subprocess boundary for Tesseract invocation."""

    def __call__(
        self,
        args: Sequence[str],
        *,
        shell: bool,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]: ...


class TesseractEngine:
    """Generate a validated artifact using a safely invoked local Tesseract CLI."""

    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        timeout_seconds: float = DEFAULT_OCR_TIMEOUT_SECONDS,
        executable_resolver: ExecutableResolver = shutil.which,
        process_runner: ProcessRunner = subprocess.run,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int | float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise InvalidConversionRequestError("OCR timeout must be a finite positive number.")
        self._executable = _discover_executable(executable, executable_resolver)
        self._timeout_seconds = float(timeout_seconds)
        self._process_runner = process_runner

    @property
    def executable(self) -> str:
        """Resolved executable selected during construction."""
        return self._executable

    @property
    def timeout_seconds(self) -> float:
        """Finite timeout used for each OCR process."""
        return self._timeout_seconds

    def recognize(self, request: OcrEngineRequest) -> OcrEngineResult:
        """Run OCR in a per-call workspace and atomically publish a trusted artifact."""
        if not isinstance(request, OcrEngineRequest):
            raise TypeError("request must be an OcrEngineRequest")
        _validate_request(request)
        suffix = f".{request.output_format.value}"
        final_output = request.output_directory / f"{request.input_path.stem}{suffix}"

        try:
            with tempfile.TemporaryDirectory(
                prefix=".docuforge-ocr-", dir=request.output_directory
            ) as workspace_name:
                workspace = Path(workspace_name)
                output_base = workspace / "ocr-result"
                staged_output = output_base.with_suffix(suffix)
                args = [
                    self._executable,
                    str(request.input_path),
                    str(output_base),
                    "-l",
                    request.language,
                ]
                if request.output_format is DocumentFormat.PDF:
                    args.append("pdf")
                self._run_process(args)
                _validate_artifact(staged_output, workspace, request.output_format)
                try:
                    os.replace(staged_output, final_output)
                except OSError as error:
                    raise OcrOutputError("Unable to publish the OCR output.") from error
        except OcrOutputError:
            raise
        except OSError as error:
            raise OcrOutputError("Unable to create or clean up the OCR workspace.") from error

        return OcrEngineResult(
            input_path=request.input_path,
            output_path=final_output,
            output_format=request.output_format,
            language=request.language,
        )

    def _run_process(self, args: Sequence[str]) -> None:
        try:
            completed = self._process_runner(
                args,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise OcrEngineTimeoutError("OCR exceeded its configured time limit.") from error
        except OSError as error:
            raise OcrEngineExecutionError("Unable to start the OCR engine.") from error
        if completed.returncode != 0:
            raise OcrEngineExecutionError("The OCR engine reported a failure.")


def _discover_executable(explicit: str | Path | None, resolver: ExecutableResolver) -> str:
    try:
        candidate = Path(explicit) if explicit is not None else Path(resolver("tesseract") or "")
        if not candidate.is_file():
            raise OcrEngineUnavailableError("Tesseract OCR is unavailable on this system.")
        return str(candidate)
    except (OSError, TypeError, ValueError) as error:
        raise OcrEngineUnavailableError("Tesseract OCR is unavailable on this system.") from error


def _validate_request(request: OcrEngineRequest) -> None:
    if request.input_path.suffix.lower() not in _RASTER_SUFFIXES:
        raise InvalidConversionRequestError("OCR input must be a supported raster image.")
    if not request.input_path.is_file():
        raise InvalidConversionRequestError("OCR input must be an existing regular file.")
    if not request.output_directory.is_dir():
        raise InvalidConversionRequestError("OCR output directory must exist.")


def _validate_artifact(path: Path, workspace: Path, output_format: DocumentFormat) -> None:
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise OcrOutputError("The OCR engine produced an unsafe output artifact.")
        path.resolve(strict=True).relative_to(workspace.resolve(strict=True))
        if output_format is DocumentFormat.TXT:
            path.read_bytes().decode("utf-8")
        else:
            with path.open("rb") as artifact:
                if artifact.read(5) != b"%PDF-":
                    raise OcrOutputError("The OCR engine produced an invalid PDF.")
    except (OSError, ValueError, UnicodeError) as error:
        raise OcrOutputError("Unable to validate the OCR output artifact.") from error

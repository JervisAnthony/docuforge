"""Behavior tests for the isolated LibreOffice process adapter."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import pytest

from docuforge.converters.office import (
    LibreOfficeEngine,
    OfficeConversionError,
    OfficeConversionRequest,
    OfficeEngineExecutionError,
    OfficeEngineTimeoutError,
    OfficeEngineUnavailableError,
)
from docuforge.core import (
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)


def file_uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    return Path(url2pathname(unquote(parsed.path)))


class RecordingRunner:
    """Fake subprocess boundary that can emit a controlled LibreOffice artifact."""

    def __init__(
        self,
        *,
        output_bytes: bytes | None = b"%PDF-1.7\ncontent",
        output_is_directory: bool = False,
        returncode: int = 0,
        error: BaseException | None = None,
        stderr: str = "",
    ) -> None:
        self.output_bytes = output_bytes
        self.output_is_directory = output_is_directory
        self.returncode = returncode
        self.error = error
        self.stderr = stderr
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []
        self.profile_paths: list[Path] = []

    def __call__(self, args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        command = tuple(args)
        self.calls.append((command, kwargs))
        profile_argument = next(
            argument for argument in command if argument.startswith("-env:UserInstallation=")
        )
        profile_path = file_uri_to_path(profile_argument.split("=", 1)[1])
        self.profile_paths.append(profile_path)
        assert profile_path.is_dir()

        if self.error is not None:
            raise self.error
        if self.output_bytes is not None:
            output_directory = Path(command[command.index("--outdir") + 1])
            input_path = Path(command[-1])
            output_path = output_directory / f"{input_path.stem}.pdf"
            if self.output_is_directory:
                output_path.mkdir()
            else:
                output_path.write_bytes(self.output_bytes)
        return subprocess.CompletedProcess(command, self.returncode, "converter output", self.stderr)


def make_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "soffice executable"
    executable.write_bytes(b"")
    return executable


def make_request(tmp_path: Path, *, suffix: str = ".docx") -> OfficeConversionRequest:
    tmp_path.mkdir(parents=True, exist_ok=True)
    input_path = tmp_path / f"source{suffix}"
    input_path.write_bytes(b"office fixture")
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    return OfficeConversionRequest(input_path, output_directory)


def make_engine(tmp_path: Path, runner: RecordingRunner) -> LibreOfficeEngine:
    return LibreOfficeEngine(executable=make_executable(tmp_path), process_runner=runner)


def test_explicit_executable_is_used_without_path_discovery(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)

    engine = LibreOfficeEngine(
        executable=executable,
        executable_resolver=lambda name: pytest.fail(f"unexpected lookup for {name}"),
    )

    assert engine.executable == str(executable)


def test_soffice_is_preferred_during_path_discovery() -> None:
    lookups: list[str] = []

    def resolve(name: str) -> str | None:
        lookups.append(name)
        return "/usr/bin/soffice" if name == "soffice" else None

    engine = LibreOfficeEngine(executable_resolver=resolve)

    assert engine.executable == "/usr/bin/soffice"
    assert lookups == ["soffice"]


def test_libreoffice_is_the_path_discovery_fallback() -> None:
    lookups: list[str] = []

    def resolve(name: str) -> str | None:
        lookups.append(name)
        return "/usr/bin/libreoffice" if name == "libreoffice" else None

    engine = LibreOfficeEngine(executable_resolver=resolve)

    assert engine.executable == "/usr/bin/libreoffice"
    assert lookups == ["soffice", "libreoffice"]


def test_unavailable_executable_raises_a_structured_error(tmp_path: Path) -> None:
    with pytest.raises(OfficeEngineUnavailableError):
        LibreOfficeEngine(executable=tmp_path / "missing-soffice")

    with pytest.raises(OfficeEngineUnavailableError):
        LibreOfficeEngine(executable_resolver=lambda name: None)


@pytest.mark.parametrize(
    ("suffix", "source_format"),
    [
        (".docx", DocumentFormat.DOCX),
        (".PPTX", DocumentFormat.PPTX),
        (".xlsx", DocumentFormat.XLSX),
    ],
)
def test_supported_suffixes_are_case_insensitive(
    tmp_path: Path,
    suffix: str,
    source_format: DocumentFormat,
) -> None:
    runner = RecordingRunner()
    request = make_request(tmp_path, suffix=suffix)

    result = make_engine(tmp_path, runner).convert_to_pdf(request)

    assert result.source_format is source_format
    assert result.target_format is DocumentFormat.PDF
    assert result.input_path == request.input_path
    assert result.output_path == request.output_directory / "source.pdf"


def test_unsupported_suffix_is_rejected_before_execution(tmp_path: Path) -> None:
    runner = RecordingRunner()
    request = make_request(tmp_path, suffix=".doc")

    with pytest.raises(UnsupportedConversionError):
        make_engine(tmp_path, runner).convert_to_pdf(request)

    assert runner.calls == []


def test_missing_or_directory_source_is_rejected(tmp_path: Path) -> None:
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    engine = LibreOfficeEngine(executable=make_executable(tmp_path), process_runner=RecordingRunner())

    with pytest.raises(InvalidConversionRequestError):
        engine.convert_to_pdf(OfficeConversionRequest(tmp_path / "missing.docx", output_directory))
    with pytest.raises(InvalidConversionRequestError):
        engine.convert_to_pdf(OfficeConversionRequest(tmp_path, output_directory))


def test_invalid_output_directory_is_rejected(tmp_path: Path) -> None:
    input_path = tmp_path / "source.docx"
    input_path.write_bytes(b"office fixture")
    output_file = tmp_path / "not-a-directory"
    output_file.write_bytes(b"")
    engine = LibreOfficeEngine(executable=make_executable(tmp_path), process_runner=RecordingRunner())

    with pytest.raises(InvalidConversionRequestError):
        engine.convert_to_pdf(OfficeConversionRequest(input_path, tmp_path / "missing"))
    with pytest.raises(InvalidConversionRequestError):
        engine.convert_to_pdf(OfficeConversionRequest(input_path, output_file))


def test_command_uses_safe_headless_arguments_and_preserves_complex_paths(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    runner = RecordingRunner()
    input_path = tmp_path / "résumé (final) document.DOCX"
    input_path.write_bytes(b"office fixture")
    output_directory = tmp_path / "output folder (résultats)"
    output_directory.mkdir()
    request = OfficeConversionRequest(input_path, output_directory)

    LibreOfficeEngine(executable=executable, process_runner=runner).convert_to_pdf(request)

    command, options = runner.calls[0]
    assert command[0] == str(executable)
    assert "--headless" in command
    assert command[command.index("--convert-to") + 1] == "pdf"
    assert command[command.index("--outdir") + 1] == str(output_directory)
    assert command[-1] == str(input_path)
    assert options == {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 90.0,
        "shell": False,
    }


def test_non_zero_exit_and_launch_failure_are_safe_errors(tmp_path: Path) -> None:
    secret = "private stderr details"
    request = make_request(tmp_path)
    non_zero_runner = RecordingRunner(returncode=2, stderr=secret)

    with pytest.raises(OfficeEngineExecutionError) as non_zero:
        make_engine(tmp_path, non_zero_runner).convert_to_pdf(request)
    assert secret not in str(non_zero.value)

    launch_runner = RecordingRunner(error=OSError(secret))
    with pytest.raises(OfficeEngineExecutionError) as launch:
        make_engine(tmp_path, launch_runner).convert_to_pdf(request)
    assert secret not in str(launch.value)


def test_timeout_uses_configured_limit_and_does_not_leak_details(tmp_path: Path) -> None:
    secret = "private timeout details"
    timeout = subprocess.TimeoutExpired("soffice", 12, stderr=secret)
    runner = RecordingRunner(error=timeout)
    request = make_request(tmp_path)
    engine = LibreOfficeEngine(
        executable=make_executable(tmp_path),
        timeout_seconds=12,
        process_runner=runner,
    )

    with pytest.raises(OfficeEngineTimeoutError) as raised:
        engine.convert_to_pdf(request)

    assert runner.calls[0][1]["timeout"] == 12.0
    assert secret not in str(raised.value)


@pytest.mark.parametrize(
    ("output_bytes", "message_fragment"),
    [
        (None, "did not produce"),
        (b"", "empty"),
        (b"not a PDF", "invalid"),
    ],
)
def test_missing_empty_and_invalid_pdf_outputs_are_rejected(
    tmp_path: Path,
    output_bytes: bytes | None,
    message_fragment: str,
) -> None:
    runner = RecordingRunner(output_bytes=output_bytes)
    request = make_request(tmp_path)

    with pytest.raises(OfficeConversionError, match=message_fragment):
        make_engine(tmp_path, runner).convert_to_pdf(request)


def test_directory_output_is_rejected(tmp_path: Path) -> None:
    runner = RecordingRunner(output_is_directory=True)
    request = make_request(tmp_path)

    with pytest.raises(OfficeConversionError, match="not a regular file"):
        make_engine(tmp_path, runner).convert_to_pdf(request)


def test_each_conversion_uses_a_distinct_profile_and_cleans_it_up(tmp_path: Path) -> None:
    runner = RecordingRunner()
    executable = make_executable(tmp_path)
    engine = LibreOfficeEngine(executable=executable, process_runner=runner)
    first = make_request(tmp_path / "first")
    second = make_request(tmp_path / "second")

    engine.convert_to_pdf(first)
    engine.convert_to_pdf(second)

    assert runner.profile_paths[0] != runner.profile_paths[1]
    assert all(not profile_path.exists() for profile_path in runner.profile_paths)


def test_profile_is_cleaned_up_after_process_failure(tmp_path: Path) -> None:
    runner = RecordingRunner(returncode=1)
    request = make_request(tmp_path)

    with pytest.raises(OfficeEngineExecutionError):
        make_engine(tmp_path, runner).convert_to_pdf(request)

    assert len(runner.profile_paths) == 1
    assert not runner.profile_paths[0].exists()


def test_timeout_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(InvalidConversionRequestError):
        LibreOfficeEngine(executable=make_executable(tmp_path), timeout_seconds=0)

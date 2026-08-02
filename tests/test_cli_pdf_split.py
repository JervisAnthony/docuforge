"""Focused tests for PDF split command-line execution."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

import docuforge.cli.commands.pdf_split as pdf_split_module
import docuforge.cli.dispatch as dispatch_module
from docuforge.__main__ import main
from docuforge.cli.commands.pdf_split import run_pdf_split
from docuforge.cli.dispatch import dispatch
from docuforge.cli.parser import build_parser
from docuforge.converters import (
    PdfProcessingError,
    PdfSplitDirectoryRequest,
    PdfSplitDirectoryResult,
)


def write_pdf(path: Path, page_widths: tuple[float, ...]) -> None:
    """Write a PDF whose page widths make ordering observable."""
    writer = PdfWriter()
    try:
        for width in page_widths:
            writer.add_blank_page(width=width, height=100)
        writer.write(path)
    finally:
        writer.close()


def write_encrypted_pdf(path: Path) -> None:
    """Write a password-protected PDF."""
    writer = PdfWriter()
    try:
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("secret")
        writer.write(path)
    finally:
        writer.close()


def page_widths(path: Path) -> list[float]:
    """Return page widths from a PDF."""
    return [float(page.mediabox.width) for page in PdfReader(path).pages]


def module_environment() -> dict[str, str]:
    """Return an environment that imports DocuForge from this source tree."""
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    source_path = str(project_root / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        path for path in (source_path, environment.get("PYTHONPATH")) if path
    )
    return environment


@pytest.mark.parametrize("output_option", ["-o", "--output-dir"])
def test_parser_accepts_split_paths_and_output_alias(output_option: str) -> None:
    arguments = build_parser().parse_args(
        ["pdf", "split", "input.pdf", output_option, "pages"]
    )

    assert arguments.input_path == Path("input.pdf")
    assert isinstance(arguments.input_path, Path)
    assert arguments.output_directory == Path("pages")
    assert isinstance(arguments.output_directory, Path)
    assert arguments.command_handler == "pdf_split"


@pytest.mark.parametrize(
    "arguments",
    [
        ["pdf", "split"],
        ["pdf", "split", "input.pdf"],
        ["pdf", "split", "first.pdf", "second.pdf", "-o", "pages"],
        ["pdf", "split", "input.pdf", "-o", "pages", "--unknown"],
    ],
)
def test_invalid_split_usage_returns_two_without_execution(
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def unexpected_split(input_path: Path, output_directory: Path) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(dispatch_module, "run_pdf_split", unexpected_split)

    assert main(arguments) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage: docuforge" in captured.err
    assert "error:" in captured.err
    assert called is False


def test_split_help_describes_input_and_output_aliases(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["pdf", "split", "--help"]) == 0

    captured = capsys.readouterr()
    assert "usage: docuforge pdf split" in captured.out
    assert "INPUT" in captured.out
    assert "-o OUTPUT_DIR" in captured.out
    assert "--output-dir OUTPUT_DIR" in captured.out
    assert captured.err == ""


def test_dispatch_passes_exact_parsed_paths_and_return_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = build_parser().parse_args(
        ["pdf", "split", "relative/input.pdf", "-o", "relative/pages"]
    )
    received_input: Path | None = None
    received_output_directory: Path | None = None

    def run_split(input_path: Path, output_directory: Path) -> int:
        nonlocal received_input, received_output_directory
        received_input = input_path
        received_output_directory = output_directory
        return 17

    monkeypatch.setattr(dispatch_module, "run_pdf_split", run_split)

    assert dispatch(arguments) == 17
    assert received_input is arguments.input_path
    assert received_output_directory is arguments.output_directory


def test_parser_construction_does_not_execute_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def unexpected_split(input_path: Path, output_directory: Path) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(dispatch_module, "run_pdf_split", unexpected_split)

    build_parser()

    assert called is False


@pytest.mark.parametrize("output_option", ["-o", "--output-dir"])
def test_main_splits_multiple_pages_with_exact_success_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_option: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("source.pdf"), (100, 200, 300))

    assert main(["pdf", "split", "source.pdf", output_option, "pages"]) == 0

    outputs = tuple(
        Path("pages") / f"source-page-{page_number:04d}.pdf"
        for page_number in range(1, 4)
    )
    assert all(path.is_file() for path in outputs)
    assert [page_widths(path) for path in outputs] == [[100], [200], [300]]
    captured = capsys.readouterr()
    assert captured.out == "Split source.pdf into 3 PDF files in pages\n"
    assert captured.err == ""


def test_main_splits_one_uppercase_pdf_and_creates_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("SOURCE.PDF"), (100,))

    assert main(["pdf", "split", "SOURCE.PDF", "-o", "nested/pages"]) == 0

    output = Path("nested/pages/SOURCE-page-0001.pdf")
    assert page_widths(output) == [100]
    captured = capsys.readouterr()
    assert captured.out == f"Split SOURCE.PDF into 1 PDF files in {Path('nested/pages')}\n"
    assert captured.err == ""


def test_run_pdf_split_uses_public_request_identity_and_result_count(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = Path("relative/input.pdf")
    output_directory = Path("relative/pages")
    output_paths = tuple(Path(f"canonical-{index}.pdf") for index in range(4))
    received_request: PdfSplitDirectoryRequest | None = None
    call_count = 0

    def split(request: PdfSplitDirectoryRequest) -> PdfSplitDirectoryResult:
        nonlocal call_count, received_request
        call_count += 1
        received_request = request
        return PdfSplitDirectoryResult(
            input_path=request.input_path,
            output_directory=request.output_directory,
            output_paths=output_paths,
        )

    monkeypatch.setattr(pdf_split_module, "split_pdf_to_directory", split)

    assert run_pdf_split(input_path, output_directory) == 0

    assert received_request is not None
    assert call_count == 1
    assert isinstance(received_request, PdfSplitDirectoryRequest)
    assert received_request.input_path is input_path
    assert received_request.output_directory is output_directory
    captured = capsys.readouterr()
    assert captured.out == (
        f"Split {input_path} into 4 PDF files in {output_directory}\n"
    )
    assert captured.err == ""


def test_run_pdf_split_does_not_validate_or_scan_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = Path("notes.txt")
    output_directory = Path("missing-pages")
    received_request: PdfSplitDirectoryRequest | None = None

    def split(request: PdfSplitDirectoryRequest) -> PdfSplitDirectoryResult:
        nonlocal received_request
        received_request = request
        return PdfSplitDirectoryResult(
            request.input_path,
            request.output_directory,
            (Path("library-owned-output.pdf"),),
        )

    def unexpected_scan(path: Path, *args: object, **kwargs: object) -> object:
        raise AssertionError("CLI must not scan the output directory")

    monkeypatch.setattr(pdf_split_module, "split_pdf_to_directory", split)
    monkeypatch.setattr(Path, "iterdir", unexpected_scan)
    monkeypatch.setattr(Path, "glob", unexpected_scan)

    assert run_pdf_split(input_path, output_directory) == 0

    assert received_request is not None
    assert received_request.input_path is input_path
    assert received_request.output_directory is output_directory
    captured = capsys.readouterr()
    assert captured.out == "Split notes.txt into 1 PDF files in missing-pages\n"
    assert captured.err == ""


@pytest.mark.parametrize(
    ("input_name", "expected_error"),
    [
        ("notes.txt", "Input file must use the .pdf extension: notes.txt"),
        ("missing.pdf", "Input file does not exist: missing.pdf."),
    ],
)
def test_main_reports_input_validation_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    input_name: str,
    expected_error: str,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["pdf", "split", input_name, "-o", "pages"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Error: {expected_error}\n"
    assert "Traceback" not in captured.err
    assert "Split" not in captured.err
    assert not Path("pages").exists()


def test_main_reports_directory_input_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("input.pdf").mkdir()

    assert main(["pdf", "split", "input.pdf", "-o", "pages"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Input path is not a file: input.pdf.\n"


def test_main_reports_malformed_pdf_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("malformed.pdf").write_bytes(b"not a PDF")

    assert main(["pdf", "split", "malformed.pdf", "-o", "pages"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Unable to inspect the requested PDF document.\n"
    assert not Path("pages").exists()


def test_main_reports_encrypted_pdf_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_encrypted_pdf(Path("encrypted.pdf"))

    assert main(["pdf", "split", "encrypted.pdf", "-o", "pages"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Error: Encrypted PDF requires a password: encrypted.pdf.\n"
    )
    assert not Path("pages").exists()


def test_main_reports_empty_pdf_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("empty.pdf"), ())

    assert main(["pdf", "split", "empty.pdf", "-o", "pages"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: PDF splitting requires at least one page.\n"
    assert not Path("pages").exists()


def test_main_reports_invalid_output_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("input.pdf"), (100,))
    Path("pages").write_text("not a directory", encoding="utf-8")

    assert main(["pdf", "split", "input.pdf", "-o", "pages"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Output path is not a directory: pages.\n"


def test_run_pdf_split_preserves_operation_stderr_and_reports_public_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(request: PdfSplitDirectoryRequest) -> PdfSplitDirectoryResult:
        print("operation diagnostic", file=sys.stderr)
        raise PdfProcessingError("simulated split failure")

    monkeypatch.setattr(pdf_split_module, "split_pdf_to_directory", fail)

    assert run_pdf_split(Path("input.pdf"), Path("pages")) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "operation diagnostic\nError: simulated split failure\n"
    )


def test_run_pdf_split_does_not_catch_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(request: PdfSplitDirectoryRequest) -> PdfSplitDirectoryResult:
        raise RuntimeError("unexpected split failure")

    monkeypatch.setattr(pdf_split_module, "split_pdf_to_directory", fail)

    with pytest.raises(RuntimeError, match="unexpected split failure"):
        run_pdf_split(Path("input.pdf"), Path("pages"))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_python_module_entry_point_splits_pdf(tmp_path: Path) -> None:
    input_path = tmp_path / "source.pdf"
    output_directory = tmp_path / "pages"
    write_pdf(input_path, (100, 200, 300))
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "docuforge",
            "pdf",
            "split",
            str(input_path),
            "--output-dir",
            str(output_directory),
        ],
        cwd=project_root,
        env=module_environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == (
        f"Split {input_path} into 3 PDF files in {output_directory}\n"
    )
    assert result.stderr == ""
    assert [
        page_widths(output_directory / f"source-page-{number:04d}.pdf")
        for number in range(1, 4)
    ] == [[100], [200], [300]]


def test_python_module_entry_point_reports_only_malformed_pdf_error(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "malformed.pdf"
    output_directory = tmp_path / "pages"
    input_path.write_bytes(b"not a PDF")
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "docuforge",
            "pdf",
            "split",
            str(input_path),
            "-o",
            str(output_directory),
        ],
        cwd=project_root,
        env=module_environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Error: Unable to inspect the requested PDF document.\n"
    assert not output_directory.exists()


def test_installed_console_script_splits_pdf(tmp_path: Path) -> None:
    executable = shutil.which("docuforge")
    if executable is None:
        pytest.skip("the docuforge console script is not installed")
    input_path = tmp_path / "source.pdf"
    output_directory = tmp_path / "pages"
    write_pdf(input_path, (100, 200))

    result = subprocess.run(
        [executable, "pdf", "split", str(input_path), "-o", str(output_directory)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == (
        f"Split {input_path} into 2 PDF files in {output_directory}\n"
    )
    assert result.stderr == ""
    assert page_widths(output_directory / "source-page-0001.pdf") == [100]
    assert page_widths(output_directory / "source-page-0002.pdf") == [200]

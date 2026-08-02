"""Focused tests for PDF merge command-line execution."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

import docuforge.cli.dispatch as dispatch_module
from docuforge.__main__ import main
from docuforge.cli.commands.pdf_merge import run_pdf_merge
from docuforge.cli.parser import build_parser
from docuforge.converters import PdfMergeConverter, PdfProcessingError
from docuforge.core import ConversionRequest, InvalidConversionRequestError


def write_pdf(path: Path, page_widths: tuple[float, ...]) -> None:
    """Write a PDF whose page widths make ordering observable."""
    writer = PdfWriter()
    try:
        for width in page_widths:
            writer.add_blank_page(width=width, height=100)
        writer.write(path)
    finally:
        writer.close()


def page_widths(path: Path) -> list[float]:
    """Return page widths from a PDF."""
    return [float(page.mediabox.width) for page in PdfReader(path).pages]


@pytest.mark.parametrize("output_option", ["-o", "--output"])
def test_parser_accepts_two_paths_and_output_alias(output_option: str) -> None:
    arguments = build_parser().parse_args(
        ["pdf", "merge", "first.pdf", "second.pdf", output_option, "combined.pdf"]
    )

    assert arguments.first_input == Path("first.pdf")
    assert arguments.input_paths == [Path("second.pdf")]
    assert arguments.output_path == Path("combined.pdf")
    assert arguments.command_handler == "pdf_merge"


def test_parser_preserves_more_than_two_input_paths() -> None:
    arguments = build_parser().parse_args(
        [
            "pdf",
            "merge",
            "third.pdf",
            "first.pdf",
            "second.pdf",
            "--output",
            "combined.pdf",
        ]
    )

    assert (arguments.first_input, *arguments.input_paths) == (
        Path("third.pdf"),
        Path("first.pdf"),
        Path("second.pdf"),
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["pdf", "merge"],
        ["pdf", "merge", "one.pdf", "--output", "output.pdf"],
        ["pdf", "merge", "one.pdf", "two.pdf"],
        ["pdf", "merge", "one.pdf", "two.pdf", "--unknown"],
    ],
)
def test_invalid_merge_usage_returns_two_without_execution(
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def unexpected_merge(input_paths: tuple[Path, ...], output_path: Path) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(dispatch_module, "run_pdf_merge", unexpected_merge)

    assert main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage: docuforge pdf merge" in captured.err
    assert called is False


def test_merge_help_describes_inputs_and_output_aliases(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["pdf", "merge", "--help"]) == 0

    captured = capsys.readouterr()
    assert "INPUT [INPUT ...]" in captured.out
    assert "-o OUTPUT" in captured.out
    assert "--output OUTPUT" in captured.out
    assert captured.err == ""


def test_dispatch_passes_paths_to_merge_handler_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: tuple[tuple[Path, ...], Path] | None = None

    def record_merge(input_paths: tuple[Path, ...], output_path: Path) -> int:
        nonlocal received
        received = (input_paths, output_path)
        return 17

    monkeypatch.setattr(dispatch_module, "run_pdf_merge", record_merge)

    result = main(
        ["pdf", "merge", "third.pdf", "first.pdf", "second.pdf", "-o", "out.pdf"]
    )

    assert result == 17
    assert received == (
        (Path("third.pdf"), Path("first.pdf"), Path("second.pdf")),
        Path("out.pdf"),
    )


def test_parser_construction_does_not_execute_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_merge(input_paths: tuple[Path, ...], output_path: Path) -> int:
        raise AssertionError("merge must not run during parser construction")

    monkeypatch.setattr(dispatch_module, "run_pdf_merge", unexpected_merge)

    build_parser()


@pytest.mark.parametrize("output_option", ["-o", "--output"])
def test_main_merges_two_pdfs_with_exact_success_output(
    tmp_path: Path,
    output_option: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    output = tmp_path / "combined.pdf"
    write_pdf(first, (100,))
    write_pdf(second, (200, 210))

    result = main(
        ["pdf", "merge", str(first), str(second), output_option, str(output)]
    )

    assert result == 0
    assert page_widths(output) == [100, 200, 210]
    captured = capsys.readouterr()
    assert captured.out == f"Merged 2 PDF files into {output}\n"
    assert captured.err == ""


def test_main_merges_more_than_two_pdfs_in_input_order(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    third = tmp_path / "third.pdf"
    output = tmp_path / "all.pdf"
    write_pdf(first, (100,))
    write_pdf(second, (200, 210))
    write_pdf(third, (300,))

    assert main(
        ["pdf", "merge", str(first), str(second), str(third), "-o", str(output)]
    ) == 0

    assert page_widths(output) == [100, 200, 210, 300]
    captured = capsys.readouterr()
    assert captured.out == f"Merged 3 PDF files into {output}\n"
    assert captured.err == ""


def test_main_preserves_relative_output_in_success_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("FIRST.PDF"), (100,))
    write_pdf(Path("SECOND.Pdf"), (200,))

    assert main(
        ["pdf", "merge", "FIRST.PDF", "SECOND.Pdf", "--output", "COMBINED.PDF"]
    ) == 0

    assert page_widths(Path("COMBINED.PDF")) == [100, 200]
    captured = capsys.readouterr()
    assert captured.out == "Merged 2 PDF files into COMBINED.PDF\n"
    assert captured.err == ""


@pytest.mark.parametrize(
    ("input_names", "output_name", "expected_error"),
    [
        (
            ("notes.txt", "second.pdf"),
            "failed.pdf",
            "Input file must use the .pdf extension: notes.txt",
        ),
        (
            ("first.pdf", "second.pdf"),
            "combined.txt",
            "Output file must use the .pdf extension: combined.txt",
        ),
        (
            ("missing.pdf", "second.pdf"),
            "failed.pdf",
            "Input file does not exist: missing.pdf.",
        ),
    ],
)
def test_main_reports_expected_validation_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    input_names: tuple[str, str],
    output_name: str,
    expected_error: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("first.pdf"), (100,))
    write_pdf(Path("second.pdf"), (200,))

    assert main(
        ["pdf", "merge", *input_names, "--output", output_name]
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Error: {expected_error}\n"
    assert "Traceback" not in captured.err
    assert "Merged" not in captured.err
    assert not Path(output_name).exists()


def test_main_reports_malformed_pdf_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("malformed.pdf").write_bytes(b"not a PDF")
    write_pdf(Path("second.pdf"), (200,))

    assert main(
        ["pdf", "merge", "malformed.pdf", "second.pdf", "-o", "output.pdf"]
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Unable to merge the requested PDF documents.\n"
    assert "Traceback" not in captured.err
    assert not Path("output.pdf").exists()


def test_run_pdf_merge_preserves_converter_stderr_and_translates_public_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_conversion(
        converter: PdfMergeConverter,
        request: ConversionRequest,
    ) -> Path:
        print("converter diagnostic", file=sys.stderr)
        raise PdfProcessingError("simulated merge failure")

    monkeypatch.setattr(PdfMergeConverter, "convert", fail_conversion)

    assert run_pdf_merge(
        (Path("first.pdf"), Path("second.pdf")),
        Path("output.pdf"),
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "converter diagnostic\nError: simulated merge failure\n"


def test_run_pdf_merge_does_not_catch_unexpected_converter_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_conversion(
        converter: PdfMergeConverter,
        request: ConversionRequest,
    ) -> Path:
        raise RuntimeError("unexpected merge failure")

    monkeypatch.setattr(PdfMergeConverter, "convert", fail_conversion)

    with pytest.raises(RuntimeError, match="unexpected merge failure"):
        run_pdf_merge(
            (Path("first.pdf"), Path("second.pdf")),
            Path("output.pdf"),
        )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_cli_passes_invalid_extension_to_public_converter(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    received_request: ConversionRequest | None = None

    def reject_request(
        converter: PdfMergeConverter,
        request: ConversionRequest,
    ) -> Path:
        nonlocal received_request
        received_request = request
        raise InvalidConversionRequestError(
            f"Input file must use the .pdf extension: {request.input_paths[0]}"
        )

    monkeypatch.setattr(PdfMergeConverter, "convert", reject_request)

    assert main(
        ["pdf", "merge", "notes.txt", "second.pdf", "-o", "output.pdf"]
    ) == 1

    assert received_request is not None
    assert received_request.input_paths == (Path("notes.txt"), Path("second.pdf"))
    captured = capsys.readouterr()
    assert captured.err == "Error: Input file must use the .pdf extension: notes.txt\n"


def test_python_module_entry_point_merges_pdfs(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    output = tmp_path / "output.pdf"
    write_pdf(first, (100,))
    write_pdf(second, (200,))
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    source_path = str(project_root / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        path for path in (source_path, environment.get("PYTHONPATH")) if path
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "docuforge",
            "pdf",
            "merge",
            str(first),
            str(second),
            "-o",
            str(output),
        ],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == f"Merged 2 PDF files into {output}\n"
    assert result.stderr == ""
    assert page_widths(output) == [100, 200]


def test_python_module_entry_point_reports_only_public_malformed_pdf_error(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "malformed.pdf"
    second = tmp_path / "second.pdf"
    output = tmp_path / "output.pdf"
    malformed.write_bytes(b"not a PDF")
    write_pdf(second, (200,))
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    source_path = str(project_root / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        path for path in (source_path, environment.get("PYTHONPATH")) if path
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "docuforge",
            "pdf",
            "merge",
            str(malformed),
            str(second),
            "-o",
            str(output),
        ],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Error: Unable to merge the requested PDF documents.\n"
    assert not output.exists()


def test_installed_console_script_merges_pdfs(tmp_path: Path) -> None:
    executable = shutil.which("docuforge")
    if executable is None:
        pytest.skip("the docuforge console script is not installed")
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    output = tmp_path / "output.pdf"
    write_pdf(first, (100,))
    write_pdf(second, (200,))

    result = subprocess.run(
        [executable, "pdf", "merge", str(first), str(second), "-o", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == f"Merged 2 PDF files into {output}\n"
    assert result.stderr == ""
    assert page_widths(output) == [100, 200]

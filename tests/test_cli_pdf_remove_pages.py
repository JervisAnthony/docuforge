"""Focused tests for PDF page-removal command-line execution."""

import sys
from argparse import ArgumentTypeError
from collections.abc import Sequence
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

import docuforge.cli.commands.pdf_remove_pages as remove_pages_module
import docuforge.cli.dispatch as dispatch_module
from docuforge.__main__ import main
from docuforge.cli.commands.pdf_remove_pages import run_pdf_remove_pages
from docuforge.cli.dispatch import dispatch
from docuforge.cli.parser import PAGE_NUMBER_ERROR, build_parser, parse_positive_page
from docuforge.converters import (
    PdfProcessingError,
    PdfRemovePagesPathRequest,
    PdfRemovePagesPathResult,
)


def write_pdf(path: Path, page_sizes: tuple[tuple[float, float], ...]) -> None:
    """Write a PDF with distinguishable pages."""
    writer = PdfWriter()
    try:
        for width, height in page_sizes:
            writer.add_blank_page(width=width, height=height)
        writer.write(path)
    finally:
        writer.close()


def write_encrypted_pdf(path: Path) -> None:
    """Write a one-page encrypted PDF."""
    writer = PdfWriter()
    try:
        writer.add_blank_page(width=100, height=200)
        writer.encrypt("secret")
        writer.write(path)
    finally:
        writer.close()


def page_sizes(path: Path) -> list[tuple[float, float]]:
    """Return ordered page dimensions."""
    return [
        (float(page.mediabox.width), float(page.mediabox.height))
        for page in PdfReader(path).pages
    ]


@pytest.mark.parametrize(("value", "expected"), [("1", 1), ("2", 2), ("999", 999)])
def test_parse_positive_page_accepts_positive_integers(value: str, expected: int) -> None:
    assert parse_positive_page(value) == expected


@pytest.mark.parametrize(
    "value",
    ["0", "-1", "+1", "nope", "1.0", "1-3", "1,2", "1_0", " 1"],
)
def test_parse_positive_page_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ArgumentTypeError, match=PAGE_NUMBER_ERROR):
        parse_positive_page(value)


@pytest.mark.parametrize("output_option", ["-o", "--output"])
def test_parser_registers_remove_pages_and_preserves_page_order(
    output_option: str,
) -> None:
    arguments = build_parser().parse_args(
        [
            "pdf",
            "remove-pages",
            "source.pdf",
            output_option,
            "trimmed.pdf",
            "--page",
            "4",
            "--page",
            "2",
            "--page",
            "5",
        ]
    )

    assert arguments.input_path == Path("source.pdf")
    assert arguments.output_path == Path("trimmed.pdf")
    assert arguments.pages == [4, 2, 5]
    assert arguments.command_handler == "pdf_remove_pages"


@pytest.mark.parametrize(
    "arguments",
    [
        ["pdf", "remove-pages"],
        ["pdf", "remove-pages", "source.pdf"],
        ["pdf", "remove-pages", "source.pdf", "-o", "output.pdf"],
        ["pdf", "remove-pages", "source.pdf", "--page", "1"],
        ["pdf", "remove-pages", "source.pdf", "-o", "output.pdf", "--page", "0"],
        ["pdf", "remove-pages", "source.pdf", "-o", "output.pdf", "--page", "-1"],
        ["pdf", "remove-pages", "source.pdf", "-o", "output.pdf", "--page", "x"],
        ["pdf", "remove-pages", "source.pdf", "-o", "output.pdf", "--page", "1-3"],
        ["pdf", "remove-pages", "source.pdf", "-o", "output.pdf", "--page", "1,2"],
    ],
)
def test_invalid_remove_pages_usage_returns_two_without_execution(
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def unexpected_remove(
        input_path: Path,
        output_path: Path,
        pages: Sequence[int],
    ) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(dispatch_module, "run_pdf_remove_pages", unexpected_remove)

    assert main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err
    assert called is False


def test_duplicate_pages_report_first_duplicate_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def unexpected_remove(
        input_path: Path,
        output_path: Path,
        pages: Sequence[int],
    ) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(dispatch_module, "run_pdf_remove_pages", unexpected_remove)

    assert main(
        [
            "pdf",
            "remove-pages",
            "source.pdf",
            "-o",
            "output.pdf",
            "--page",
            "2",
            "--page",
            "4",
            "--page",
            "2",
            "--page",
            "4",
        ]
    ) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Each page may be removed only once: 2" in captured.err
    assert "once: 4" not in captured.err
    assert called is False


def test_remove_pages_help_documents_required_syntax(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["pdf", "remove-pages", "--help"]) == 0

    captured = capsys.readouterr()
    assert "usage: docuforge pdf remove-pages" in captured.out
    assert "INPUT" in captured.out
    assert "-o OUTPUT" in captured.out
    assert "--output OUTPUT" in captured.out
    assert "--page PAGE" in captured.out
    assert "one-based" in captured.out
    assert "repeat" in captured.out.lower()
    assert captured.err == ""


def test_dispatch_preserves_paths_pages_and_return_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = build_parser().parse_args(
        [
            "pdf",
            "remove-pages",
            "relative/source.pdf",
            "-o",
            "relative/output.pdf",
            "--page",
            "4",
            "--page",
            "2",
        ]
    )
    received: tuple[Path, Path, Sequence[int]] | None = None

    def remove(input_path: Path, output_path: Path, pages: Sequence[int]) -> int:
        nonlocal received
        received = (input_path, output_path, pages)
        return 17

    monkeypatch.setattr(dispatch_module, "run_pdf_remove_pages", remove)

    assert dispatch(arguments) == 17
    assert received is not None
    assert received[0] is arguments.input_path
    assert received[1] is arguments.output_path
    assert received[2] is arguments.pages


@pytest.mark.parametrize(
    ("pages", "expected_indices"),
    [([1], (0,)), ([2, 4], (1, 3)), ([4, 2, 5], (3, 1, 4))],
)
def test_run_pdf_remove_pages_converts_once_and_delegates_once(
    pages: list[int],
    expected_indices: tuple[int, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = Path("relative/source.pdf")
    output_path = Path("relative/requested.pdf")
    returned_output = Path("library/returned.pdf")
    requests: list[PdfRemovePagesPathRequest] = []

    def remove(request: PdfRemovePagesPathRequest) -> PdfRemovePagesPathResult:
        requests.append(request)
        return PdfRemovePagesPathResult(
            request.input_path,
            returned_output,
            request.page_indices,
        )

    monkeypatch.setattr(remove_pages_module, "remove_pdf_pages", remove)

    assert run_pdf_remove_pages(input_path, output_path, pages) == 0
    assert len(requests) == 1
    assert isinstance(requests[0], PdfRemovePagesPathRequest)
    assert requests[0].input_path is input_path
    assert requests[0].output_path is output_path
    assert requests[0].page_indices == expected_indices
    captured = capsys.readouterr()
    assert captured.out == f"Removed {len(pages)} pages into {returned_output}\n"
    assert str(output_path) not in captured.out
    assert captured.err == ""


def test_run_pdf_remove_pages_performs_no_filesystem_or_low_level_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_request: PdfRemovePagesPathRequest | None = None

    def remove(request: PdfRemovePagesPathRequest) -> PdfRemovePagesPathResult:
        nonlocal received_request
        received_request = request
        return PdfRemovePagesPathResult(
            request.input_path,
            Path("returned.pdf"),
            request.page_indices,
        )

    def unexpected_work(*args: object, **kwargs: object) -> object:
        raise AssertionError("the command must not perform filesystem work")

    monkeypatch.setattr(remove_pages_module, "remove_pdf_pages", remove)
    for method_name in ("exists", "is_file", "resolve", "mkdir", "open"):
        monkeypatch.setattr(Path, method_name, unexpected_work)

    assert run_pdf_remove_pages(Path("source.pdf"), Path("output.pdf"), [5]) == 0
    assert received_request is not None
    assert received_request.page_indices == (4,)


def test_run_pdf_remove_pages_rejects_duplicate_before_api_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def unexpected_remove(request: PdfRemovePagesPathRequest) -> PdfRemovePagesPathResult:
        nonlocal called
        called = True
        raise AssertionError("duplicate pages must not reach the path API")

    monkeypatch.setattr(remove_pages_module, "remove_pdf_pages", unexpected_remove)

    assert run_pdf_remove_pages(
        Path("source.pdf"),
        Path("output.pdf"),
        [3, 1, 3, 1],
    ) == 2
    assert called is False
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Each page may be removed only once: 3\n"


def test_run_pdf_remove_pages_reports_public_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(request: PdfRemovePagesPathRequest) -> PdfRemovePagesPathResult:
        print("operation diagnostic", file=sys.stderr)
        raise PdfProcessingError("simulated removal failure")

    monkeypatch.setattr(remove_pages_module, "remove_pdf_pages", fail)

    assert run_pdf_remove_pages(Path("source.pdf"), Path("output.pdf"), [1]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "operation diagnostic\nError: simulated removal failure\n"


def test_run_pdf_remove_pages_does_not_catch_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(request: PdfRemovePagesPathRequest) -> PdfRemovePagesPathResult:
        raise RuntimeError("unexpected removal failure")

    monkeypatch.setattr(remove_pages_module, "remove_pdf_pages", fail)

    with pytest.raises(RuntimeError, match="unexpected removal failure"):
        run_pdf_remove_pages(Path("source.pdf"), Path("output.pdf"), [1])


@pytest.mark.parametrize(
    ("removed_pages", "expected_sizes"),
    [
        ([1], [(200, 300), (300, 400), (400, 500), (500, 600)]),
        ([3], [(100, 200), (200, 300), (400, 500), (500, 600)]),
        ([5], [(100, 200), (200, 300), (300, 400), (400, 500)]),
        ([4, 2], [(100, 200), (300, 400), (500, 600)]),
    ],
)
def test_main_removes_selected_pages_without_changing_source(
    removed_pages: list[int],
    expected_sizes: list[tuple[float, float]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    original = [(100, 200), (200, 300), (300, 400), (400, 500), (500, 600)]
    write_pdf(Path("source.pdf"), tuple(original))
    arguments = ["pdf", "remove-pages", "source.pdf", "-o", "trimmed.pdf"]
    for page in removed_pages:
        arguments.extend(("--page", str(page)))

    assert main(arguments) == 0
    assert page_sizes(Path("trimmed.pdf")) == expected_sizes
    assert page_sizes(Path("source.pdf")) == original
    captured = capsys.readouterr()
    assert captured.out == f"Removed {len(removed_pages)} pages into trimmed.pdf\n"
    assert captured.err == ""


def test_main_accepts_uppercase_paths_and_replaces_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("SOURCE.PDF"), ((100, 200), (300, 400)))
    write_pdf(Path("OUTPUT.PDF"), ((1, 2), (3, 4), (5, 6)))

    assert main(
        ["pdf", "remove-pages", "SOURCE.PDF", "-o", "OUTPUT.PDF", "--page", "2"]
    ) == 0
    assert page_sizes(Path("OUTPUT.PDF")) == [(100, 200)]


@pytest.mark.parametrize(
    ("input_name", "output_name", "expected_error"),
    [
        ("source.txt", "output.pdf", "Input file must use the .pdf extension: source.txt"),
        ("source.pdf", "output.txt", "Output file must use the .pdf extension: output.txt"),
        ("missing.pdf", "output.pdf", "Input file does not exist: missing.pdf."),
    ],
)
def test_main_reports_path_validation_failures(
    input_name: str,
    output_name: str,
    expected_error: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("source.pdf"), ((100, 200), (300, 400)))

    assert main(
        ["pdf", "remove-pages", input_name, "-o", output_name, "--page", "1"]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Error: {expected_error}\n"


def test_main_reports_missing_output_parent_without_creating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("source.pdf"), ((100, 200), (300, 400)))

    assert main(
        [
            "pdf",
            "remove-pages",
            "source.pdf",
            "-o",
            "missing/output.pdf",
            "--page",
            "1",
        ]
    ) == 1
    assert not Path("missing").exists()
    captured = capsys.readouterr()
    assert captured.err == "Error: Output parent directory does not exist: missing.\n"


def test_main_reports_input_output_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("source.pdf"), ((100, 200), (300, 400)))

    assert main(
        ["pdf", "remove-pages", "source.pdf", "-o", "source.pdf", "--page", "1"]
    ) == 1
    captured = capsys.readouterr()
    assert captured.err == "Error: Output path must not resolve to the input file.\n"


@pytest.mark.parametrize(
    ("kind", "expected_error"),
    [
        ("malformed", "Unable to remove pages from the requested PDF document."),
        ("encrypted", "Encrypted PDF requires a password: input.pdf."),
    ],
)
def test_main_reports_unreadable_pdf_failures(
    kind: str,
    expected_error: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    if kind == "malformed":
        Path("input.pdf").write_bytes(b"not a PDF")
    else:
        write_encrypted_pdf(Path("input.pdf"))

    assert main(
        ["pdf", "remove-pages", "input.pdf", "-o", "output.pdf", "--page", "1"]
    ) == 1
    assert not Path("output.pdf").exists()
    captured = capsys.readouterr()
    assert captured.err == f"Error: {expected_error}\n"


@pytest.mark.parametrize(
    ("pages", "expected_error"),
    [([3], "Page index is out of range: 2"), ([1, 2], "At least one PDF page must remain after removal.")],
)
def test_main_propagates_content_dependent_removal_failures(
    pages: list[int],
    expected_error: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("source.pdf"), ((100, 200), (300, 400)))
    arguments = ["pdf", "remove-pages", "source.pdf", "-o", "output.pdf"]
    for page in pages:
        arguments.extend(("--page", str(page)))

    assert main(arguments) == 1
    assert not Path("output.pdf").exists()
    captured = capsys.readouterr()
    assert captured.err == f"Error: {expected_error}\n"

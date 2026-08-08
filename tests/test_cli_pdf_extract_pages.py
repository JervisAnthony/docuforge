"""Focused tests for PDF page-extraction command-line execution."""

import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

import docuforge.cli.commands.pdf_extract_pages as extract_pages_module
import docuforge.cli.dispatch as dispatch_module
from docuforge.__main__ import main
from docuforge.cli.commands.pdf_extract_pages import run_pdf_extract_pages
from docuforge.cli.dispatch import dispatch
from docuforge.cli.parser import build_parser
from docuforge.converters import (
    PdfExtractPagesPathRequest,
    PdfExtractPagesPathResult,
    PdfProcessingError,
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
        for page in PdfReader(path, strict=True).pages
    ]


@pytest.mark.parametrize("output_option", ["-o", "--output"])
def test_parser_registers_extract_pages_and_preserves_page_order(
    output_option: str,
) -> None:
    arguments = build_parser().parse_args(
        [
            "pdf",
            "extract-pages",
            "source.pdf",
            output_option,
            "selected.pdf",
            "--page",
            "4",
            "--page",
            "2",
            "--page",
            "5",
        ]
    )

    assert arguments.input_path == Path("source.pdf")
    assert arguments.output_path == Path("selected.pdf")
    assert arguments.pages == [4, 2, 5]
    assert arguments.command_handler == "pdf_extract_pages"


@pytest.mark.parametrize(
    "arguments",
    [
        ["pdf", "extract-pages"],
        ["pdf", "extract-pages", "source.pdf"],
        ["pdf", "extract-pages", "source.pdf", "-o", "output.pdf"],
        ["pdf", "extract-pages", "source.pdf", "--page", "1"],
        ["pdf", "extract-pages", "source.pdf", "-o", "output.pdf", "--page", "0"],
        ["pdf", "extract-pages", "source.pdf", "-o", "output.pdf", "--page", "-1"],
        ["pdf", "extract-pages", "source.pdf", "-o", "output.pdf", "--page", "x"],
        ["pdf", "extract-pages", "source.pdf", "-o", "output.pdf", "--page", "1-3"],
        ["pdf", "extract-pages", "source.pdf", "-o", "output.pdf", "--page", "1,2"],
    ],
)
def test_invalid_extract_pages_usage_returns_two_without_execution(
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def unexpected_extract(
        input_path: Path,
        output_path: Path,
        pages: Sequence[int],
    ) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(dispatch_module, "run_pdf_extract_pages", unexpected_extract)

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

    def unexpected_extract(
        input_path: Path,
        output_path: Path,
        pages: Sequence[int],
    ) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(dispatch_module, "run_pdf_extract_pages", unexpected_extract)

    assert main(
        [
            "pdf",
            "extract-pages",
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
    assert "Each page may be extracted only once: 2" in captured.err
    assert "once: 4" not in captured.err
    assert called is False


def test_extract_pages_help_documents_ordered_syntax(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["pdf", "extract-pages", "--help"]) == 0

    captured = capsys.readouterr()
    assert "usage: docuforge pdf extract-pages" in captured.out
    assert "INPUT" in captured.out
    assert "-o OUTPUT" in captured.out
    assert "--output OUTPUT" in captured.out
    assert "--page PAGE" in captured.out
    assert "one-based" in captured.out
    assert "order" in captured.out.lower()
    assert captured.err == ""


def test_dispatch_preserves_paths_pages_and_return_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = build_parser().parse_args(
        [
            "pdf",
            "extract-pages",
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

    def extract(input_path: Path, output_path: Path, pages: Sequence[int]) -> int:
        nonlocal received
        received = (input_path, output_path, pages)
        return 17

    monkeypatch.setattr(dispatch_module, "run_pdf_extract_pages", extract)

    assert dispatch(arguments) == 17
    assert received is not None
    assert received[0] is arguments.input_path
    assert received[1] is arguments.output_path
    assert received[2] is arguments.pages


@pytest.mark.parametrize(
    ("pages", "expected_indices"),
    [([1], (0,)), ([2, 4], (1, 3)), ([4, 2, 5], (3, 1, 4))],
)
def test_run_pdf_extract_pages_converts_once_and_delegates_once(
    pages: list[int],
    expected_indices: tuple[int, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = Path("relative/source.pdf")
    output_path = Path("relative/requested.pdf")
    returned_output = Path("library/returned.pdf")
    requests: list[PdfExtractPagesPathRequest] = []

    def extract(request: PdfExtractPagesPathRequest) -> PdfExtractPagesPathResult:
        requests.append(request)
        return PdfExtractPagesPathResult(
            request.input_path,
            returned_output,
            request.page_indices,
        )

    monkeypatch.setattr(extract_pages_module, "extract_pdf_pages", extract)

    assert run_pdf_extract_pages(input_path, output_path, pages) == 0
    assert len(requests) == 1
    assert requests[0].input_path is input_path
    assert requests[0].output_path is output_path
    assert requests[0].page_indices == expected_indices
    captured = capsys.readouterr()
    assert captured.out == f"Extracted {len(pages)} pages into {returned_output}\n"
    assert str(output_path) not in captured.out
    assert captured.err == ""


def test_run_pdf_extract_pages_performs_no_filesystem_or_low_level_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_request: PdfExtractPagesPathRequest | None = None

    def extract(request: PdfExtractPagesPathRequest) -> PdfExtractPagesPathResult:
        nonlocal received_request
        received_request = request
        return PdfExtractPagesPathResult(
            request.input_path,
            Path("returned.pdf"),
            request.page_indices,
        )

    def unexpected_work(*args: object, **kwargs: object) -> object:
        raise AssertionError("the command must not perform filesystem work")

    monkeypatch.setattr(extract_pages_module, "extract_pdf_pages", extract)
    for method_name in ("exists", "is_file", "resolve", "mkdir", "open"):
        monkeypatch.setattr(Path, method_name, unexpected_work)

    assert run_pdf_extract_pages(Path("source.pdf"), Path("output.pdf"), [999]) == 0
    assert received_request is not None
    assert received_request.page_indices == (998,)
    assert "PdfExtractPagesConverter" not in vars(extract_pages_module)


def test_run_pdf_extract_pages_rejects_duplicate_before_api_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def unexpected_extract(
        request: PdfExtractPagesPathRequest,
    ) -> PdfExtractPagesPathResult:
        nonlocal called
        called = True
        raise AssertionError("duplicate pages must not reach the path API")

    monkeypatch.setattr(extract_pages_module, "extract_pdf_pages", unexpected_extract)

    assert run_pdf_extract_pages(
        Path("source.pdf"),
        Path("output.pdf"),
        [3, 1, 3, 1],
    ) == 2
    assert called is False
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Each page may be extracted only once: 3\n"


def test_run_pdf_extract_pages_reports_public_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(request: PdfExtractPagesPathRequest) -> PdfExtractPagesPathResult:
        print("operation diagnostic", file=sys.stderr)
        raise PdfProcessingError("simulated extraction failure")

    monkeypatch.setattr(extract_pages_module, "extract_pdf_pages", fail)

    assert run_pdf_extract_pages(Path("source.pdf"), Path("output.pdf"), [1]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "operation diagnostic\nError: simulated extraction failure\n"


def test_run_pdf_extract_pages_does_not_catch_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(request: PdfExtractPagesPathRequest) -> PdfExtractPagesPathResult:
        raise RuntimeError("unexpected extraction failure")

    monkeypatch.setattr(extract_pages_module, "extract_pdf_pages", fail)

    with pytest.raises(RuntimeError, match="unexpected extraction failure"):
        run_pdf_extract_pages(Path("source.pdf"), Path("output.pdf"), [1])


@pytest.mark.parametrize(
    ("selected_pages", "expected_sizes"),
    [
        ([1], [(100, 200)]),
        ([3], [(300, 400)]),
        ([5], [(500, 600)]),
        ([2, 4], [(200, 300), (400, 500)]),
        ([4, 2, 5], [(400, 500), (200, 300), (500, 600)]),
    ],
)
def test_main_extracts_selected_pages_in_user_order_without_changing_source(
    selected_pages: list[int],
    expected_sizes: list[tuple[float, float]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    original = [(100, 200), (200, 300), (300, 400), (400, 500), (500, 600)]
    write_pdf(Path("source.pdf"), tuple(original))
    source_before = Path("source.pdf").read_bytes()
    arguments = ["pdf", "extract-pages", "source.pdf", "-o", "selected.pdf"]
    for page in selected_pages:
        arguments.extend(("--page", str(page)))

    assert main(arguments) == 0
    assert page_sizes(Path("selected.pdf")) == expected_sizes
    assert len(PdfReader(Path("selected.pdf"), strict=True).pages) == len(selected_pages)
    assert Path("source.pdf").read_bytes() == source_before
    assert page_sizes(Path("source.pdf")) == original
    captured = capsys.readouterr()
    assert captured.out == f"Extracted {len(selected_pages)} pages into selected.pdf\n"
    assert captured.err == ""


def test_main_accepts_uppercase_paths_and_replaces_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("SOURCE.PDF"), ((100, 200), (300, 400)))
    write_pdf(Path("OUTPUT.PDF"), ((1, 2), (3, 4), (5, 6)))

    assert main(
        ["pdf", "extract-pages", "SOURCE.PDF", "-o", "OUTPUT.PDF", "--page", "2"]
    ) == 0
    assert page_sizes(Path("OUTPUT.PDF")) == [(300, 400)]


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
        ["pdf", "extract-pages", input_name, "-o", output_name, "--page", "1"]
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
            "extract-pages",
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
        ["pdf", "extract-pages", "source.pdf", "-o", "source.pdf", "--page", "1"]
    ) == 1
    captured = capsys.readouterr()
    assert captured.err == "Error: Output path must not resolve to the input file.\n"


@pytest.mark.parametrize(
    ("kind", "expected_error"),
    [
        ("malformed", "Unable to extract the requested PDF pages."),
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
        ["pdf", "extract-pages", "input.pdf", "-o", "output.pdf", "--page", "1"]
    ) == 1
    assert not Path("output.pdf").exists()
    captured = capsys.readouterr()
    assert captured.err == f"Error: {expected_error}\n"


def test_main_delegates_out_of_range_positive_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("source.pdf"), ((100, 200), (300, 400)))

    assert main(
        ["pdf", "extract-pages", "source.pdf", "-o", "output.pdf", "--page", "999"]
    ) == 1
    assert not Path("output.pdf").exists()
    captured = capsys.readouterr()
    assert captured.err == "Error: Page index is out of range: 998\n"

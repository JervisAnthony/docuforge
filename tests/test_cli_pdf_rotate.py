"""Focused tests for PDF rotation command-line execution."""

import os
import shutil
import subprocess
import sys
from argparse import ArgumentTypeError
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

import docuforge.cli.commands.pdf_rotate as pdf_rotate_module
import docuforge.cli.dispatch as dispatch_module
from docuforge.__main__ import main
from docuforge.cli.commands.pdf_rotate import run_pdf_rotate
from docuforge.cli.dispatch import dispatch
from docuforge.cli.parser import (
    ROTATION_SYNTAX_ERROR,
    build_parser,
    parse_page_rotation,
)
from docuforge.converters import (
    PageRotation,
    PdfProcessingError,
    PdfRotatePathRequest,
    PdfRotatePathResult,
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


def page_metadata(path: Path) -> list[tuple[float, float, int]]:
    """Return page dimensions and clockwise rotations."""
    return [
        (float(page.mediabox.width), float(page.mediabox.height), page.rotation)
        for page in PdfReader(path).pages
    ]


def module_environment() -> dict[str, str]:
    """Return an environment that imports DocuForge from this source tree."""
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    source_path = str(project_root / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        path for path in (source_path, environment.get("PYTHONPATH")) if path
    )
    return environment


@pytest.mark.parametrize(
    ("value", "page_index", "degrees"),
    [("1:90", 0, 90), ("2:180", 1, 180), ("10:270", 9, 270)],
)
def test_parse_page_rotation_translates_one_based_page_numbers(
    value: str,
    page_index: int,
    degrees: int,
) -> None:
    rotation = parse_page_rotation(value)

    assert isinstance(rotation, PageRotation)
    assert rotation.page_index == page_index
    assert rotation.degrees == degrees


@pytest.mark.parametrize(
    "value",
    [
        "1",
        "1:",
        ":90",
        "1:90:extra",
        "1,90",
        "1-90",
        "0:90",
        "-1:90",
        "+1:90",
        "1.0:90",
        "one:90",
        "1:0",
        "1:360",
        "1:-90",
        "1:45",
        "1:ninety",
        "1 :90",
        "1: 90",
    ],
)
def test_parse_page_rotation_rejects_malformed_values(value: str) -> None:
    with pytest.raises(ArgumentTypeError) as exc_info:
        parse_page_rotation(value)

    assert str(exc_info.value) == ROTATION_SYNTAX_ERROR


@pytest.mark.parametrize("value", [True, False, 1, None])
def test_parse_page_rotation_rejects_non_strings(value: object) -> None:
    with pytest.raises(ArgumentTypeError) as exc_info:
        parse_page_rotation(value)  # type: ignore[arg-type]

    assert str(exc_info.value) == ROTATION_SYNTAX_ERROR


def test_parse_page_rotation_performs_no_filesystem_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_access(*args: object, **kwargs: object) -> object:
        raise AssertionError("rotation parsing must not access the filesystem")

    for method_name in ("exists", "is_file", "resolve", "open"):
        monkeypatch.setattr(Path, method_name, unexpected_access)

    assert parse_page_rotation("3:270") == PageRotation(2, 270)


@pytest.mark.parametrize("output_option", ["-o", "--output"])
def test_parser_accepts_ordered_rotations_paths_and_output_alias(
    output_option: str,
) -> None:
    arguments = build_parser().parse_args(
        [
            "pdf",
            "rotate",
            "source.pdf",
            output_option,
            "rotated.pdf",
            "--rotate",
            "3:270",
            "--rotate",
            "1:90",
        ]
    )

    assert isinstance(arguments.input_path, Path)
    assert arguments.input_path == Path("source.pdf")
    assert isinstance(arguments.output_path, Path)
    assert arguments.output_path == Path("rotated.pdf")
    assert arguments.rotations == [PageRotation(2, 270), PageRotation(0, 90)]
    assert arguments.command_handler == "pdf_rotate"


@pytest.mark.parametrize(
    "arguments",
    [
        ["pdf", "rotate"],
        ["pdf", "rotate", "source.pdf"],
        ["pdf", "rotate", "source.pdf", "-o", "output.pdf"],
        [
            "pdf",
            "rotate",
            "first.pdf",
            "second.pdf",
            "-o",
            "output.pdf",
            "--rotate",
            "1:90",
        ],
        [
            "pdf",
            "rotate",
            "source.pdf",
            "-o",
            "output.pdf",
            "--rotate",
            "1:45",
        ],
        [
            "pdf",
            "rotate",
            "source.pdf",
            "-o",
            "output.pdf",
            "--rotate",
            "1:90",
            "--unknown",
        ],
    ],
)
def test_invalid_rotate_usage_returns_two_without_execution(
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def unexpected_rotate(
        input_path: Path,
        output_path: Path,
        rotations: Sequence[PageRotation],
    ) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(dispatch_module, "run_pdf_rotate", unexpected_rotate)

    assert main(arguments) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage: docuforge" in captured.err
    assert "error:" in captured.err
    assert called is False


def test_duplicate_page_instruction_reports_one_based_page_and_does_not_execute(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def unexpected_rotate(
        input_path: Path,
        output_path: Path,
        rotations: Sequence[PageRotation],
    ) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(dispatch_module, "run_pdf_rotate", unexpected_rotate)

    assert main(
        [
            "pdf",
            "rotate",
            "source.pdf",
            "-o",
            "output.pdf",
            "--rotate",
            "1:90",
            "--rotate",
            "2:180",
            "--rotate",
            "1:270",
        ]
    ) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "each page may be rotated only once: 1" in captured.err
    assert "once: 0" not in captured.err
    assert called is False


def test_rotate_help_documents_required_syntax(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["pdf", "rotate", "--help"]) == 0

    captured = capsys.readouterr()
    assert "usage: docuforge pdf rotate" in captured.out
    assert "INPUT" in captured.out
    assert "-o OUTPUT" in captured.out
    assert "--output OUTPUT" in captured.out
    assert "--rotate PAGE:DEGREES" in captured.out
    assert "one-based" in captured.out
    assert all(degrees in captured.out for degrees in ("90", "180", "270"))
    assert "repeat" in captured.out.lower()
    assert captured.err == ""


def test_dispatch_preserves_exact_paths_rotations_order_and_return_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = build_parser().parse_args(
        [
            "pdf",
            "rotate",
            "relative/source.pdf",
            "-o",
            "relative/output.pdf",
            "--rotate",
            "3:270",
            "--rotate",
            "1:90",
        ]
    )
    received: tuple[Path, Path, Sequence[PageRotation]] | None = None

    def run_rotate(
        input_path: Path,
        output_path: Path,
        rotations: Sequence[PageRotation],
    ) -> int:
        nonlocal received
        received = (input_path, output_path, rotations)
        return 17

    monkeypatch.setattr(dispatch_module, "run_pdf_rotate", run_rotate)

    assert dispatch(arguments) == 17
    assert received is not None
    assert received[0] is arguments.input_path
    assert received[1] is arguments.output_path
    assert received[2] is arguments.rotations
    assert all(
        actual is expected
        for actual, expected in zip(received[2], arguments.rotations, strict=True)
    )


def test_parser_construction_does_not_execute_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def unexpected_rotate(
        input_path: Path,
        output_path: Path,
        rotations: Sequence[PageRotation],
    ) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(dispatch_module, "run_pdf_rotate", unexpected_rotate)

    build_parser()

    assert called is False


class ObservedRotationSequence(Sequence[PageRotation]):
    """A sequence that records tuple-construction iteration."""

    def __init__(self, rotations: tuple[PageRotation, ...]) -> None:
        self.rotations = rotations
        self.iteration_count = 0

    def __getitem__(self, index: int) -> PageRotation:
        return self.rotations[index]

    def __len__(self) -> int:
        return len(self.rotations)

    def __iter__(self) -> Iterator[PageRotation]:
        self.iteration_count += 1
        return iter(self.rotations)


def test_run_pdf_rotate_uses_public_request_once_and_result_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = Path("relative/source.pdf")
    output_path = Path("relative/requested.pdf")
    first = PageRotation(2, 270)
    second = PageRotation(0, 90)
    rotations = ObservedRotationSequence((first, second))
    returned_output = Path("library/returned.pdf")
    received_request: PdfRotatePathRequest | None = None
    call_count = 0

    def rotate(request: PdfRotatePathRequest) -> PdfRotatePathResult:
        nonlocal call_count, received_request
        call_count += 1
        received_request = request
        return PdfRotatePathResult(
            input_path=request.input_path,
            output_path=returned_output,
            rotations=request.rotations,
        )

    monkeypatch.setattr(pdf_rotate_module, "rotate_pdf_pages", rotate)

    assert run_pdf_rotate(input_path, output_path, rotations) == 0

    assert call_count == 1
    assert rotations.iteration_count == 1
    assert received_request is not None
    assert received_request.input_path is input_path
    assert received_request.output_path is output_path
    assert received_request.rotations[0] is first
    assert received_request.rotations[1] is second
    captured = capsys.readouterr()
    assert captured.out == f"Rotated 2 pages into {returned_output}\n"
    assert str(output_path) not in captured.out
    assert captured.err == ""


def test_run_pdf_rotate_performs_no_filesystem_or_low_level_work(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = Path("source.pdf")
    output_path = Path("output.pdf")
    rotation = PageRotation(4, 180)
    received_request: PdfRotatePathRequest | None = None

    def rotate(request: PdfRotatePathRequest) -> PdfRotatePathResult:
        nonlocal received_request
        received_request = request
        return PdfRotatePathResult(
            request.input_path,
            Path("returned.pdf"),
            request.rotations,
        )

    def unexpected_work(*args: object, **kwargs: object) -> object:
        raise AssertionError("the command must not perform filesystem work")

    monkeypatch.setattr(pdf_rotate_module, "rotate_pdf_pages", rotate)
    for method_name in ("resolve", "mkdir", "iterdir", "glob"):
        monkeypatch.setattr(Path, method_name, unexpected_work)

    assert run_pdf_rotate(input_path, output_path, [rotation]) == 0

    assert received_request is not None
    assert received_request.rotations == (rotation,)
    assert received_request.rotations[0].page_index == 4
    captured = capsys.readouterr()
    assert captured.out == "Rotated 1 pages into returned.pdf\n"
    assert captured.err == ""


def test_run_pdf_rotate_reports_public_failure_and_preserves_operation_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(request: PdfRotatePathRequest) -> PdfRotatePathResult:
        print("operation diagnostic", file=sys.stderr)
        raise PdfProcessingError("simulated rotation failure")

    monkeypatch.setattr(pdf_rotate_module, "rotate_pdf_pages", fail)

    assert run_pdf_rotate(
        Path("source.pdf"),
        Path("output.pdf"),
        [PageRotation(0, 90)],
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "operation diagnostic\nError: simulated rotation failure\n"
    )
    assert "Traceback" not in captured.err
    assert "Rotated" not in captured.err


def test_run_pdf_rotate_does_not_catch_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(request: PdfRotatePathRequest) -> PdfRotatePathResult:
        raise RuntimeError("unexpected rotation failure")

    monkeypatch.setattr(pdf_rotate_module, "rotate_pdf_pages", fail)

    with pytest.raises(RuntimeError, match="unexpected rotation failure"):
        run_pdf_rotate(
            Path("source.pdf"),
            Path("output.pdf"),
            [PageRotation(0, 90)],
        )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize("degrees", [90, 180, 270])
@pytest.mark.parametrize("output_option", ["-o", "--output"])
def test_main_rotates_one_page_with_exact_success_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    degrees: int,
    output_option: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("source.pdf"), ((100, 200),))

    assert main(
        [
            "pdf",
            "rotate",
            "source.pdf",
            output_option,
            "rotated.pdf",
            "--rotate",
            f"1:{degrees}",
        ]
    ) == 0

    assert page_metadata(Path("rotated.pdf")) == [(100, 200, degrees)]
    assert page_metadata(Path("source.pdf")) == [(100, 200, 0)]
    captured = capsys.readouterr()
    assert captured.out == "Rotated 1 pages into rotated.pdf\n"
    assert captured.err == ""


def test_main_rotates_selected_pages_without_reordering_or_changing_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    original = [(100, 200, 0), (300, 400, 0), (500, 600, 0)]
    write_pdf(Path("source.pdf"), tuple((width, height) for width, height, _ in original))

    assert main(
        [
            "pdf",
            "rotate",
            "source.pdf",
            "--output",
            "nested-name.pdf",
            "--rotate",
            "3:270",
            "--rotate",
            "1:90",
        ]
    ) == 0

    assert page_metadata(Path("nested-name.pdf")) == [
        (100, 200, 90),
        (300, 400, 0),
        (500, 600, 270),
    ]
    assert page_metadata(Path("source.pdf")) == original
    captured = capsys.readouterr()
    assert captured.out == "Rotated 2 pages into nested-name.pdf\n"
    assert captured.err == ""


def test_main_accepts_uppercase_paths_and_replaces_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("SOURCE.PDF"), ((100, 200),))
    write_pdf(Path("OUTPUT.PDF"), ((1, 2), (3, 4)))

    assert main(
        [
            "pdf",
            "rotate",
            "SOURCE.PDF",
            "-o",
            "OUTPUT.PDF",
            "--rotate",
            "1:270",
        ]
    ) == 0

    assert page_metadata(Path("OUTPUT.PDF")) == [(100, 200, 270)]
    captured = capsys.readouterr()
    assert captured.out == "Rotated 1 pages into OUTPUT.PDF\n"
    assert captured.err == ""


@pytest.mark.parametrize(
    ("input_name", "output_name", "expected_error"),
    [
        (
            "source.txt",
            "output.pdf",
            "Input file must use the .pdf extension: source.txt",
        ),
        (
            "source.pdf",
            "output.txt",
            "Output file must use the .pdf extension: output.txt",
        ),
        (
            "missing.pdf",
            "output.pdf",
            "Input file does not exist: missing.pdf.",
        ),
    ],
)
def test_main_reports_public_path_validation_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    input_name: str,
    output_name: str,
    expected_error: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("source.pdf"), ((100, 200),))

    assert main(
        [
            "pdf",
            "rotate",
            input_name,
            "-o",
            output_name,
            "--rotate",
            "1:90",
        ]
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Error: {expected_error}\n"
    assert "Traceback" not in captured.err
    assert "Rotated" not in captured.err


def test_main_reports_directory_input_and_non_directory_output_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("directory.pdf").mkdir()

    assert main(
        [
            "pdf",
            "rotate",
            "directory.pdf",
            "-o",
            "output.pdf",
            "--rotate",
            "1:90",
        ]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Input path is not a file: directory.pdf.\n"

    write_pdf(Path("source.pdf"), ((100, 200),))
    Path("parent").write_text("not a directory", encoding="utf-8")
    assert main(
        [
            "pdf",
            "rotate",
            "source.pdf",
            "-o",
            "parent/output.pdf",
            "--rotate",
            "1:90",
        ]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Error: Output parent directory does not exist: parent.\n"
    )


def test_main_does_not_create_missing_output_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("source.pdf"), ((100, 200),))

    assert main(
        [
            "pdf",
            "rotate",
            "source.pdf",
            "-o",
            "missing/output.pdf",
            "--rotate",
            "1:90",
        ]
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Error: Output parent directory does not exist: missing.\n"
    )
    assert not Path("missing").exists()


def test_main_reports_input_output_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("source.pdf"), ((100, 200),))

    assert main(
        [
            "pdf",
            "rotate",
            "source.pdf",
            "-o",
            "source.pdf",
            "--rotate",
            "1:90",
        ]
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Output path must not resolve to the input file.\n"


@pytest.mark.parametrize("kind", ["malformed", "encrypted"])
def test_main_reports_invalid_pdf_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    input_path = Path(f"{kind}.pdf")
    if kind == "malformed":
        input_path.write_bytes(b"not a PDF")
        expected_error = "Unable to rotate the requested PDF document."
    else:
        write_encrypted_pdf(input_path)
        expected_error = f"Encrypted PDF requires a password: {input_path}."

    assert main(
        [
            "pdf",
            "rotate",
            str(input_path),
            "-o",
            "output.pdf",
            "--rotate",
            "1:90",
        ]
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Error: {expected_error}\n"
    assert "Traceback" not in captured.err
    assert not Path("output.pdf").exists()


def test_main_reports_out_of_range_page_as_runtime_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_pdf(Path("source.pdf"), ((100, 200), (300, 400), (500, 600)))

    assert main(
        [
            "pdf",
            "rotate",
            "source.pdf",
            "-o",
            "output.pdf",
            "--rotate",
            "4:90",
        ]
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Page index is out of range: 3\n"
    assert "Traceback" not in captured.err
    assert not Path("output.pdf").exists()


def test_python_module_entry_point_rotates_pdf(tmp_path: Path) -> None:
    input_path = tmp_path / "source.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200), (300, 400)))
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "docuforge",
            "pdf",
            "rotate",
            str(input_path),
            "-o",
            str(output_path),
            "--rotate",
            "2:180",
        ],
        cwd=project_root,
        env=module_environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == f"Rotated 1 pages into {output_path}\n"
    assert result.stderr == ""
    assert page_metadata(output_path) == [(100, 200, 0), (300, 400, 180)]


def test_python_module_entry_point_reports_only_malformed_pdf_error(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "malformed.pdf"
    output_path = tmp_path / "output.pdf"
    input_path.write_bytes(b"not a PDF")
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "docuforge",
            "pdf",
            "rotate",
            str(input_path),
            "-o",
            str(output_path),
            "--rotate",
            "1:90",
        ],
        cwd=project_root,
        env=module_environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Error: Unable to rotate the requested PDF document.\n"
    assert "Traceback" not in result.stderr
    assert not output_path.exists()


def test_installed_console_script_rotates_pdf(tmp_path: Path) -> None:
    executable = shutil.which("docuforge")
    if executable is None:
        pytest.skip("the docuforge console script is not installed")
    input_path = tmp_path / "source.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200),))

    result = subprocess.run(
        [
            executable,
            "pdf",
            "rotate",
            str(input_path),
            "-o",
            str(output_path),
            "--rotate",
            "1:270",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == f"Rotated 1 pages into {output_path}\n"
    assert result.stderr == ""
    assert page_metadata(output_path) == [(100, 200, 270)]

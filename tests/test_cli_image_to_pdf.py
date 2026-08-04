"""Focused tests for image-to-PDF command-line execution."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

import docuforge.cli.commands.image_to_pdf as image_command_module
import docuforge.cli.dispatch as dispatch_module
from docuforge.__main__ import main
from docuforge.cli.commands.image_to_pdf import run_image_to_pdf
from docuforge.cli.dispatch import dispatch
from docuforge.cli.parser import build_parser
from docuforge.converters import (
    ImageProcessingError,
    ImageToPdfPathRequest,
    ImageToPdfPathResult,
)


def write_image(path: Path, size: tuple[int, int], image_format: str) -> None:
    """Write one RGB image with an observable page size."""
    image = Image.new("RGB", size, "white")
    try:
        image.save(path, format=image_format)
    finally:
        image.close()


def page_sizes(path: Path) -> list[tuple[float, float]]:
    """Return PDF page dimensions in output order."""
    return [
        (float(page.mediabox.width), float(page.mediabox.height))
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


@pytest.mark.parametrize("output_option", ["-o", "--output"])
def test_parser_accepts_ordered_paths_and_output_alias(output_option: str) -> None:
    arguments = build_parser().parse_args(
        [
            "image",
            "to-pdf",
            "third.png",
            "first.jpg",
            "second.bmp",
            output_option,
            "output.pdf",
        ]
    )

    assert arguments.input_paths == [
        Path("third.png"),
        Path("first.jpg"),
        Path("second.bmp"),
    ]
    assert all(isinstance(path, Path) for path in arguments.input_paths)
    assert arguments.output_path == Path("output.pdf")
    assert isinstance(arguments.output_path, Path)
    assert arguments.command_handler == "image_to_pdf"


def test_parser_accepts_one_input() -> None:
    arguments = build_parser().parse_args(
        ["image", "to-pdf", "one.jpeg", "-o", "output.pdf"]
    )

    assert arguments.input_paths == [Path("one.jpeg")]


@pytest.mark.parametrize(
    "arguments",
    [
        ["image", "to-pdf"],
        ["image", "to-pdf", "input.jpg"],
        ["image", "to-pdf", "-o", "output.pdf"],
        ["image", "to-pdf", "input.jpg", "-o", "output.pdf", "--unknown"],
    ],
)
def test_invalid_usage_returns_two_without_conversion(
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def unexpected_conversion(input_paths: list[Path], output_path: Path) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(dispatch_module, "run_image_to_pdf", unexpected_conversion)

    assert main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage: docuforge" in captured.err
    assert "error:" in captured.err
    assert called is False


def test_image_help_describes_repeated_inputs_and_output_aliases(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["image", "to-pdf", "--help"]) == 0

    captured = capsys.readouterr()
    assert "INPUT [INPUT ...]" in captured.out
    assert "-o OUTPUT" in captured.out
    assert "--output OUTPUT" in captured.out
    assert "ordered image files" in captured.out
    assert captured.err == ""


def test_dispatch_preserves_exact_parsed_paths_order_and_return_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = build_parser().parse_args(
        [
            "image",
            "to-pdf",
            "relative/third.png",
            "relative/first.jpg",
            "-o",
            "relative/output.pdf",
        ]
    )
    received_inputs: list[Path] | None = None
    received_output: Path | None = None

    def record_conversion(input_paths: list[Path], output_path: Path) -> int:
        nonlocal received_inputs, received_output
        received_inputs = input_paths
        received_output = output_path
        return 17

    monkeypatch.setattr(dispatch_module, "run_image_to_pdf", record_conversion)

    assert dispatch(arguments) == 17
    assert received_inputs is arguments.input_paths
    assert received_inputs[0] is arguments.input_paths[0]
    assert received_inputs[1] is arguments.input_paths[1]
    assert received_output is arguments.output_path


def test_parser_construction_does_not_execute_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_conversion(input_paths: list[Path], output_path: Path) -> int:
        raise AssertionError("conversion must not run during parser construction")

    monkeypatch.setattr(dispatch_module, "run_image_to_pdf", unexpected_conversion)

    build_parser()


def test_run_image_to_pdf_uses_public_request_and_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = Path("relative/third.unknown")
    second = Path("relative/first.unknown")
    parsed_inputs = [first, second]
    parsed_output = Path("parsed-output.pdf")
    returned_output = Path("library-returned.pdf")
    received_request: ImageToPdfPathRequest | None = None
    call_count = 0

    def convert(request: ImageToPdfPathRequest) -> ImageToPdfPathResult:
        nonlocal call_count, received_request
        call_count += 1
        received_request = request
        return ImageToPdfPathResult(request.input_paths, returned_output)

    monkeypatch.setattr(image_command_module, "convert_images_to_pdf", convert)

    assert run_image_to_pdf(parsed_inputs, parsed_output) == 0

    assert call_count == 1
    assert isinstance(received_request, ImageToPdfPathRequest)
    assert isinstance(received_request.input_paths, tuple)
    assert received_request.input_paths == (first, second)
    assert received_request.input_paths[0] is first
    assert received_request.input_paths[1] is second
    assert received_request.output_path is parsed_output
    captured = capsys.readouterr()
    assert captured.out == "Converted 2 image files into library-returned.pdf\n"
    assert captured.err == ""


def test_run_image_to_pdf_performs_no_filesystem_or_low_level_work(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inputs = [Path("second.invalid"), Path("first.invalid")]
    output = Path("missing/output.invalid")

    def convert(request: ImageToPdfPathRequest) -> ImageToPdfPathResult:
        return ImageToPdfPathResult(request.input_paths, request.output_path)

    def unexpected_call(path: Path, *args: object, **kwargs: object) -> object:
        raise AssertionError("CLI performed filesystem work")

    monkeypatch.setattr(image_command_module, "convert_images_to_pdf", convert)
    monkeypatch.setattr(Path, "exists", unexpected_call)
    monkeypatch.setattr(Path, "is_file", unexpected_call)
    monkeypatch.setattr(Path, "resolve", unexpected_call)
    monkeypatch.setattr(Path, "iterdir", unexpected_call)
    monkeypatch.setattr(Path, "glob", unexpected_call)
    monkeypatch.setattr(Path, "mkdir", unexpected_call)

    assert run_image_to_pdf(inputs, output) == 0
    captured = capsys.readouterr()
    assert captured.out == f"Converted 2 image files into {output}\n"
    assert captured.err == ""
    assert not hasattr(image_command_module, "ImageInput")
    assert not hasattr(image_command_module, "ImageToPdfRequest")
    assert not hasattr(image_command_module, "ImageToPdfConverter")


def test_run_image_to_pdf_reports_public_failure_and_preserves_operation_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = ImageProcessingError("simulated image failure")

    def fail(request: ImageToPdfPathRequest) -> ImageToPdfPathResult:
        print("operation diagnostic", file=sys.stderr)
        raise failure

    monkeypatch.setattr(image_command_module, "convert_images_to_pdf", fail)

    assert run_image_to_pdf([Path("input.jpg")], Path("output.pdf")) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "operation diagnostic\nError: simulated image failure\n"
    assert "Traceback" not in captured.err
    assert "Converted" not in captured.err


def test_run_image_to_pdf_does_not_catch_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = RuntimeError("unexpected image failure")

    def fail(request: ImageToPdfPathRequest) -> ImageToPdfPathResult:
        raise failure

    monkeypatch.setattr(image_command_module, "convert_images_to_pdf", fail)

    with pytest.raises(RuntimeError) as exc_info:
        run_image_to_pdf([Path("input.jpg")], Path("output.pdf"))

    assert exc_info.value is failure
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize("output_option", ["-o", "--output"])
def test_main_converts_one_jpg_with_exact_success_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_option: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    write_image(Path("input.jpg"), (10, 20), "JPEG")

    assert main(["image", "to-pdf", "input.jpg", output_option, "output.pdf"]) == 0

    assert page_sizes(Path("output.pdf")) == [(10, 20)]
    captured = capsys.readouterr()
    assert captured.out == "Converted 1 image files into output.pdf\n"
    assert captured.err == ""


def test_main_converts_mixed_formats_in_command_line_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    inputs = (
        ("third.bmp", (50, 60), "BMP"),
        ("first.jpeg", (10, 20), "JPEG"),
        ("fourth.tiff", (70, 80), "TIFF"),
        ("second.png", (30, 40), "PNG"),
    )
    for name, size, image_format in inputs:
        write_image(Path(name), size, image_format)

    assert main(
        ["image", "to-pdf", *(name for name, _, _ in inputs), "-o", "mixed.pdf"]
    ) == 0

    assert page_sizes(Path("mixed.pdf")) == [
        (50, 60),
        (10, 20),
        (70, 80),
        (30, 40),
    ]
    captured = capsys.readouterr()
    assert captured.out == "Converted 4 image files into mixed.pdf\n"
    assert captured.err == ""


def test_main_accepts_uppercase_aliases_and_replaces_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_image(Path("FIRST.JPEG"), (11, 21), "JPEG")
    write_image(Path("SECOND.PNG"), (31, 41), "PNG")
    write_image(Path("THIRD.TIF"), (51, 61), "TIFF")
    writer = PdfWriter()
    try:
        writer.add_blank_page(width=999, height=999)
        writer.write(Path("OUTPUT.PDF"))
    finally:
        writer.close()

    assert main(
        [
            "image",
            "to-pdf",
            "FIRST.JPEG",
            "SECOND.PNG",
            "THIRD.TIF",
            "--output",
            "OUTPUT.PDF",
        ]
    ) == 0

    assert page_sizes(Path("OUTPUT.PDF")) == [(11, 21), (31, 41), (51, 61)]
    captured = capsys.readouterr()
    assert captured.out == "Converted 3 image files into OUTPUT.PDF\n"
    assert captured.err == ""


@pytest.mark.parametrize(
    ("input_name", "output_name", "expected_error"),
    [
        (
            "animation.gif",
            "output.pdf",
            "Input file must use .jpg, .jpeg, .png, .bmp, .tif, or .tiff: animation.gif",
        ),
        (
            "image.webp",
            "output.pdf",
            "Input file must use .jpg, .jpeg, .png, .bmp, .tif, or .tiff: image.webp",
        ),
        (
            "missing.jpg",
            "output.pdf",
            "Input file does not exist: missing.jpg.",
        ),
        (
            "first.jpg",
            "output.txt",
            "Output file must use the .pdf extension: output.txt",
        ),
    ],
)
def test_main_reports_public_validation_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    input_name: str,
    output_name: str,
    expected_error: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    write_image(Path("first.jpg"), (10, 20), "JPEG")

    assert main(["image", "to-pdf", input_name, "-o", output_name]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Error: {expected_error}\n"
    assert "Traceback" not in captured.err
    assert "Converted" not in captured.err


def test_main_reports_directory_and_duplicate_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("directory.jpg").mkdir()

    assert main(["image", "to-pdf", "directory.jpg", "-o", "output.pdf"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Input path is not a file: directory.jpg.\n"

    write_image(Path("input.jpg"), (10, 20), "JPEG")
    Path("nested").mkdir()
    assert main(
        [
            "image",
            "to-pdf",
            "input.jpg",
            str(Path("nested") / ".." / "input.jpg"),
            "-o",
            "output.pdf",
        ]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Input paths must not resolve to the same file.\n"


def test_main_reports_malformed_and_mismatched_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("malformed.jpg").write_bytes(b"not an image")

    assert main(["image", "to-pdf", "malformed.jpg", "-o", "malformed.pdf"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: Unable to convert the requested images to PDF.\n"
    assert "Traceback" not in captured.err

    write_image(Path("mismatch.jpg"), (10, 20), "PNG")
    assert main(["image", "to-pdf", "mismatch.jpg", "-o", "mismatch.pdf"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Error: Image format does not match its declaration: mismatch.jpg.\n"
    )


def test_main_does_not_create_missing_output_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_image(Path("input.jpg"), (10, 20), "JPEG")

    assert main(
        ["image", "to-pdf", "input.jpg", "-o", "missing/output.pdf"]
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"Error: Output parent directory does not exist: {Path('missing')}.\n"
    )
    assert not Path("missing").exists()


def test_python_module_entry_point_converts_images(tmp_path: Path) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.png"
    output = tmp_path / "output.pdf"
    write_image(first, (10, 20), "JPEG")
    write_image(second, (30, 40), "PNG")
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "docuforge",
            "image",
            "to-pdf",
            str(first),
            str(second),
            "-o",
            str(output),
        ],
        cwd=project_root,
        env=module_environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == f"Converted 2 image files into {output}\n"
    assert result.stderr == ""
    assert page_sizes(output) == [(10, 20), (30, 40)]


def test_python_module_entry_point_reports_only_malformed_image_error(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "malformed.jpg"
    output = tmp_path / "output.pdf"
    malformed.write_bytes(b"not an image")
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "docuforge",
            "image",
            "to-pdf",
            str(malformed),
            "--output",
            str(output),
        ],
        cwd=project_root,
        env=module_environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Error: Unable to convert the requested images to PDF.\n"
    assert not output.exists()


def test_installed_console_script_converts_images(tmp_path: Path) -> None:
    executable = shutil.which("docuforge")
    if executable is None:
        pytest.skip("the docuforge console script is not installed")
    input_path = tmp_path / "input.jpg"
    output = tmp_path / "output.pdf"
    write_image(input_path, (10, 20), "JPEG")

    result = subprocess.run(
        [
            executable,
            "image",
            "to-pdf",
            str(input_path),
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == f"Converted 1 image files into {output}\n"
    assert result.stderr == ""
    assert page_sizes(output) == [(10, 20)]

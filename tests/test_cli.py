import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from docuforge.__main__ import PLACEHOLDER_EXIT_CODE, main
from docuforge.cli.parser import package_version


@pytest.mark.parametrize(
    ("arguments", "expected_text"),
    [
        (["--help"], "usage: docuforge"),
        (["pdf", "--help"], "usage: docuforge pdf"),
        (["image", "--help"], "usage: docuforge image"),
        (["pdf", "merge", "--help"], "usage: docuforge pdf merge"),
        (["pdf", "split", "--help"], "usage: docuforge pdf split"),
        (["image", "to-pdf", "--help"], "usage: docuforge image to-pdf"),
    ],
)
def test_help_returns_zero(arguments, expected_text, capsys) -> None:
    assert main(arguments) == 0

    captured = capsys.readouterr()
    assert expected_text in captured.out
    assert captured.err == ""


def test_main_without_command_prints_root_help(capsys) -> None:
    assert main([]) == 0

    captured = capsys.readouterr()
    assert "usage: docuforge" in captured.out
    assert "{pdf,image}" in captured.out
    assert captured.err == ""


def test_version_returns_zero(capsys) -> None:
    assert main(["--version"]) == 0

    captured = capsys.readouterr()
    assert captured.out == f"docuforge {package_version()}\n"
    assert captured.err == ""


@pytest.mark.parametrize(
    "arguments",
    [
        ["unknown"],
        ["pdf", "unknown"],
    ],
)
def test_invalid_command_returns_two(arguments, capsys) -> None:
    assert main(arguments) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error: argument" in captured.err


@pytest.mark.parametrize(
    ("arguments", "command_path"),
    [
        (["pdf", "merge"], "pdf merge"),
        (["pdf", "split"], "pdf split"),
        (["image", "to-pdf"], "image to-pdf"),
    ],
)
def test_placeholder_command_returns_two_on_stderr(arguments, command_path, capsys) -> None:
    assert main(arguments) == PLACEHOLDER_EXIT_CODE

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"docuforge {command_path}: command execution will be added in a later commit\n"
    )


def test_python_module_entry_point_help() -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    source_path = str(project_root / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        path for path in (source_path, environment.get("PYTHONPATH")) if path
    )

    result = subprocess.run(
        [sys.executable, "-m", "docuforge", "--help"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage: docuforge" in result.stdout
    assert result.stderr == ""


def test_installed_console_script_help() -> None:
    executable = shutil.which("docuforge")
    if executable is None:
        pytest.skip("the docuforge console script is not installed")

    result = subprocess.run(
        [executable, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage: docuforge" in result.stdout
    assert result.stderr == ""

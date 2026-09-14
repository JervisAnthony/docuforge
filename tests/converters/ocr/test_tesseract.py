"""Tesseract adapter tests use an injected runner, never an installed OCR executable."""

import math
import os
import subprocess
from pathlib import Path

import pytest

from docuforge.converters.ocr import (
    OcrEngineExecutionError,
    OcrEngineRequest,
    OcrEngineTimeoutError,
    OcrEngineUnavailableError,
    OcrOutputError,
    TesseractEngine,
)
from docuforge.core import DocumentFormat, InvalidConversionRequestError


@pytest.fixture
def executable(tmp_path):
    path = tmp_path / "fake-tesseract"
    path.write_bytes(b"fake")
    return path


def engine(executable, runner, **kwargs):
    return TesseractEngine(executable=executable, process_runner=runner, **kwargs)


def request(tmp_path, suffix=".png", output_format=DocumentFormat.TXT, stem="page"):
    source = tmp_path / f"{stem}{suffix}"
    source.write_bytes(b"raster")
    output = tmp_path / "output"
    output.mkdir(exist_ok=True)
    return OcrEngineRequest(source, output, output_format)


def fake_runner(content):
    def run(args, **kwargs):
        base = Path(args[2])
        base.with_suffix(".pdf" if args[-1] == "pdf" else ".txt").write_bytes(content)
        return subprocess.CompletedProcess(args, 0, "", "")
    return run


def assert_clean(output):
    assert not list(output.glob(".docuforge-ocr-*"))


def test_discovery_and_construction(executable, tmp_path):
    calls = []
    def resolver(name):
        calls.append(name)
        return str(executable)
    def forbidden_runner(*args, **kwargs):
        raise AssertionError("construction ran a subprocess")
    resolved = TesseractEngine(executable_resolver=resolver, process_runner=forbidden_runner)
    assert calls == ["tesseract"]
    assert resolved.executable == str(executable)
    assert resolved.timeout_seconds == 60.0
    assert engine(executable, forbidden_runner).executable == str(executable)
    assert calls == ["tesseract"]
    with pytest.raises(OcrEngineUnavailableError, match="unavailable"):
        TesseractEngine(executable_resolver=lambda _: None)
    with pytest.raises(OcrEngineUnavailableError):
        TesseractEngine(executable=tmp_path / "missing")
    with pytest.raises(OcrEngineUnavailableError):
        TesseractEngine(executable=tmp_path)


@pytest.mark.parametrize("timeout", [1, 0.5, 60])
def test_positive_timeout(executable, timeout):
    assert engine(executable, lambda *_a, **_k: None, timeout_seconds=timeout).timeout_seconds == timeout


@pytest.mark.parametrize("timeout", [True, False, 0, -1, math.nan, math.inf, -math.inf, "60", None])
def test_invalid_timeout(executable, timeout):
    with pytest.raises(InvalidConversionRequestError):
        engine(executable, lambda *_a, **_k: None, timeout_seconds=timeout)


@pytest.mark.parametrize("suffix", [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".PNG"])
def test_supported_raster_suffixes(executable, tmp_path, suffix):
    item = request(tmp_path, suffix=suffix)
    assert engine(executable, fake_runner(b"hello")).recognize(item).output_path.read_bytes() == b"hello"


@pytest.mark.parametrize("suffix", [".pdf", ".docx", ".pptx", ".xlsx", ".gif", ".txt", ""])
def test_unsupported_sources_do_not_run(executable, tmp_path, suffix):
    item = request(tmp_path, suffix=suffix)
    with pytest.raises(InvalidConversionRequestError):
        engine(executable, lambda *_a, **_k: pytest.fail("process ran")).recognize(item)


def test_missing_and_non_file_paths_do_not_run(executable, tmp_path):
    item = request(tmp_path)
    runner = lambda *_a, **_k: pytest.fail("process ran")
    item.input_path.unlink()
    with pytest.raises(InvalidConversionRequestError):
        engine(executable, runner).recognize(item)
    item.input_path.mkdir()
    with pytest.raises(InvalidConversionRequestError):
        engine(executable, runner).recognize(item)
    item.input_path.rmdir()
    item.input_path.write_bytes(b"raster")
    item.output_directory.rmdir()
    with pytest.raises(InvalidConversionRequestError):
        engine(executable, runner).recognize(item)
    item.output_directory.write_bytes(b"file")
    with pytest.raises(InvalidConversionRequestError):
        engine(executable, runner).recognize(item)


@pytest.mark.parametrize("format_value,content", [(DocumentFormat.TXT, "Zażółć ☃\n".encode()), (DocumentFormat.PDF, b"%PDF-1.7\nbody")])
def test_success_invocation_publication_and_cleanup(executable, tmp_path, format_value, content):
    item = request(tmp_path, ".PNG", format_value, "a space ☃")
    destination = item.output_directory / f"{item.input_path.stem}.{format_value.value}"
    destination.write_bytes(b"OLD")
    calls = []
    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return fake_runner(content)(args, **kwargs)
    result = engine(executable, runner, timeout_seconds=3).recognize(item)
    assert result.input_path == item.input_path
    assert result.output_format is format_value
    assert result.language == "eng"
    assert result.output_path == destination
    assert destination.read_bytes() == content
    args, kwargs = calls[0]
    assert isinstance(args, list)
    assert args[:2] == [str(executable), str(item.input_path)]
    assert args[3:5] == ["-l", "eng"]
    assert Path(args[2]).parent.name.startswith(".docuforge-ocr-")
    assert Path(args[2]).parent.parent == item.output_directory
    assert args[5:] == (["pdf"] if format_value is DocumentFormat.PDF else [])
    assert kwargs == {"shell": False, "check": False, "capture_output": True, "text": True, "timeout": 3.0}
    assert_clean(item.output_directory)


def test_empty_text_is_valid(executable, tmp_path):
    item = request(tmp_path)
    assert engine(executable, fake_runner(b"")).recognize(item).output_path.read_bytes() == b""
    assert_clean(item.output_directory)


@pytest.mark.parametrize("failure,expected", [
    ("timeout", OcrEngineTimeoutError),
    ("start", OcrEngineExecutionError),
    ("exit", OcrEngineExecutionError),
    ("missing", OcrOutputError),
    ("invalid_text", OcrOutputError),
    ("invalid_pdf", OcrOutputError),
    ("empty_pdf", OcrOutputError),
    ("directory", OcrOutputError),
])
def test_failure_preserves_existing_destination(executable, tmp_path, failure, expected):
    target = DocumentFormat.PDF if failure in {"invalid_pdf", "empty_pdf"} else DocumentFormat.TXT
    item = request(tmp_path, output_format=target)
    destination = item.output_directory / f"page.{target.value}"
    destination.write_bytes(b"OLD")
    def runner(args, **kwargs):
        path = Path(args[2]).with_suffix(f".{target.value}")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 3, stderr="secret")
        if failure == "start":
            raise OSError("secret path")
        if failure == "exit":
            return subprocess.CompletedProcess(args, 1, "secret stdout", "secret stderr")
        if failure == "invalid_text":
            path.write_bytes(b"\xff")
        elif failure == "invalid_pdf":
            path.write_bytes(b"not a PDF")
        elif failure == "empty_pdf":
            path.write_bytes(b"")
        elif failure == "directory":
            path.mkdir()
        return subprocess.CompletedProcess(args, 0, "", "")
    with pytest.raises(expected) as error:
        engine(executable, runner).recognize(item)
    assert "secret" not in str(error.value)
    assert destination.read_bytes() == b"OLD"
    assert_clean(item.output_directory)


@pytest.mark.parametrize("inside", [True, False])
def test_staged_symlink_rejected_inside_and_outside_workspace(executable, tmp_path, inside):
    item = request(tmp_path)
    destination = item.output_directory / "page.txt"
    destination.write_bytes(b"OLD")
    def runner(args, **kwargs):
        base = Path(args[2])
        target = base.parent / "target.txt" if inside else tmp_path / "outside.txt"
        target.write_bytes(b"text")
        try:
            base.with_suffix(".txt").symlink_to(target)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f"symlinks unavailable: {error}")
        return subprocess.CompletedProcess(args, 0)
    with pytest.raises(OcrOutputError):
        engine(executable, runner).recognize(item)
    assert destination.read_bytes() == b"OLD"
    assert_clean(item.output_directory)


def test_publication_failure_preserves_output(executable, tmp_path, monkeypatch):
    item = request(tmp_path)
    destination = item.output_directory / "page.txt"
    destination.write_bytes(b"OLD")
    def fail_replace(*args):
        raise OSError("secret path")
    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OcrOutputError, match="Unable to publish") as error:
        engine(executable, fake_runner(b"NEW")).recognize(item)
    assert "secret" not in str(error.value)
    assert destination.read_bytes() == b"OLD"
    assert_clean(item.output_directory)


def test_wrong_request_type(executable):
    with pytest.raises(TypeError):
        engine(executable, fake_runner(b"text")).recognize(object())


@pytest.mark.parametrize("output_format,content", [(DocumentFormat.TXT, b"text"), (DocumentFormat.PDF, b"%PDF-1.7")])
def test_explicit_dpi_is_separate_argument_and_result_metadata(
    executable, tmp_path, output_format, content
):
    item = request(tmp_path, output_format=output_format)
    item = OcrEngineRequest(item.input_path, item.output_directory, output_format, "eng", 300)
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        return fake_runner(content)(args, **kwargs)

    result = engine(executable, runner).recognize(item)
    assert calls[0][5:7] == ["--dpi", "300"]
    assert calls[0][7:] == (["pdf"] if output_format is DocumentFormat.PDF else [])
    assert result.dpi == 300

"""Image OCR workflow tests exercise only fake OcrEngine implementations."""

import os

import pytest
from PIL import Image

from docuforge.converters.ocr import (
    ImageToTextConverter,
    ImageToTextRequest,
    OcrEngineExecutionError,
    OcrEngineResult,
    OcrEngineTimeoutError,
    OcrEngineUnavailableError,
    OcrOutputError,
    extract_text_from_image,
)
from docuforge.core import DocumentFormat, InvalidConversionRequestError


class FakeEngine:
    def __init__(self, content=b"Hello", result_factory=None):
        self.content = content
        self.result_factory = result_factory
        self.requests = []

    def recognize(self, request):
        self.requests.append(request)
        artifact = request.output_directory / "result.txt"
        artifact.write_bytes(self.content)
        if self.result_factory is not None:
            return self.result_factory(request, artifact)
        return OcrEngineResult(request.input_path, artifact, DocumentFormat.TXT, request.language)


def source(tmp_path, suffix=".png", pillow_format="PNG", stem="scan"):
    path = tmp_path / f"{stem}{suffix}"
    with Image.new("RGB", (8, 8), "white") as image:
        image.save(path, format=pillow_format)
    return path


def assert_clean(directory):
    assert not list(directory.glob(".docuforge-image-ocr-*"))


@pytest.mark.parametrize(
    "suffix,pillow_format,expected",
    [
        (".jpg", "JPEG", DocumentFormat.JPG),
        (".JPEG", "JPEG", DocumentFormat.JPG),
        (".png", "PNG", DocumentFormat.PNG),
        (".PNG", "PNG", DocumentFormat.PNG),
        (".webp", "WEBP", DocumentFormat.WEBP),
        (".WEBP", "WEBP", DocumentFormat.WEBP),
        (".bmp", "BMP", DocumentFormat.BMP),
        (".BMP", "BMP", DocumentFormat.BMP),
        (".tif", "TIFF", DocumentFormat.TIFF),
        (".TIFF", "TIFF", DocumentFormat.TIFF),
    ],
)
def test_supported_single_frame_formats(tmp_path, suffix, pillow_format, expected):
    image = source(tmp_path, suffix, pillow_format, "scan with space ☃")
    destination = tmp_path / "custom output ☃.TXT"
    fake = FakeEngine("  Grüß Gott\r\n\t\n".encode())
    item = ImageToTextRequest(image, destination, "eng+deu")
    original_bytes = image.read_bytes()
    result = extract_text_from_image(item, engine=fake)
    assert len(fake.requests) == 1
    engine_request = fake.requests[0]
    assert engine_request.input_path == image
    assert engine_request.output_format is DocumentFormat.TXT
    assert engine_request.language == "eng+deu"
    assert engine_request.output_directory.parent == destination.parent
    assert engine_request.output_directory.name.startswith(".docuforge-image-ocr-")
    assert engine_request.output_directory != destination.parent
    assert result.input_path == image
    assert result.output_path == destination
    assert result.source_format is expected
    assert result.language == "eng+deu"
    assert result.text == "  Grüß Gott\r\n\t\n"
    assert image.read_bytes() == original_bytes
    assert destination.read_bytes() == fake.content
    assert_clean(tmp_path)


@pytest.mark.parametrize("text", ["ASCII", "  leading", "trailing  ", "a\n\nb\n", "a\r\nb", "\t☃ é\u000c", ""])
def test_exact_text_and_existing_output_replacement(tmp_path, text):
    image = source(tmp_path)
    destination = tmp_path / "chosen.txt"
    destination.write_text("OLD")
    fake = FakeEngine(text.encode("utf-8"))
    result = ImageToTextConverter(fake).convert(ImageToTextRequest(image, destination))
    assert result.text == text
    assert destination.read_bytes() == text.encode("utf-8")
    assert_clean(tmp_path)


@pytest.mark.parametrize("suffix", [".gif", ".pdf", ".docx", ".pptx", ".xlsx", ".txt", ""])
def test_unsupported_suffix_rejected_before_engine(tmp_path, suffix):
    image = source(tmp_path, suffix, "PNG")
    fake = FakeEngine()
    with pytest.raises(InvalidConversionRequestError):
        ImageToTextConverter(fake).convert(ImageToTextRequest(image, tmp_path / "out.txt"))
    assert fake.requests == []


@pytest.mark.parametrize(
    "suffix,pillow_format,content",
    [
        (".png", None, b"not an image"),
        (".jpg", None, b"arbitrary binary"),
        (".jpg", "PNG", None),
        (".png", "JPEG", None),
        (".jpg", None, b"\xff\xd8truncated"),
        (".png", None, b"\x89PNG\r\n\x1a\ntruncated"),
    ],
)
def test_invalid_or_mismatched_image_rejected_before_engine(
    tmp_path, suffix, pillow_format, content
):
    image = source(tmp_path, suffix, pillow_format) if pillow_format else tmp_path / f"scan{suffix}"
    if content is not None:
        image.write_bytes(content)
    fake = FakeEngine()
    with pytest.raises(InvalidConversionRequestError, match="valid supported raster"):
        ImageToTextConverter(fake).convert(ImageToTextRequest(image, tmp_path / "out.txt"))
    assert fake.requests == []


def test_multiframe_tiff_rejected_before_engine(tmp_path):
    image = tmp_path / "pages.tiff"
    with Image.new("RGB", (8, 8), "white") as first, Image.new("RGB", (8, 8), "black") as second:
        first.save(image, format="TIFF", save_all=True, append_images=[second])
    fake = FakeEngine()
    with pytest.raises(InvalidConversionRequestError):
        ImageToTextConverter(fake).convert(ImageToTextRequest(image, tmp_path / "out.txt"))
    assert fake.requests == []


@pytest.mark.parametrize(
    "failure",
    [
        OSError("private image path"),
        ValueError("private image detail"),
        Image.DecompressionBombError("private image dimensions"),
        Image.DecompressionBombWarning("private image dimensions"),
    ],
)
def test_pillow_failures_are_safe_and_precede_engine(tmp_path, monkeypatch, failure):
    image = source(tmp_path)
    fake = FakeEngine()

    def fail_open(*args, **kwargs):
        raise failure

    monkeypatch.setattr(Image, "open", fail_open)
    with pytest.raises(InvalidConversionRequestError) as error:
        ImageToTextConverter(fake).convert(ImageToTextRequest(image, tmp_path / "out.txt"))
    assert "private" not in str(error.value)
    assert fake.requests == []


def test_missing_and_directory_source_rejected_before_engine(tmp_path):
    fake = FakeEngine()
    item = ImageToTextRequest(tmp_path / "missing.png", tmp_path / "out.txt")
    with pytest.raises(InvalidConversionRequestError):
        ImageToTextConverter(fake).convert(item)
    item.input_path.mkdir()
    with pytest.raises(InvalidConversionRequestError):
        ImageToTextConverter(fake).convert(item)
    assert fake.requests == []


@pytest.mark.parametrize("suffix", [".pdf", ".png", ""])
def test_output_suffix_rejected_before_engine(tmp_path, suffix):
    image = source(tmp_path)
    fake = FakeEngine()
    with pytest.raises(InvalidConversionRequestError):
        ImageToTextConverter(fake).convert(ImageToTextRequest(image, tmp_path / f"out{suffix}"))
    assert fake.requests == []


def test_invalid_output_paths_rejected_before_engine(tmp_path):
    image = source(tmp_path)
    fake = FakeEngine()
    missing = tmp_path / "missing" / "out.txt"
    with pytest.raises(InvalidConversionRequestError):
        ImageToTextConverter(fake).convert(ImageToTextRequest(image, missing))
    parent_file = tmp_path / "parent"
    parent_file.write_bytes(b"x")
    with pytest.raises(InvalidConversionRequestError):
        ImageToTextConverter(fake).convert(ImageToTextRequest(image, parent_file / "out.txt"))
    directory = tmp_path / "out.txt"
    directory.mkdir()
    with pytest.raises(InvalidConversionRequestError):
        ImageToTextConverter(fake).convert(ImageToTextRequest(image, directory))
    hardlink = tmp_path / "same.txt"
    try:
        os.link(image, hardlink)
    except OSError as error:
        pytest.skip(f"hard links unavailable: {error}")
    with pytest.raises(InvalidConversionRequestError):
        ImageToTextConverter(fake).convert(ImageToTextRequest(image, hardlink))
    assert fake.requests == []


@pytest.mark.parametrize(
    "scenario",
    ["wrong_type", "wrong_source", "wrong_format", "wrong_language", "missing", "directory", "outside", "wrong_suffix", "invalid_utf8", "symlink_inside", "symlink_outside"],
)
def test_untrusted_engine_result_preserves_destination(tmp_path, scenario):
    image = source(tmp_path)
    destination = tmp_path / "chosen.txt"
    destination.write_bytes(b"OLD")

    def result_factory(engine_request, artifact):
        if scenario == "wrong_type":
            return object()
        if scenario == "wrong_source":
            return OcrEngineResult(tmp_path / "other.png", artifact, "txt", "eng")
        if scenario == "wrong_format":
            return OcrEngineResult(image, artifact, "pdf", "eng")
        if scenario == "wrong_language":
            return OcrEngineResult(image, artifact, "txt", "deu")
        if scenario == "missing":
            artifact.unlink()
        if scenario == "directory":
            artifact.unlink()
            artifact.mkdir()
        if scenario == "outside":
            artifact = tmp_path / "outside.txt"
            artifact.write_bytes(b"outside")
        if scenario == "wrong_suffix":
            artifact = artifact.rename(artifact.with_suffix(".bin"))
        if scenario == "invalid_utf8":
            artifact.write_bytes(b"\xff")
        if scenario.startswith("symlink_"):
            artifact.unlink()
            target = artifact.parent / "inside.txt" if scenario == "symlink_inside" else tmp_path / "outside.txt"
            target.write_bytes(b"text")
            try:
                artifact.symlink_to(target)
            except (OSError, NotImplementedError) as error:
                pytest.skip(f"symlinks unavailable: {error}")
        return OcrEngineResult(engine_request.input_path, artifact, "txt", "eng")

    fake = FakeEngine(result_factory=result_factory)
    with pytest.raises(OcrOutputError):
        ImageToTextConverter(fake).convert(ImageToTextRequest(image, destination))
    assert len(fake.requests) == 1
    assert destination.read_bytes() == b"OLD"
    assert_clean(tmp_path)


@pytest.mark.parametrize("error_type", [OcrEngineUnavailableError, OcrEngineTimeoutError, OcrEngineExecutionError, OcrOutputError])
def test_structured_engine_errors_propagate_and_clean_workspace(tmp_path, error_type):
    image = source(tmp_path)
    destination = tmp_path / "chosen.txt"
    destination.write_bytes(b"OLD")
    class FailingEngine:
        def recognize(self, request):
            assert request.output_directory.parent == tmp_path
            raise error_type("safe error")
    with pytest.raises(error_type, match="safe error"):
        ImageToTextConverter(FailingEngine()).convert(ImageToTextRequest(image, destination))
    assert destination.read_bytes() == b"OLD"
    assert_clean(tmp_path)


def test_publication_failure_preserves_destination(tmp_path, monkeypatch):
    image = source(tmp_path)
    destination = tmp_path / "chosen.txt"
    destination.write_bytes(b"OLD")
    def fail_replace(*args):
        raise OSError("secret filesystem path")
    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OcrOutputError, match="Unable to publish") as error:
        ImageToTextConverter(FakeEngine()).convert(ImageToTextRequest(image, destination))
    assert "secret" not in str(error.value)
    assert destination.read_bytes() == b"OLD"
    assert_clean(tmp_path)


def test_wrong_request_type():
    with pytest.raises(TypeError):
        ImageToTextConverter(FakeEngine()).convert(object())

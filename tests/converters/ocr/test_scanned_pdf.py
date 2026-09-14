"""Scanned-PDF workflows use the real bounded renderer and fake OCR engines."""

import os
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from docuforge.converters.ocr import (
    OcrEngineExecutionError,
    OcrEngineResult,
    OcrEngineTimeoutError,
    OcrEngineUnavailableError,
    OcrOutputError,
    ScannedPdfToSearchablePdfConverter,
    ScannedPdfToSearchablePdfRequest,
    ScannedPdfToTextConverter,
    ScannedPdfToTextRequest,
    extract_text_from_scanned_pdf,
    make_scanned_pdf_searchable,
)
from docuforge.converters.pdf import pdf_to_images_path
from docuforge.converters.pdf.exceptions import PdfProcessingError
from docuforge.core import DocumentFormat, InvalidConversionRequestError


def pdf(tmp_path, sizes=((72, 96), (40, 50)), name="scan.pdf"):
    path = tmp_path / name
    writer = PdfWriter()
    for width, height in sizes:
        writer.add_blank_page(width=width, height=height)
    with path.open("wb") as stream:
        writer.write(stream)
    return path


def page_pdf(path, raster, dpi, *, page_count=1, width_factor=1, encrypted=False):
    with Image.open(raster) as image:
        width, height = image.size
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=width * 72 / dpi * width_factor, height=height * 72 / dpi)
    if encrypted:
        writer.encrypt("password")
    with path.open("wb") as stream:
        writer.write(stream)


class FakeEngine:
    def __init__(self, text_pages=("First\n", "Second\n"), scenario=None):
        self.text_pages = text_pages
        self.scenario = scenario
        self.requests = []

    def recognize(self, request):
        self.requests.append(request)
        index = len(self.requests) - 1
        artifact = request.output_directory / f"result.{request.output_format.value}"
        if request.output_format is DocumentFormat.TXT:
            artifact.write_bytes(self.text_pages[index].encode("utf-8"))
        else:
            page_pdf(artifact, request.input_path, request.dpi)
        if self.scenario is not None:
            return self.scenario(request, artifact, index)
        return OcrEngineResult(
            request.input_path, artifact, request.output_format, request.language, request.dpi
        )


def assert_clean(directory):
    assert not list(directory.glob(".docuforge-pdf-ocr-*"))


@pytest.mark.parametrize(
    "page_texts,expected",
    [
        (("Hello\n",), "Hello\n"),
        (("First\r\n", "\tSecond ☃\n"), "First\r\n\f\tSecond ☃\n"),
        (("", "Second"), "\fSecond"),
        (("", ""), "\f"),
        (("",), ""),
    ],
)
def test_text_aggregation_order_and_exact_publication(tmp_path, page_texts, expected):
    source = pdf(tmp_path, sizes=((72, 96),) * len(page_texts), name="scan ☃.PDF")
    destination = tmp_path / "chosen text ☃.TXT"
    destination.write_bytes(b"OLD")
    fake = FakeEngine(text_pages=page_texts)
    item = ScannedPdfToTextRequest(source, destination, "eng+deu", dpi=72)
    result = extract_text_from_scanned_pdf(item, engine=fake)
    assert result.input_path == source
    assert result.output_path == destination
    assert result.page_count == len(page_texts)
    assert result.page_texts == page_texts
    assert result.text == expected
    assert result.language == "eng+deu"
    assert result.dpi == 72
    assert destination.read_bytes() == expected.encode("utf-8")
    assert len(fake.requests) == len(page_texts)
    for index, call in enumerate(fake.requests, start=1):
        assert call.input_path.name == f"page-{index:04d}.png"
        assert call.output_format is DocumentFormat.TXT
        assert call.language == "eng+deu"
        assert call.dpi == 72
        assert call.output_directory.name == f"ocr-page-{index:04d}"
        assert call.output_directory.parent.name.startswith(".docuforge-pdf-ocr-")
    assert_clean(tmp_path)


@pytest.mark.parametrize("sizes", [((72, 96),), ((72, 96), (40, 50)), ((31, 47), (40, 50), (52, 68))])
def test_searchable_pdf_assembly_order_and_geometry(tmp_path, sizes):
    source = pdf(tmp_path, sizes=sizes)
    destination = tmp_path / "searchable ☃.PDF"
    destination.write_bytes(b"OLD")
    fake = FakeEngine()
    result = make_scanned_pdf_searchable(
        ScannedPdfToSearchablePdfRequest(source, destination, dpi=144), engine=fake
    )
    assert result.input_path == source
    assert result.output_path == destination
    assert result.page_count == len(sizes)
    assert result.dpi == 144
    assert destination.read_bytes().startswith(b"%PDF-")
    reader = PdfReader(destination)
    assert len(reader.pages) == len(sizes)
    for index, ((width, height), page) in enumerate(zip(sizes, reader.pages, strict=True), start=1):
        assert abs(float(page.mediabox.width) - width) <= 1
        assert abs(float(page.mediabox.height) - height) <= 1
        call = fake.requests[index - 1]
        assert call.input_path.name == f"page-{index:04d}.png"
        assert call.output_format is DocumentFormat.PDF
        assert call.dpi == 144
    assert len(fake.requests) == len(sizes)
    assert_clean(tmp_path)


@pytest.mark.parametrize("suffix", [".txt", ".png", ""])
def test_wrong_source_suffix_rejected_before_engine(tmp_path, suffix):
    source = pdf(tmp_path, name=f"source{suffix}")
    fake = FakeEngine()
    with pytest.raises(InvalidConversionRequestError):
        ScannedPdfToTextConverter(fake).convert(ScannedPdfToTextRequest(source, tmp_path / "out.txt"))
    assert fake.requests == []


@pytest.mark.parametrize("kind", ["missing", "directory", "corrupt", "renamed_text", "zero", "encrypted"])
def test_unrenderable_source_never_reaches_engine(tmp_path, kind):
    source = tmp_path / "source.pdf"
    if kind == "directory":
        source.mkdir()
    elif kind == "corrupt":
        source.write_bytes(b"%PDF-truncated")
    elif kind == "renamed_text":
        source.write_text("not a PDF")
    elif kind == "zero":
        pdf(tmp_path, sizes=(), name="source.pdf")
    elif kind == "encrypted":
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=96)
        writer.encrypt("secret")
        with source.open("wb") as stream:
            writer.write(stream)
    fake = FakeEngine()
    with pytest.raises((InvalidConversionRequestError, OcrOutputError)):
        ScannedPdfToTextConverter(fake).convert(ScannedPdfToTextRequest(source, tmp_path / "out.txt", dpi=72))
    assert fake.requests == []
    assert_clean(tmp_path)


@pytest.mark.parametrize("converter,request_type,suffix", [
    (ScannedPdfToTextConverter, ScannedPdfToTextRequest, ".txt"),
    (ScannedPdfToSearchablePdfConverter, ScannedPdfToSearchablePdfRequest, ".pdf"),
])
def test_request_paths_and_same_file_rejected_before_engine(tmp_path, converter, request_type, suffix):
    source = pdf(tmp_path)
    fake = FakeEngine()
    invalid = [tmp_path / f"out{suffix}" / f"inner{suffix}", tmp_path / "wrong.png"]
    directory = tmp_path / f"directory{suffix}"
    directory.mkdir()
    invalid.append(directory)
    parent_file = tmp_path / "parent"
    parent_file.write_bytes(b"x")
    invalid.append(parent_file / f"out{suffix}")
    if suffix == ".pdf":
        invalid.append(source)
        hardlink = tmp_path / "same.pdf"
        os.link(source, hardlink)
        invalid.append(hardlink)
    for output in invalid:
        with pytest.raises(InvalidConversionRequestError):
            converter(fake).convert(request_type(source, output, dpi=72))
    assert fake.requests == []


@pytest.mark.parametrize("limit,field", [(1, "max_pages"), (100, "max_pixels_per_page")])
def test_renderer_bounds_precede_ocr(tmp_path, limit, field):
    source = pdf(tmp_path)
    destination = tmp_path / "out.txt"
    destination.write_bytes(b"OLD")
    fake = FakeEngine()
    with pytest.raises(InvalidConversionRequestError):
        ScannedPdfToTextConverter(fake).convert(
            ScannedPdfToTextRequest(source, destination, dpi=72, **{field: limit})
        )
    assert fake.requests == []
    assert destination.read_bytes() == b"OLD"
    assert_clean(tmp_path)


@pytest.mark.parametrize("failure", ["processing", "wrong_input", "wrong_directory", "wrong_format", "wrong_dpi", "reordered", "missing_page"])
def test_renderer_contract_failure_preserves_destination(tmp_path, monkeypatch, failure):
    source = pdf(tmp_path)
    destination = tmp_path / "out.txt"
    destination.write_bytes(b"OLD")
    fake = FakeEngine()

    def renderer(item):
        if failure == "processing":
            raise PdfProcessingError("private renderer detail")
        result = pdf_to_images_path(item)
        if failure == "wrong_input":
            return replace(result, input_path=tmp_path / "other.pdf")
        if failure == "wrong_directory":
            return replace(result, output_directory=tmp_path)
        if failure == "wrong_format":
            return replace(result, output_format=DocumentFormat.JPG)
        if failure == "wrong_dpi":
            return replace(result, dpi=150)
        if failure == "reordered":
            return replace(result, output_paths=tuple(reversed(result.output_paths)))
        result.output_paths[0].unlink()
        return result

    monkeypatch.setattr("docuforge.converters.ocr.scanned_pdf.pdf_to_images_path", renderer)
    with pytest.raises(OcrOutputError) as error:
        ScannedPdfToTextConverter(fake).convert(
            ScannedPdfToTextRequest(source, destination, dpi=72, max_pages=5, max_pixels_per_page=100_000)
        )
    assert "private" not in str(error.value)
    assert fake.requests == []
    assert destination.read_bytes() == b"OLD"
    assert_clean(tmp_path)


def test_searchable_pdf_assembly_failure_preserves_destination(tmp_path, monkeypatch):
    source = pdf(tmp_path, sizes=((72, 96),))
    destination = tmp_path / "out.pdf"
    destination.write_bytes(b"OLD")
    prebuilt = tmp_path / "prebuilt.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=96)
    with prebuilt.open("wb") as stream:
        writer.write(stream)

    class PrebuiltEngine:
        def recognize(self, request):
            artifact = request.output_directory / "page.pdf"
            artifact.write_bytes(prebuilt.read_bytes())
            return OcrEngineResult(request.input_path, artifact, "pdf", request.language, request.dpi)

    def fail_write(*args, **kwargs):
        raise OSError("private PDF path")

    monkeypatch.setattr(PdfWriter, "write", fail_write)
    with pytest.raises(OcrOutputError) as error:
        ScannedPdfToSearchablePdfConverter(PrebuiltEngine()).convert(
            ScannedPdfToSearchablePdfRequest(source, destination, dpi=72)
        )
    assert "private" not in str(error.value)
    assert destination.read_bytes() == b"OLD"
    assert_clean(tmp_path)


@pytest.mark.parametrize("target", [DocumentFormat.TXT, DocumentFormat.PDF])
@pytest.mark.parametrize("failure", ["wrong_type", "wrong_input", "wrong_format", "wrong_language", "wrong_dpi", "missing", "directory", "wrong_suffix", "outside", "symlink_inside", "symlink_outside", "invalid_content"])
def test_bad_engine_result_preserves_destination(tmp_path, target, failure):
    source = pdf(tmp_path, sizes=((72, 96),))
    destination = tmp_path / ("out.txt" if target is DocumentFormat.TXT else "out.pdf")
    destination.write_bytes(b"OLD")

    def scenario(request, artifact, index):
        if failure == "wrong_type":
            return object()
        if failure == "wrong_input":
            return OcrEngineResult(source, artifact, target, "eng", request.dpi)
        if failure == "wrong_format":
            wrong = DocumentFormat.PDF if target is DocumentFormat.TXT else DocumentFormat.TXT
            return OcrEngineResult(request.input_path, artifact, wrong, "eng", request.dpi)
        if failure == "wrong_language":
            return OcrEngineResult(request.input_path, artifact, target, "deu", request.dpi)
        if failure == "wrong_dpi":
            return OcrEngineResult(request.input_path, artifact, target, "eng", 150)
        if failure == "missing":
            artifact.unlink()
        if failure == "directory":
            artifact.unlink()
            artifact.mkdir()
        if failure == "wrong_suffix":
            artifact = artifact.rename(artifact.with_suffix(".bin"))
        if failure == "outside":
            artifact = tmp_path / artifact.name
            artifact.write_bytes(b"outside")
        if failure.startswith("symlink_"):
            artifact.unlink()
            linked = artifact.parent / "inside.txt" if failure == "symlink_inside" else tmp_path / "outside.txt"
            linked.write_bytes(b"text")
            try:
                artifact.symlink_to(linked)
            except (OSError, NotImplementedError) as error:
                pytest.skip(f"symlink unavailable: {error}")
        if failure == "invalid_content":
            artifact.write_bytes(b"\xff" if target is DocumentFormat.TXT else b"bad PDF")
        return OcrEngineResult(request.input_path, artifact, target, "eng", request.dpi)

    fake = FakeEngine(text_pages=("x",), scenario=scenario)
    item = (ScannedPdfToTextRequest if target is DocumentFormat.TXT else ScannedPdfToSearchablePdfRequest)(
        source, destination, dpi=72
    )
    converter = ScannedPdfToTextConverter if target is DocumentFormat.TXT else ScannedPdfToSearchablePdfConverter
    with pytest.raises(OcrOutputError):
        converter(fake).convert(item)
    assert len(fake.requests) == 1
    assert destination.read_bytes() == b"OLD"
    assert_clean(tmp_path)


@pytest.mark.parametrize("failure", ["zero", "multiple", "encrypted", "bad_geometry", "empty", "malformed"])
def test_invalid_searchable_page_pdf_rejected(tmp_path, failure):
    source = pdf(tmp_path, sizes=((72, 96),))
    destination = tmp_path / "out.pdf"
    destination.write_bytes(b"OLD")

    def scenario(request, artifact, index):
        if failure == "zero":
            page_pdf(artifact, request.input_path, request.dpi, page_count=0)
        elif failure == "multiple":
            page_pdf(artifact, request.input_path, request.dpi, page_count=2)
        elif failure == "encrypted":
            page_pdf(artifact, request.input_path, request.dpi, encrypted=True)
        elif failure == "bad_geometry":
            page_pdf(artifact, request.input_path, request.dpi, width_factor=2)
        elif failure == "empty":
            artifact.write_bytes(b"")
        else:
            artifact.write_bytes(b"%PDF-corrupt")
        return OcrEngineResult(request.input_path, artifact, "pdf", request.language, request.dpi)

    fake = FakeEngine(scenario=scenario)
    with pytest.raises(OcrOutputError):
        ScannedPdfToSearchablePdfConverter(fake).convert(
            ScannedPdfToSearchablePdfRequest(source, destination, dpi=72)
        )
    assert destination.read_bytes() == b"OLD"
    assert_clean(tmp_path)


@pytest.mark.parametrize("error_type", [OcrEngineUnavailableError, OcrEngineTimeoutError, OcrEngineExecutionError, OcrOutputError])
@pytest.mark.parametrize("target", [DocumentFormat.TXT, DocumentFormat.PDF])
def test_engine_failure_stops_later_pages_and_preserves_output(tmp_path, target, error_type):
    source = pdf(tmp_path)
    destination = tmp_path / ("out.txt" if target is DocumentFormat.TXT else "out.pdf")
    destination.write_bytes(b"OLD")
    class FailingEngine:
        calls = 0
        def recognize(self, request):
            self.calls += 1
            raise error_type("safe failure")
    fake = FailingEngine()
    item = (ScannedPdfToTextRequest if target is DocumentFormat.TXT else ScannedPdfToSearchablePdfRequest)(source, destination, dpi=72)
    converter = ScannedPdfToTextConverter if target is DocumentFormat.TXT else ScannedPdfToSearchablePdfConverter
    with pytest.raises(error_type, match="safe failure"):
        converter(fake).convert(item)
    assert fake.calls == 1
    assert destination.read_bytes() == b"OLD"
    assert_clean(tmp_path)


@pytest.mark.parametrize("target", [DocumentFormat.TXT, DocumentFormat.PDF])
def test_publication_failure_preserves_output(tmp_path, target, monkeypatch):
    source = pdf(tmp_path, sizes=((72, 96),))
    destination = tmp_path / ("out.txt" if target is DocumentFormat.TXT else "out.pdf")
    destination.write_bytes(b"OLD")
    def fail_replace(src, dst):
        if Path(dst) == destination:
            raise OSError("private path")
        return original_replace(src, dst)
    original_replace = os.replace
    monkeypatch.setattr(os, "replace", fail_replace)
    item = (ScannedPdfToTextRequest if target is DocumentFormat.TXT else ScannedPdfToSearchablePdfRequest)(source, destination, dpi=72)
    converter = ScannedPdfToTextConverter if target is DocumentFormat.TXT else ScannedPdfToSearchablePdfConverter
    with pytest.raises(OcrOutputError) as error:
        converter(FakeEngine(text_pages=("x",))).convert(item)
    assert "private" not in str(error.value)
    assert destination.read_bytes() == b"OLD"
    assert_clean(tmp_path)

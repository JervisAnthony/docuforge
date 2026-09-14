"""Bounded scanned-PDF OCR workflows over the renderer and OCR engine contracts."""

from __future__ import annotations

import math
import os
import stat
import tempfile
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter

from docuforge.converters.ocr.engine import OcrEngine
from docuforge.converters.ocr.exceptions import OcrOutputError
from docuforge.converters.ocr.models import (
    OcrEngineRequest,
    OcrEngineResult,
    ScannedPdfToSearchablePdfRequest,
    ScannedPdfToSearchablePdfResult,
    ScannedPdfToTextRequest,
    ScannedPdfToTextResult,
)
from docuforge.converters.pdf import (
    PdfToImagesPathRequest,
    PdfToImagesPathResult,
    pdf_to_images_path,
)
from docuforge.core import DocumentFormat, InvalidConversionRequestError

_Request = ScannedPdfToTextRequest | ScannedPdfToSearchablePdfRequest


class ScannedPdfToTextConverter:
    """OCR every source page and publish exact form-feed separated UTF-8 text."""

    def __init__(self, engine: OcrEngine) -> None:
        self._engine = engine

    def convert(self, request: ScannedPdfToTextRequest) -> ScannedPdfToTextResult:
        if not isinstance(request, ScannedPdfToTextRequest):
            raise TypeError("request must be a ScannedPdfToTextRequest")
        resolved_input = _validate_paths(request, ".txt")
        try:
            with tempfile.TemporaryDirectory(
                prefix=".docuforge-pdf-ocr-", dir=request.output_path.parent
            ) as workspace_name:
                workspace = Path(workspace_name)
                pages = _render_pages(request, workspace, resolved_input)
                page_texts = []
                for index, page in enumerate(pages, start=1):
                    artifact = _recognize_page(
                        self._engine, request, page, index, workspace, DocumentFormat.TXT
                    )
                    try:
                        page_texts.append(artifact.read_bytes().decode("utf-8"))
                    except (OSError, UnicodeError) as error:
                        raise OcrOutputError("The OCR engine produced invalid page text.") from error
                text = "\f".join(page_texts)
                staged = workspace / "combined.txt"
                _write_bytes(staged, text.encode("utf-8"))
                _validate_regular(staged, workspace)
                _publish(staged, request.output_path)
        except OcrOutputError:
            raise
        except OSError as error:
            raise OcrOutputError("Unable to create or clean up the PDF OCR workspace.") from error
        return ScannedPdfToTextResult(
            request.input_path, request.output_path, text, tuple(page_texts), len(pages),
            request.language, request.dpi,
        )


class ScannedPdfToSearchablePdfConverter:
    """OCR each rendered page to one searchable PDF and assemble in source order."""

    def __init__(self, engine: OcrEngine) -> None:
        self._engine = engine

    def convert(
        self, request: ScannedPdfToSearchablePdfRequest
    ) -> ScannedPdfToSearchablePdfResult:
        if not isinstance(request, ScannedPdfToSearchablePdfRequest):
            raise TypeError("request must be a ScannedPdfToSearchablePdfRequest")
        resolved_input = _validate_paths(request, ".pdf")
        try:
            with tempfile.TemporaryDirectory(
                prefix=".docuforge-pdf-ocr-", dir=request.output_path.parent
            ) as workspace_name:
                workspace = Path(workspace_name)
                pages = _render_pages(request, workspace, resolved_input)
                writer = PdfWriter()
                for index, page in enumerate(pages, start=1):
                    artifact = _recognize_page(
                        self._engine, request, page, index, workspace, DocumentFormat.PDF
                    )
                    _append_searchable_page(writer, artifact, page, request.dpi)
                staged = workspace / "combined-searchable.pdf"
                try:
                    with staged.open("wb") as stream:
                        writer.write(stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                except Exception as error:
                    raise OcrOutputError("Unable to assemble the searchable PDF.") from error
                _validate_regular(staged, workspace)
                _validate_combined_pdf(staged, len(pages))
                _publish(staged, request.output_path)
        except OcrOutputError:
            raise
        except OSError as error:
            raise OcrOutputError("Unable to create or clean up the PDF OCR workspace.") from error
        return ScannedPdfToSearchablePdfResult(
            request.input_path, request.output_path, len(pages), request.language, request.dpi
        )


def extract_text_from_scanned_pdf(
    request: ScannedPdfToTextRequest, *, engine: OcrEngine
) -> ScannedPdfToTextResult:
    """Delegate to the injected scanned-PDF text converter."""
    return ScannedPdfToTextConverter(engine).convert(request)


def make_scanned_pdf_searchable(
    request: ScannedPdfToSearchablePdfRequest, *, engine: OcrEngine
) -> ScannedPdfToSearchablePdfResult:
    """Delegate to the injected searchable-PDF converter."""
    return ScannedPdfToSearchablePdfConverter(engine).convert(request)


def _validate_paths(request: _Request, output_suffix: str) -> Path:
    if request.input_path.suffix.lower() != ".pdf":
        raise InvalidConversionRequestError("OCR source must use a .pdf extension.")
    if request.output_path.suffix.lower() != output_suffix:
        raise InvalidConversionRequestError("OCR output uses an invalid extension.")
    try:
        if not request.input_path.is_file():
            raise InvalidConversionRequestError("OCR source must be an existing PDF file.")
        if not request.output_path.parent.is_dir():
            raise InvalidConversionRequestError("OCR output parent must be an existing directory.")
        if request.output_path.is_dir():
            raise InvalidConversionRequestError("OCR output path must not be a directory.")
        source = request.input_path.resolve(strict=True)
        output = request.output_path.resolve(strict=False)
        same_file = request.output_path.exists() and os.path.samefile(
            request.input_path, request.output_path
        )
    except (OSError, ValueError) as error:
        raise InvalidConversionRequestError("Unable to validate PDF OCR paths.") from error
    if source == output or same_file:
        raise InvalidConversionRequestError("OCR source and output must be different files.")
    return source


def _render_pages(request: _Request, workspace: Path, resolved_input: Path) -> tuple[Path, ...]:
    directory = workspace / "rendered-pages"
    try:
        result = pdf_to_images_path(
            PdfToImagesPathRequest(
                request.input_path, directory, DocumentFormat.PNG, request.dpi,
                request.max_pages, request.max_pixels_per_page,
            )
        )
    except InvalidConversionRequestError:
        raise
    except Exception as error:
        raise OcrOutputError("Unable to render the PDF for OCR.") from error
    if not isinstance(result, PdfToImagesPathResult):
        raise OcrOutputError("The PDF renderer returned an invalid result.")
    if result.output_format is not DocumentFormat.PNG or result.dpi != request.dpi:
        raise OcrOutputError("The PDF renderer returned an inconsistent result.")
    if (result.page_count <= 0 or result.page_count > request.max_pages
            or len(result.output_paths) != result.page_count):
        raise OcrOutputError("The PDF renderer returned an invalid page count.")
    try:
        if result.input_path.resolve(strict=True) != resolved_input or (
            result.output_directory.resolve(strict=True) != directory.resolve(strict=True)
        ):
            raise OcrOutputError("The PDF renderer returned an inconsistent path.")
    except (OSError, ValueError) as error:
        raise OcrOutputError("Unable to validate rendered PDF paths.") from error
    for index, page in enumerate(result.output_paths, start=1):
        if page.name != f"page-{index:04d}.png":
            raise OcrOutputError("The PDF renderer returned pages out of order.")
        _validate_regular(page, directory)
    return result.output_paths


def _recognize_page(
    engine: OcrEngine, request: _Request, page: Path, index: int,
    workspace: Path, output_format: DocumentFormat,
) -> Path:
    page_workspace = workspace / f"ocr-page-{index:04d}"
    try:
        page_workspace.mkdir()
    except OSError as error:
        raise OcrOutputError("Unable to create the page OCR workspace.") from error
    result = engine.recognize(
        OcrEngineRequest(page, page_workspace, output_format, request.language, request.dpi)
    )
    if not isinstance(result, OcrEngineResult):
        raise OcrOutputError("The OCR engine returned an invalid page result.")
    if (result.output_format is not output_format or result.language != request.language
            or result.dpi != request.dpi):
        raise OcrOutputError("The OCR engine returned an inconsistent page result.")
    if result.output_path.suffix.lower() != f".{output_format.value}":
        raise OcrOutputError("The OCR engine returned an invalid page artifact.")
    try:
        if result.input_path.resolve(strict=True) != page.resolve(strict=True):
            raise OcrOutputError("The OCR engine returned an inconsistent page source.")
    except (OSError, ValueError) as error:
        raise OcrOutputError("Unable to validate the OCR page source.") from error
    _validate_regular(result.output_path, page_workspace)
    return result.output_path


def _validate_regular(path: Path, workspace: Path) -> None:
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise OcrOutputError("An OCR artifact is not a regular file.")
        path.resolve(strict=True).relative_to(workspace.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise OcrOutputError("An OCR artifact is missing or outside its workspace.") from error


def _write_bytes(path: Path, content: bytes) -> None:
    try:
        with path.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise OcrOutputError("Unable to assemble the OCR text output.") from error


def _append_searchable_page(writer: PdfWriter, artifact: Path, raster: Path, dpi: int) -> None:
    try:
        with artifact.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise OcrOutputError("The OCR engine produced an invalid page PDF.")
        reader = PdfReader(artifact)
        if reader.is_encrypted or len(reader.pages) != 1:
            raise OcrOutputError("The OCR engine produced an invalid page PDF.")
        page = reader.pages[0]
        with Image.open(raster) as image:
            if image.format != "PNG":
                raise OcrOutputError("The rendered OCR page is not a PNG.")
            width, height = image.size
        expected_width = width * 72 / dpi
        expected_height = height * 72 / dpi
        actual_width = float(page.mediabox.width)
        actual_height = float(page.mediabox.height)
        if (
            not all(map(math.isfinite, (actual_width, actual_height)))
            or width <= 0 or height <= 0
            or abs(actual_width - expected_width) > 1
            or abs(actual_height - expected_height) > 1
        ):
            raise OcrOutputError("The OCR page PDF has invalid geometry.")
        writer.add_page(page)
    except OcrOutputError:
        raise
    except Exception as error:
        raise OcrOutputError("Unable to validate the OCR page PDF.") from error


def _validate_combined_pdf(path: Path, expected_pages: int) -> None:
    try:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise OcrOutputError("The assembled searchable PDF is invalid.")
        reader = PdfReader(path)
        if reader.is_encrypted or len(reader.pages) != expected_pages:
            raise OcrOutputError("The assembled searchable PDF is invalid.")
    except OcrOutputError:
        raise
    except Exception as error:
        raise OcrOutputError("Unable to validate the searchable PDF.") from error


def _publish(source: Path, destination: Path) -> None:
    try:
        os.replace(source, destination)
    except OSError as error:
        raise OcrOutputError("Unable to publish the PDF OCR output.") from error

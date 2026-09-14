"""Validated single-image to UTF-8 text workflow over the OCR engine contract."""

from __future__ import annotations

import os
import stat
import tempfile
import warnings
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from docuforge.converters.ocr.engine import OcrEngine
from docuforge.converters.ocr.exceptions import OcrOutputError
from docuforge.converters.ocr.models import (
    ImageToTextRequest,
    ImageToTextResult,
    OcrEngineRequest,
    OcrEngineResult,
)
from docuforge.core import DocumentFormat, InvalidConversionRequestError

_FORMAT_BY_SUFFIX = {
    ".jpg": DocumentFormat.JPG,
    ".jpeg": DocumentFormat.JPG,
    ".png": DocumentFormat.PNG,
    ".webp": DocumentFormat.WEBP,
    ".bmp": DocumentFormat.BMP,
    ".tif": DocumentFormat.TIFF,
    ".tiff": DocumentFormat.TIFF,
}
_FORMAT_BY_PILLOW_NAME = {
    "JPEG": DocumentFormat.JPG,
    "PNG": DocumentFormat.PNG,
    "WEBP": DocumentFormat.WEBP,
    "BMP": DocumentFormat.BMP,
    "TIFF": DocumentFormat.TIFF,
}


class ImageToTextConverter:
    """Publish one exact text artifact from an injected OCR engine."""

    def __init__(self, engine: OcrEngine) -> None:
        self._engine = engine

    def convert(self, request: ImageToTextRequest) -> ImageToTextResult:
        """Validate the raster and engine result before publishing recognized text."""
        if not isinstance(request, ImageToTextRequest):
            raise TypeError("request must be an ImageToTextRequest")
        resolved_input = _validate_paths(request)
        source_format = _validate_image(request.input_path)

        try:
            with tempfile.TemporaryDirectory(
                prefix=".docuforge-image-ocr-", dir=request.output_path.parent
            ) as workspace_name:
                workspace = Path(workspace_name)
                engine_result = self._engine.recognize(
                    OcrEngineRequest(
                        input_path=request.input_path,
                        output_directory=workspace,
                        output_format=DocumentFormat.TXT,
                        language=request.language,
                    )
                )
                artifact, text = _validate_engine_result(
                    engine_result,
                    resolved_input=resolved_input,
                    language=request.language,
                    workspace=workspace,
                )
                try:
                    os.replace(artifact, request.output_path)
                except OSError as error:
                    raise OcrOutputError("Unable to publish the OCR text output.") from error
        except OcrOutputError:
            raise
        except OSError as error:
            raise OcrOutputError("Unable to create or clean up the OCR workflow workspace.") from error

        return ImageToTextResult(
            input_path=request.input_path,
            output_path=request.output_path,
            text=text,
            source_format=source_format,
            language=request.language,
        )


def extract_text_from_image(
    request: ImageToTextRequest, *, engine: OcrEngine
) -> ImageToTextResult:
    """Delegate an image-to-text request to the injected engine workflow."""
    return ImageToTextConverter(engine).convert(request)


def _validate_paths(request: ImageToTextRequest) -> Path:
    if request.input_path.suffix.lower() not in _FORMAT_BY_SUFFIX:
        raise InvalidConversionRequestError("OCR source must use a supported raster extension.")
    if request.output_path.suffix.lower() != ".txt":
        raise InvalidConversionRequestError("OCR output must use a .txt extension.")
    if not request.input_path.is_file():
        raise InvalidConversionRequestError("OCR source must be an existing file.")
    if not request.output_path.parent.is_dir():
        raise InvalidConversionRequestError("OCR output parent must be an existing directory.")
    if request.output_path.is_dir():
        raise InvalidConversionRequestError("OCR output path must not be a directory.")
    try:
        resolved_input = request.input_path.resolve(strict=True)
        resolved_output = request.output_path.resolve(strict=False)
        same_file = request.output_path.exists() and os.path.samefile(
            request.input_path, request.output_path
        )
    except (OSError, ValueError) as error:
        raise InvalidConversionRequestError("Unable to validate OCR source and output paths.") from error
    if same_file or resolved_input == resolved_output:
        raise InvalidConversionRequestError("OCR source and output must be different files.")
    return resolved_input


def _validate_image(input_path: Path) -> DocumentFormat:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(input_path) as image:
                source_format = _FORMAT_BY_PILLOW_NAME.get(image.format or "")
                if (
                    source_format is None
                    or source_format is not _FORMAT_BY_SUFFIX[input_path.suffix.lower()]
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise InvalidConversionRequestError(
                        "The OCR source is not a valid supported raster image."
                    )
                image.load()
                return source_format
    except InvalidConversionRequestError:
        raise
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise InvalidConversionRequestError(
            "The OCR source is not a valid supported raster image."
        ) from error


def _validate_engine_result(
    result: object, *, resolved_input: Path, language: str, workspace: Path
) -> tuple[Path, str]:
    if not isinstance(result, OcrEngineResult):
        raise OcrOutputError("The OCR engine returned an invalid result.")
    if result.output_format is not DocumentFormat.TXT or result.language != language:
        raise OcrOutputError("The OCR engine returned an inconsistent result.")
    if result.output_path.suffix.lower() != ".txt":
        raise OcrOutputError("The OCR engine returned an invalid text artifact.")
    try:
        if result.input_path.resolve(strict=True) != resolved_input:
            raise OcrOutputError("The OCR engine returned an inconsistent source.")
        if not stat.S_ISREG(result.output_path.lstat().st_mode):
            raise OcrOutputError("The OCR engine returned an unsafe text artifact.")
        result.output_path.resolve(strict=True).relative_to(workspace.resolve(strict=True))
        text = result.output_path.read_bytes().decode("utf-8")
    except (OSError, ValueError, UnicodeError) as error:
        raise OcrOutputError("Unable to validate the OCR text artifact.") from error
    return result.output_path, text

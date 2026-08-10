"""PDF-specific HTTP adapter helpers built on reusable converter APIs."""

from collections.abc import Sequence
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from docuforge.api.errors import ApiError
from docuforge.api.uploads import StoredUpload
from docuforge.converters import (
    PageRotation,
    PdfExtractPagesPathRequest,
    PdfMergeConverter,
    PdfRemovePagesPathRequest,
    PdfRotatePathRequest,
    PdfSplitDirectoryRequest,
    extract_pdf_pages,
    remove_pdf_pages,
    rotate_pdf_pages,
    split_pdf_to_directory,
)
from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    DocumentFormat,
)

PDF_MEDIA_TYPE = "application/pdf"
ZIP_MEDIA_TYPE = "application/zip"


def parse_page_selection(values: Sequence[str] | None) -> tuple[int, ...]:
    """Parse repeated positive one-based page fields into zero-based indices."""
    if not values:
        raise ApiError(
            status_code=400,
            code="invalid_page_selection",
            message="At least one valid page number is required.",
        )

    pages: list[int] = []
    seen_pages: set[int] = set()
    for value in values:
        if not value.isascii() or not value.isdigit():
            raise _invalid_page_selection_error()
        page = int(value)
        if page < 1 or page in seen_pages:
            raise _invalid_page_selection_error()
        seen_pages.add(page)
        pages.append(page - 1)
    return tuple(pages)


def parse_rotations(values: Sequence[str] | None) -> tuple[PageRotation, ...]:
    """Parse repeated PAGE:DEGREES fields into zero-based rotation models."""
    if not values:
        raise ApiError(
            status_code=400,
            code="invalid_rotation",
            message="At least one valid rotation is required.",
        )

    rotations: list[PageRotation] = []
    seen_pages: set[int] = set()
    for value in values:
        parts = value.split(":")
        if len(parts) != 2:
            raise _invalid_rotation_error()
        page_value, degrees_value = parts
        if (
            not page_value.isascii()
            or not page_value.isdigit()
            or not degrees_value.isascii()
            or not degrees_value.isdigit()
        ):
            raise _invalid_rotation_error()
        page = int(page_value)
        degrees = int(degrees_value)
        if page < 1 or degrees not in {90, 180, 270} or page in seen_pages:
            raise _invalid_rotation_error()
        seen_pages.add(page)
        rotations.append(PageRotation(page_index=page - 1, degrees=degrees))
    return tuple(rotations)


def merge_pdfs(uploads: Sequence[StoredUpload], output_path: Path) -> None:
    """Delegate an ordered merge to the reusable PDF merge converter."""
    request = ConversionRequest(
        input_paths=tuple(upload.stored_path for upload in uploads),
        output_path=output_path,
        source_format=DocumentFormat.PDF,
        target_format=DocumentFormat.PDF,
        operation=ConversionOperation.MERGE,
    )
    PdfMergeConverter().convert(request)


def split_pdf(upload: StoredUpload, output_path: Path) -> None:
    """Split one PDF and package deterministic client-safe members in a ZIP."""
    split_directory = output_path.parent / "split-pages"
    result = split_pdf_to_directory(
        PdfSplitDirectoryRequest(
            input_path=upload.stored_path,
            output_directory=split_directory,
        )
    )
    stem = _client_stem(upload.original_name)
    with ZipFile(output_path, mode="w", compression=ZIP_DEFLATED) as archive:
        for page_number, page_path in enumerate(result.output_paths, start=1):
            archive.write(
                page_path,
                arcname=f"{stem}-page-{page_number:04d}.pdf",
            )


def rotate_pdf(
    upload: StoredUpload,
    output_path: Path,
    rotations: tuple[PageRotation, ...],
) -> None:
    """Delegate selected-page rotation to the reusable path API."""
    rotate_pdf_pages(
        PdfRotatePathRequest(
            input_path=upload.stored_path,
            output_path=output_path,
            rotations=rotations,
        )
    )


def remove_pdf_pages_from_upload(
    upload: StoredUpload,
    output_path: Path,
    page_indices: tuple[int, ...],
) -> None:
    """Delegate selected-page removal to the reusable path API."""
    remove_pdf_pages(
        PdfRemovePagesPathRequest(
            input_path=upload.stored_path,
            output_path=output_path,
            page_indices=page_indices,
        )
    )


def extract_pdf_pages_from_upload(
    upload: StoredUpload,
    output_path: Path,
    page_indices: tuple[int, ...],
) -> None:
    """Delegate ordered selected-page extraction to the reusable path API."""
    extract_pdf_pages(
        PdfExtractPagesPathRequest(
            input_path=upload.stored_path,
            output_path=output_path,
            page_indices=page_indices,
        )
    )


def derived_download_name(original_name: str, suffix: str) -> str:
    """Build a safe client-facing filename from a normalized upload basename."""
    extension = Path(suffix).suffix
    stem_suffix = suffix[: -len(extension)] if extension else suffix
    maximum_stem_length = 255 - len(stem_suffix) - len(extension)
    stem = _client_stem(original_name)[:maximum_stem_length]
    return f"{stem}{stem_suffix}{extension}"


def _client_stem(original_name: str) -> str:
    stem = Path(original_name).stem
    while ".." in stem:
        stem = stem.replace("..", "_")
    return stem


def _invalid_page_selection_error() -> ApiError:
    return ApiError(
        status_code=400,
        code="invalid_page_selection",
        message="Page selections must be unique positive integers.",
    )


def _invalid_rotation_error() -> ApiError:
    return ApiError(
        status_code=400,
        code="invalid_rotation",
        message="Rotations must use unique positive pages and 90, 180, or 270 degrees.",
    )

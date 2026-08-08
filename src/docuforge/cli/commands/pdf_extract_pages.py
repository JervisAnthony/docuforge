"""Command-line execution for extracting selected PDF pages."""

import sys
from collections.abc import Sequence
from pathlib import Path

from docuforge.converters import PdfExtractPagesPathRequest, extract_pdf_pages
from docuforge.core import DocuForgeError


def run_pdf_extract_pages(
    input_path: Path,
    output_path: Path,
    pages: Sequence[int],
) -> int:
    """Extract parsed one-based PDF pages and return a conventional exit code."""
    seen_pages: set[int] = set()
    for page in pages:
        if page in seen_pages:
            print(f"Error: Each page may be extracted only once: {page}", file=sys.stderr)
            return 2
        seen_pages.add(page)

    page_indices = tuple(page - 1 for page in pages)

    try:
        request = PdfExtractPagesPathRequest(
            input_path=input_path,
            output_path=output_path,
            page_indices=page_indices,
        )
        result = extract_pdf_pages(request)
    except DocuForgeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Extracted {len(request.page_indices)} pages into {result.output_path}")
    return 0

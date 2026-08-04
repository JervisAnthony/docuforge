"""Command-line execution for rotating selected PDF pages."""

import sys
from collections.abc import Sequence
from pathlib import Path

from docuforge.converters import (
    PageRotation,
    PdfRotatePathRequest,
    rotate_pdf_pages,
)
from docuforge.core import DocuForgeError


def run_pdf_rotate(
    input_path: Path,
    output_path: Path,
    rotations: Sequence[PageRotation],
) -> int:
    """Rotate parsed PDF pages and return a conventional command exit code."""
    try:
        request = PdfRotatePathRequest(
            input_path=input_path,
            output_path=output_path,
            rotations=tuple(rotations),
        )
        result = rotate_pdf_pages(request)
    except DocuForgeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Rotated {len(request.rotations)} pages into {result.output_path}")
    return 0

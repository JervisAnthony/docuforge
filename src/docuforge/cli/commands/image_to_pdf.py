"""Command-line execution for converting ordered images into one PDF."""

import sys
from collections.abc import Sequence
from pathlib import Path

from docuforge.converters import ImageToPdfPathRequest, convert_images_to_pdf
from docuforge.core import DocuForgeError


def run_image_to_pdf(input_paths: Sequence[Path], output_path: Path) -> int:
    """Convert parsed image paths and return a conventional command exit code."""
    try:
        request = ImageToPdfPathRequest(
            input_paths=tuple(input_paths),
            output_path=output_path,
        )
        result = convert_images_to_pdf(request)
    except DocuForgeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(
        f"Converted {len(request.input_paths)} image files into {result.output_path}"
    )
    return 0

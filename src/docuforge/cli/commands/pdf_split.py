"""Command-line execution for splitting a PDF into directory outputs."""

import sys
from pathlib import Path

from docuforge.converters import PdfSplitDirectoryRequest, split_pdf_to_directory
from docuforge.core import DocuForgeError


def run_pdf_split(input_path: Path, output_directory: Path) -> int:
    """Split a parsed PDF path and return a conventional command exit code."""
    try:
        result = split_pdf_to_directory(
            PdfSplitDirectoryRequest(
                input_path=input_path,
                output_directory=output_directory,
            )
        )
    except DocuForgeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(
        f"Split {input_path} into {len(result.output_paths)} PDF files "
        f"in {output_directory}"
    )
    return 0

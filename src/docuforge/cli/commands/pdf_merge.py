"""Command-line execution for PDF merging."""

import sys
from collections.abc import Sequence
from pathlib import Path

from docuforge.converters import PdfMergeConverter
from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    DocuForgeError,
    DocumentFormat,
)


def run_pdf_merge(input_paths: Sequence[Path], output_path: Path) -> int:
    """Merge parsed PDF paths and return a conventional command exit code."""
    try:
        request = ConversionRequest(
            input_paths=tuple(input_paths),
            output_path=output_path,
            source_format=DocumentFormat.PDF,
            target_format=DocumentFormat.PDF,
            operation=ConversionOperation.MERGE,
        )
        PdfMergeConverter().convert(request)
    except DocuForgeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Merged {len(input_paths)} PDF files into {output_path}")
    return 0

"""Shared trust boundary for retained converted outputs."""

import stat

from docuforge.batch import (
    BatchDocumentConvertRequest,
    BatchDocumentResult,
    BatchImageCompressRequest,
    BatchImageConvertRequest,
    BatchImageResizeRequest,
    BatchImageResult,
)
from docuforge.batch.document import _valid_preserved_pdf
from docuforge.batch.image import _valid_preserved_image


def retained_outputs_are_valid(request: object, result: object) -> bool:
    """Validate files only when their completed result is about to be reused."""
    if isinstance(
        request, (BatchImageConvertRequest, BatchImageResizeRequest, BatchImageCompressRequest)
    ) and isinstance(result, BatchImageResult):
        validator = _valid_preserved_image
    elif isinstance(request, BatchDocumentConvertRequest) and isinstance(
        result, BatchDocumentResult
    ):
        validator = _valid_preserved_pdf
    else:
        return False
    try:
        node = request.output_directory.lstat()
        if stat.S_ISLNK(node.st_mode) or not stat.S_ISDIR(node.st_mode):
            return False
        return all(
            validator(output, source=request.items[output.position], request=request)
            for output in result.outputs
        )
    except (IndexError, TypeError, OSError):
        return False

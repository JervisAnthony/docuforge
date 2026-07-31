"""Operations supported by DocuForge conversion requests."""

from enum import Enum


class ConversionOperation(str, Enum):
    """Describe the intent of a document-processing request."""

    CONVERT = "convert"
    MERGE = "merge"
    SPLIT = "split"

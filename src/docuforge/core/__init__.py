"""Public domain API for DocuForge."""

from docuforge.core.converters import Converter
from docuforge.core.exceptions import (
    ConverterNotFoundError,
    DocuForgeError,
    DuplicateConverterRegistrationError,
    InvalidConversionRequestError,
    InvalidFormatError,
    UnsupportedConversionError,
)
from docuforge.core.formats import DocumentFormat
from docuforge.core.models import ConversionRequest
from docuforge.core.operations import ConversionOperation
from docuforge.core.registry import ConverterKey, ConverterRegistry

__all__ = [
    "ConversionOperation",
    "ConversionRequest",
    "Converter",
    "ConverterKey",
    "ConverterNotFoundError",
    "ConverterRegistry",
    "DocuForgeError",
    "DocumentFormat",
    "DuplicateConverterRegistrationError",
    "InvalidConversionRequestError",
    "InvalidFormatError",
    "UnsupportedConversionError",
]

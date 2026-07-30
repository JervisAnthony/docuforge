"""Tests for the public DocuForge exception hierarchy."""

import pytest

from docuforge.core import (
    ConverterNotFoundError,
    DocuForgeError,
    DuplicateConverterRegistrationError,
    InvalidConversionRequestError,
    InvalidFormatError,
    UnsupportedConversionError,
)


@pytest.mark.parametrize(
    "exception_type",
    [
        InvalidFormatError,
        InvalidConversionRequestError,
        UnsupportedConversionError,
        ConverterNotFoundError,
        DuplicateConverterRegistrationError,
    ],
)
def test_core_exceptions_inherit_from_docuforge_error(
    exception_type: type[DocuForgeError],
) -> None:
    assert issubclass(exception_type, DocuForgeError)

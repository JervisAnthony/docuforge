"""Tests for the Office conversion exception contract."""

import pytest

from docuforge.converters.office import (
    OfficeConversionError,
    OfficeEngineExecutionError,
    OfficeEngineTimeoutError,
    OfficeEngineUnavailableError,
)
from docuforge.core import DocuForgeError


@pytest.mark.parametrize(
    "exception_type",
    [
        OfficeEngineUnavailableError,
        OfficeEngineTimeoutError,
        OfficeEngineExecutionError,
    ],
)
def test_office_engine_errors_share_the_conversion_error_contract(
    exception_type: type[OfficeConversionError],
) -> None:
    assert issubclass(exception_type, OfficeConversionError)
    assert issubclass(exception_type, DocuForgeError)

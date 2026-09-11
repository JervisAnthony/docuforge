"""Application-neutral contract for Office-to-PDF engines."""

from typing import Protocol

from docuforge.converters.office.models import OfficeConversionRequest, OfficeConversionResult


class OfficeConversionEngine(Protocol):
    """Render supported Office documents without exposing backend details."""

    def convert_to_pdf(self, request: OfficeConversionRequest) -> OfficeConversionResult:
        """Convert one supported Office document into a validated PDF artifact."""

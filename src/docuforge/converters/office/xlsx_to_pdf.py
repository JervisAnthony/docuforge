"""Concrete XLSX-to-PDF conversion workflow."""

from __future__ import annotations

from pathlib import Path

from docuforge.converters.office._workflow import publish_conversion, validate_request
from docuforge.converters.office.engine import OfficeConversionEngine
from docuforge.converters.office.models import XlsxToPdfRequest
from docuforge.core import ConversionOperation, ConversionRequest, Converter, DocumentFormat


class XlsxToPdfConverter(Converter):
    """Convert one XLSX into an exact PDF destination through an injected engine."""

    def __init__(self, engine: OfficeConversionEngine) -> None:
        if not callable(getattr(engine, "convert_to_pdf", None)):
            raise TypeError("engine must implement OfficeConversionEngine")
        super().__init__(ConversionOperation.CONVERT, DocumentFormat.XLSX, DocumentFormat.PDF)
        self._engine = engine

    def convert(self, request: ConversionRequest) -> Path:
        """Render, validate, and atomically publish an XLSX as the requested PDF."""
        resolved_input = validate_request(
            request,
            request_type=XlsxToPdfRequest,
            source_format=DocumentFormat.XLSX,
            required_member="xl/workbook.xml",
        )
        return publish_conversion(
            request,
            engine=self._engine,
            resolved_input=resolved_input,
            source_format=DocumentFormat.XLSX,
        )


def convert_xlsx_to_pdf(
    request: XlsxToPdfRequest, *, engine: OfficeConversionEngine
) -> Path:
    """Convert one XLSX by delegating to the concrete converter."""
    return XlsxToPdfConverter(engine).convert(request)

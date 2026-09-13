"""Concrete PPTX-to-PDF conversion workflow."""

from __future__ import annotations

from pathlib import Path

import docuforge.converters.office._workflow as workflow
from docuforge.converters.office._workflow import publish_conversion, validate_request
from docuforge.converters.office.engine import OfficeConversionEngine
from docuforge.converters.office.models import PptxToPdfRequest
from docuforge.core import ConversionOperation, ConversionRequest, Converter, DocumentFormat

os = workflow.os  # Retained for publication-failure tests.


class PptxToPdfConverter(Converter):
    """Convert one PPTX into an exact PDF destination through an injected engine."""

    def __init__(self, engine: OfficeConversionEngine) -> None:
        if not callable(getattr(engine, "convert_to_pdf", None)):
            raise TypeError("engine must implement OfficeConversionEngine")
        super().__init__(ConversionOperation.CONVERT, DocumentFormat.PPTX, DocumentFormat.PDF)
        self._engine = engine

    def convert(self, request: ConversionRequest) -> Path:
        """Render, validate, and atomically publish a PPTX as the requested PDF."""
        resolved_input = validate_request(
            request,
            request_type=PptxToPdfRequest,
            source_format=DocumentFormat.PPTX,
            required_member="ppt/presentation.xml",
        )
        return publish_conversion(
            request,
            engine=self._engine,
            resolved_input=resolved_input,
            source_format=DocumentFormat.PPTX,
        )


def convert_pptx_to_pdf(
    request: PptxToPdfRequest, *, engine: OfficeConversionEngine
) -> Path:
    """Convert one PPTX by delegating to the concrete converter."""
    return PptxToPdfConverter(engine).convert(request)

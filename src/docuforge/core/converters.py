"""Converter contracts for DocuForge."""

from abc import ABC, abstractmethod
from pathlib import Path

from docuforge.core.formats import DocumentFormat
from docuforge.core.models import ConversionRequest


class Converter(ABC):
    """Base interface implemented by document converters."""

    def __init__(
        self,
        source_format: str | DocumentFormat,
        target_format: str | DocumentFormat,
    ) -> None:
        """Initialize a converter for one normalized format pair."""
        self._source_format = DocumentFormat.normalize(source_format)
        self._target_format = DocumentFormat.normalize(target_format)

    @property
    def source_format(self) -> DocumentFormat:
        """Return the format accepted by this converter."""
        return self._source_format

    @property
    def target_format(self) -> DocumentFormat:
        """Return the format produced by this converter."""
        return self._target_format

    @abstractmethod
    def convert(self, request: ConversionRequest) -> Path:
        """Convert a validated request and return its output path."""
        raise NotImplementedError

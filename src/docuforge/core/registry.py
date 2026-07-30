"""Registry for pluggable document converters."""

from docuforge.core.converters import Converter
from docuforge.core.exceptions import (
    ConverterNotFoundError,
    DuplicateConverterRegistrationError,
)
from docuforge.core.formats import DocumentFormat
from docuforge.core.models import ConversionRequest
from docuforge.core.operations import ConversionOperation

ConverterKey = tuple[ConversionOperation, DocumentFormat, DocumentFormat]


class ConverterRegistry:
    """Store and locate converter instances by source and target format."""

    def __init__(self) -> None:
        """Create an empty, independent converter registry."""
        self._converters: dict[ConverterKey, Converter] = {}

    def register(self, converter: Converter) -> None:
        """Register a converter instance for its normalized format pair."""
        if not isinstance(converter, Converter):
            raise TypeError("converter must be an instance of Converter")

        key = (
            ConversionOperation(converter.operation),
            DocumentFormat.normalize(converter.source_format),
            DocumentFormat.normalize(converter.target_format),
        )
        if key in self._converters:
            raise DuplicateConverterRegistrationError(
                "A converter is already registered for "
                f"{key[0].value}: {key[1].value} -> {key[2].value}."
            )
        self._converters[key] = converter

    def get_converter(
        self,
        operation: ConversionOperation,
        source_format: str | DocumentFormat,
        target_format: str | DocumentFormat,
    ) -> Converter:
        """Return the converter registered for an operation and format pair."""
        key = (
            ConversionOperation(operation),
            DocumentFormat.normalize(source_format),
            DocumentFormat.normalize(target_format),
        )
        try:
            return self._converters[key]
        except KeyError as error:
            raise ConverterNotFoundError(
                "No converter is registered for "
                f"{key[0].value}: {key[1].value} -> {key[2].value}."
            ) from error

    def get_converter_for(self, request: ConversionRequest) -> Converter:
        """Return the converter matching a conversion request."""
        if not isinstance(request, ConversionRequest):
            raise TypeError("request must be an instance of ConversionRequest")
        return self.get_converter(
            request.operation,
            request.source_format,
            request.target_format,
        )

    def supported_conversions(self) -> tuple[ConverterKey, ...]:
        """Return converter keys in deterministic registration order."""
        return tuple(self._converters)

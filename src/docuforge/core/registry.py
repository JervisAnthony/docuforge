"""Registry for pluggable document converters."""

from docuforge.core.converters import Converter
from docuforge.core.exceptions import (
    ConverterNotFoundError,
    DuplicateConverterRegistrationError,
)
from docuforge.core.formats import DocumentFormat
from docuforge.core.models import ConversionRequest

ConversionPair = tuple[DocumentFormat, DocumentFormat]


class ConverterRegistry:
    """Store and locate converter instances by source and target format."""

    def __init__(self) -> None:
        """Create an empty, independent converter registry."""
        self._converters: dict[ConversionPair, Converter] = {}

    def register(self, converter: Converter) -> None:
        """Register a converter instance for its normalized format pair."""
        if not isinstance(converter, Converter):
            raise TypeError("converter must be an instance of Converter")

        pair = (
            DocumentFormat.normalize(converter.source_format),
            DocumentFormat.normalize(converter.target_format),
        )
        if pair in self._converters:
            raise DuplicateConverterRegistrationError(
                f"A converter is already registered for {pair[0].value} -> {pair[1].value}."
            )
        self._converters[pair] = converter

    def get_converter(
        self,
        source_format: str | DocumentFormat,
        target_format: str | DocumentFormat,
    ) -> Converter:
        """Return the converter registered for a normalized format pair."""
        pair = (
            DocumentFormat.normalize(source_format),
            DocumentFormat.normalize(target_format),
        )
        try:
            return self._converters[pair]
        except KeyError as error:
            raise ConverterNotFoundError(
                f"No converter is registered for {pair[0].value} -> {pair[1].value}."
            ) from error

    def get_converter_for(self, request: ConversionRequest) -> Converter:
        """Return the converter matching a conversion request."""
        if not isinstance(request, ConversionRequest):
            raise TypeError("request must be an instance of ConversionRequest")
        return self.get_converter(request.source_format, request.target_format)

    def supported_pairs(self) -> tuple[ConversionPair, ...]:
        """Return registered format pairs in deterministic registration order."""
        return tuple(self._converters)

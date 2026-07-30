"""Tests for the converter registry."""

from pathlib import Path

import pytest

from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    Converter,
    ConverterNotFoundError,
    ConverterRegistry,
    DocumentFormat,
    DuplicateConverterRegistrationError,
)


class StubConverter(Converter):
    """Converter test double that performs no filesystem operations."""

    def convert(self, request: ConversionRequest) -> Path:
        """Return the request output path."""
        return request.output_path


def make_request(
    source_format: DocumentFormat = DocumentFormat.TXT,
    target_format: DocumentFormat = DocumentFormat.PDF,
) -> ConversionRequest:
    """Create a valid request for registry tests."""
    return ConversionRequest(
        input_paths=(Path(f"input.{source_format.value}"),),
        output_path=Path(f"output.{target_format.value}"),
        source_format=source_format,
        target_format=target_format,
    )


def test_register_and_lookup_converter() -> None:
    registry = ConverterRegistry()
    converter = StubConverter(
        ConversionOperation.CONVERT,
        DocumentFormat.TXT,
        DocumentFormat.PDF,
    )

    registry.register(converter)

    assert (
        registry.get_converter(ConversionOperation.CONVERT, " .TXT ", ".pdf") is converter
    )


def test_lookup_converter_by_conversion_request() -> None:
    registry = ConverterRegistry()
    converter = StubConverter(
        ConversionOperation.CONVERT,
        DocumentFormat.TXT,
        DocumentFormat.PDF,
    )
    other_operation = StubConverter(
        ConversionOperation.MERGE,
        DocumentFormat.TXT,
        DocumentFormat.PDF,
    )
    request = make_request()
    registry.register(other_operation)
    registry.register(converter)

    assert registry.get_converter_for(request) is converter


def test_missing_converter_raises_converter_not_found_error() -> None:
    registry = ConverterRegistry()

    with pytest.raises(ConverterNotFoundError):
        registry.get_converter(
            ConversionOperation.CONVERT,
            DocumentFormat.TXT,
            DocumentFormat.PDF,
        )


def test_duplicate_registration_is_rejected() -> None:
    registry = ConverterRegistry()
    registry.register(
        StubConverter(
            ConversionOperation.CONVERT,
            DocumentFormat.TXT,
            DocumentFormat.PDF,
        )
    )

    with pytest.raises(DuplicateConverterRegistrationError):
        registry.register(
            StubConverter(
                ConversionOperation.CONVERT,
                DocumentFormat.TXT,
                DocumentFormat.PDF,
            )
        )


def test_invalid_registration_input_is_rejected() -> None:
    registry = ConverterRegistry()

    with pytest.raises(TypeError):
        registry.register(object())  # type: ignore[arg-type]


def test_supported_conversions_preserve_registration_order() -> None:
    registry = ConverterRegistry()
    registry.register(
        StubConverter(
            ConversionOperation.CONVERT,
            DocumentFormat.TXT,
            DocumentFormat.PDF,
        )
    )
    registry.register(
        StubConverter(
            ConversionOperation.CONVERT,
            DocumentFormat.PNG,
            DocumentFormat.JPG,
        )
    )

    assert registry.supported_conversions() == (
        (ConversionOperation.CONVERT, DocumentFormat.TXT, DocumentFormat.PDF),
        (ConversionOperation.CONVERT, DocumentFormat.PNG, DocumentFormat.JPG),
    )


def test_different_operations_for_the_same_format_pair_can_coexist() -> None:
    registry = ConverterRegistry()
    convert = StubConverter(
        ConversionOperation.CONVERT,
        DocumentFormat.TXT,
        DocumentFormat.PDF,
    )
    merge = StubConverter(
        ConversionOperation.MERGE,
        DocumentFormat.TXT,
        DocumentFormat.PDF,
    )

    registry.register(convert)
    registry.register(merge)

    assert (
        registry.get_converter(
            ConversionOperation.CONVERT,
            DocumentFormat.TXT,
            DocumentFormat.PDF,
        )
        is convert
    )
    assert (
        registry.get_converter(
            ConversionOperation.MERGE,
            DocumentFormat.TXT,
            DocumentFormat.PDF,
        )
        is merge
    )


def test_registry_instances_do_not_share_state() -> None:
    first_registry = ConverterRegistry()
    second_registry = ConverterRegistry()
    first_registry.register(
        StubConverter(
            ConversionOperation.CONVERT,
            DocumentFormat.TXT,
            DocumentFormat.PDF,
        )
    )

    assert first_registry.supported_conversions() == (
        (ConversionOperation.CONVERT, DocumentFormat.TXT, DocumentFormat.PDF),
    )
    assert second_registry.supported_conversions() == ()

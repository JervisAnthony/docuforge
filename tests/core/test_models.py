"""Tests for core conversion-request models."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    DocumentFormat,
    InvalidConversionRequestError,
)


def test_valid_conversion_request() -> None:
    request = ConversionRequest(
        input_paths=(Path("input.txt"),),
        output_path=Path("output.pdf"),
        source_format=DocumentFormat.TXT,
        target_format=DocumentFormat.PDF,
    )

    assert request.input_paths == (Path("input.txt"),)
    assert request.output_path == Path("output.pdf")
    assert request.source_format is DocumentFormat.TXT
    assert request.target_format is DocumentFormat.PDF


def test_conversion_request_is_immutable() -> None:
    request = ConversionRequest(
        input_paths=(Path("input.txt"),),
        output_path=Path("output.pdf"),
        source_format=DocumentFormat.TXT,
        target_format=DocumentFormat.PDF,
    )

    with pytest.raises(FrozenInstanceError):
        request.output_path = Path("other.pdf")  # type: ignore[misc]


def test_conversion_request_rejects_empty_input_paths() -> None:
    with pytest.raises(InvalidConversionRequestError):
        ConversionRequest(
            input_paths=(),
            output_path=Path("output.pdf"),
            source_format=DocumentFormat.TXT,
            target_format=DocumentFormat.PDF,
        )


def test_conversion_request_rejects_duplicate_input_paths() -> None:
    with pytest.raises(InvalidConversionRequestError):
        ConversionRequest(
            input_paths=(Path("input.txt"), Path("input.txt")),
            output_path=Path("output.pdf"),
            source_format=DocumentFormat.TXT,
            target_format=DocumentFormat.PDF,
        )


def test_conversion_request_rejects_an_output_path_used_as_input() -> None:
    with pytest.raises(InvalidConversionRequestError):
        ConversionRequest(
            input_paths=(Path("output.pdf"),),
            output_path=Path("output.pdf"),
            source_format=DocumentFormat.TXT,
            target_format=DocumentFormat.PDF,
        )


def test_conversion_request_rejects_identical_formats() -> None:
    with pytest.raises(InvalidConversionRequestError):
        ConversionRequest(
            input_paths=(Path("input.pdf"),),
            output_path=Path("output.pdf"),
            source_format=DocumentFormat.PDF,
            target_format=DocumentFormat.PDF,
        )


def test_merge_request_allows_identical_formats() -> None:
    request = ConversionRequest(
        input_paths=(Path("first.pdf"), Path("second.pdf")),
        output_path=Path("output.pdf"),
        source_format=DocumentFormat.PDF,
        target_format=DocumentFormat.PDF,
        operation=ConversionOperation.MERGE,
    )

    assert request.operation is ConversionOperation.MERGE


def test_merge_request_rejects_different_formats() -> None:
    with pytest.raises(InvalidConversionRequestError):
        ConversionRequest(
            input_paths=(Path("input.txt"), Path("other.txt")),
            output_path=Path("output.pdf"),
            source_format=DocumentFormat.TXT,
            target_format=DocumentFormat.PDF,
            operation=ConversionOperation.MERGE,
        )


def test_conversion_request_rejects_unknown_operation() -> None:
    with pytest.raises(InvalidConversionRequestError):
        ConversionRequest(
            input_paths=(Path("input.txt"),),
            output_path=Path("output.pdf"),
            source_format=DocumentFormat.TXT,
            target_format=DocumentFormat.PDF,
            operation="unknown",  # type: ignore[arg-type]
        )

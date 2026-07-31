"""Core domain models for document conversion."""

from dataclasses import dataclass
from pathlib import Path

from docuforge.core.exceptions import InvalidConversionRequestError
from docuforge.core.formats import DocumentFormat
from docuforge.core.operations import ConversionOperation


@dataclass(frozen=True, slots=True)
class ConversionRequest:
    """An immutable, validated request to convert one or more documents."""

    input_paths: tuple[Path, ...]
    output_path: Path
    source_format: DocumentFormat
    target_format: DocumentFormat
    operation: ConversionOperation = ConversionOperation.CONVERT

    def __post_init__(self) -> None:
        """Normalize field values and enforce conversion-request constraints."""
        input_paths = tuple(Path(path) for path in self.input_paths)
        output_path = Path(self.output_path)
        source_format = DocumentFormat.normalize(self.source_format)
        target_format = DocumentFormat.normalize(self.target_format)
        try:
            operation = ConversionOperation(self.operation)
        except ValueError as error:
            raise InvalidConversionRequestError(
                f"Unsupported conversion operation: {self.operation!r}."
            ) from error

        object.__setattr__(self, "input_paths", input_paths)
        object.__setattr__(self, "output_path", output_path)
        object.__setattr__(self, "source_format", source_format)
        object.__setattr__(self, "target_format", target_format)
        object.__setattr__(self, "operation", operation)

        if not input_paths:
            raise InvalidConversionRequestError("At least one input path is required.")
        if len(set(input_paths)) != len(input_paths):
            raise InvalidConversionRequestError("Input paths must not contain duplicates.")
        if output_path in input_paths:
            raise InvalidConversionRequestError("Output path must differ from every input path.")
        if operation is ConversionOperation.CONVERT and source_format is target_format:
            raise InvalidConversionRequestError("Source and target formats must differ.")
        if (
            operation in {ConversionOperation.MERGE, ConversionOperation.SPLIT}
            and source_format is not target_format
        ):
            raise InvalidConversionRequestError(
                f"{operation.value.title()} requests require identical formats."
            )
        if operation is ConversionOperation.SPLIT and len(input_paths) != 1:
            raise InvalidConversionRequestError("Split requests require exactly one input path.")

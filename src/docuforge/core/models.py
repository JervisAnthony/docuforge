"""Core domain models for document conversion."""

from dataclasses import dataclass
from pathlib import Path

from docuforge.core.exceptions import InvalidConversionRequestError
from docuforge.core.formats import DocumentFormat


@dataclass(frozen=True, slots=True)
class ConversionRequest:
    """An immutable, validated request to convert one or more documents."""

    input_paths: tuple[Path, ...]
    output_path: Path
    source_format: DocumentFormat
    target_format: DocumentFormat

    def __post_init__(self) -> None:
        """Normalize field values and enforce conversion-request constraints."""
        input_paths = tuple(Path(path) for path in self.input_paths)
        output_path = Path(self.output_path)
        source_format = DocumentFormat.normalize(self.source_format)
        target_format = DocumentFormat.normalize(self.target_format)

        object.__setattr__(self, "input_paths", input_paths)
        object.__setattr__(self, "output_path", output_path)
        object.__setattr__(self, "source_format", source_format)
        object.__setattr__(self, "target_format", target_format)

        if not input_paths:
            raise InvalidConversionRequestError("At least one input path is required.")
        if len(set(input_paths)) != len(input_paths):
            raise InvalidConversionRequestError("Input paths must not contain duplicates.")
        if output_path in input_paths:
            raise InvalidConversionRequestError("Output path must differ from every input path.")
        if source_format is target_format:
            raise InvalidConversionRequestError("Source and target formats must differ.")

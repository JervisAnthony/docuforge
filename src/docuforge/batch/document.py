"""Sequential heterogeneous Office-to-PDF batch processing."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from docuforge.batch.exceptions import BatchProcessingError, InvalidBatchDefinitionError
from docuforge.batch.models import (
    Batch,
    BatchId,
    BatchItemFailure,
    BatchItemId,
    BatchItemRequest,
    BatchItemResult,
    BatchItemStatus,
    BatchRequest,
)
from docuforge.converters.office import (
    SUPPORTED_OFFICE_SOURCE_FORMATS,
    DocxToPdfRequest,
    OfficeConversionEngine,
    OfficeConversionError,
    PptxToPdfRequest,
    XlsxToPdfRequest,
    convert_docx_to_pdf,
    convert_pptx_to_pdf,
    convert_xlsx_to_pdf,
)
from docuforge.core import (
    DocumentFormat,
    InvalidConversionRequestError,
    InvalidFormatError,
    UnsupportedConversionError,
)
from docuforge.jobs import OperationKey

_OPERATION = OperationKey("office.to_pdf")
_FORMAT_BY_SUFFIX = {
    ".docx": DocumentFormat.DOCX,
    ".pptx": DocumentFormat.PPTX,
    ".xlsx": DocumentFormat.XLSX,
}

_INVALID_REQUEST_FAILURE = BatchItemFailure(
    "invalid_document_request", "The document request is invalid."
)
_UNSUPPORTED_FORMAT_FAILURE = BatchItemFailure(
    "unsupported_document_format", "The document format is not supported."
)
_PROCESSING_FAILURE = BatchItemFailure(
    "document_processing_failed", "The document could not be processed."
)
_INVALID_OUTPUT_FAILURE = BatchItemFailure(
    "invalid_document_output", "The converted document output was invalid."
)
_PUBLISH_FAILURE = BatchItemFailure(
    "document_output_publish_failed", "The converted document could not be published."
)


@dataclass(frozen=True, slots=True)
class BatchDocumentInput:
    """One Office source document with stable batch identity."""

    input_path: Path
    id: BatchItemId = field(default_factory=BatchItemId.new)
    descriptor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.input_path, Path):
            raise InvalidBatchDefinitionError("Document input path must be a Path.")
        object.__setattr__(self, "id", BatchItemId(self.id))
        descriptor = self.descriptor
        if descriptor is None:
            descriptor = self.input_path.name
            if not descriptor.strip():
                descriptor = "document"
        if not isinstance(descriptor, str) or not descriptor.strip():
            raise InvalidBatchDefinitionError("Document descriptor must be a nonblank string.")
        object.__setattr__(self, "descriptor", descriptor.strip())


@dataclass(frozen=True, slots=True)
class BatchDocumentConvertRequest:
    """An ordered heterogeneous Office-to-PDF batch request."""

    items: tuple[BatchDocumentInput, ...]
    output_directory: Path
    batch_id: BatchId = field(default_factory=BatchId.new)

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple) or not self.items:
            raise InvalidBatchDefinitionError(
                "A batch document request requires a nonempty item tuple."
            )
        if any(not isinstance(item, BatchDocumentInput) for item in self.items):
            raise InvalidBatchDefinitionError(
                "Batch document items must be BatchDocumentInput values."
            )
        item_ids = tuple(item.id for item in self.items)
        if len(set(item_ids)) != len(item_ids):
            raise InvalidBatchDefinitionError("Batch document item IDs must be unique.")
        if not isinstance(self.output_directory, Path):
            raise InvalidBatchDefinitionError("Batch output directory must be a Path.")
        object.__setattr__(self, "batch_id", BatchId(self.batch_id))


def _normalize_source_format(value: object) -> DocumentFormat:
    try:
        source_format = DocumentFormat.normalize(value)  # type: ignore[arg-type]
    except InvalidFormatError:
        raise InvalidBatchDefinitionError(
            "Document source format must be DOCX, PPTX, or XLSX."
        ) from None
    if source_format not in SUPPORTED_OFFICE_SOURCE_FORMATS:
        raise InvalidBatchDefinitionError(
            "Document source format must be DOCX, PPTX, or XLSX."
        )
    return source_format


@dataclass(frozen=True, slots=True)
class BatchDocumentOutput:
    """Concrete path metadata for one successfully published PDF."""

    item_id: BatchItemId
    position: int
    input_path: Path
    output_path: Path
    source_format: DocumentFormat
    target_format: DocumentFormat = DocumentFormat.PDF

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", BatchItemId(self.item_id))
        if type(self.position) is not int or self.position < 0:
            raise InvalidBatchDefinitionError("Document output position must be non-negative.")
        if not isinstance(self.input_path, Path) or not isinstance(self.output_path, Path):
            raise InvalidBatchDefinitionError("Document output paths must be Path values.")
        object.__setattr__(self, "source_format", _normalize_source_format(self.source_format))
        try:
            target_format = DocumentFormat.normalize(self.target_format)
        except InvalidFormatError:
            raise InvalidBatchDefinitionError("Document output target must be PDF.") from None
        if target_format is not DocumentFormat.PDF:
            raise InvalidBatchDefinitionError("Document output target must be PDF.")
        object.__setattr__(self, "target_format", target_format)


@dataclass(frozen=True, slots=True)
class BatchDocumentResult:
    """Terminal batch state and ordered metadata for successful PDFs."""

    batch: Batch
    output_directory: Path
    outputs: tuple[BatchDocumentOutput, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.batch, Batch) or not self.batch.is_terminal:
            raise InvalidBatchDefinitionError("A document result requires a terminal Batch.")
        if not isinstance(self.output_directory, Path):
            raise InvalidBatchDefinitionError("Document result output directory must be a Path.")
        if not isinstance(self.outputs, tuple) or any(
            not isinstance(output, BatchDocumentOutput) for output in self.outputs
        ):
            raise InvalidBatchDefinitionError(
                "Document result outputs must be a tuple of outputs."
            )
        positions = tuple(output.position for output in self.outputs)
        item_ids = tuple(output.item_id for output in self.outputs)
        if positions != tuple(sorted(positions)):
            raise InvalidBatchDefinitionError("Document outputs must retain item order.")
        if len(set(positions)) != len(positions) or len(set(item_ids)) != len(item_ids):
            raise InvalidBatchDefinitionError("Document result outputs must be unique.")
        by_id = {item.id: item for item in self.batch.items}
        for output in self.outputs:
            item = by_id.get(output.item_id)
            if (
                item is None
                or item.status is not BatchItemStatus.COMPLETED
                or item.position != output.position
                or item.result is None
                or item.result.descriptor != output.output_path.name
            ):
                raise InvalidBatchDefinitionError(
                    "Document output does not match its batch item."
                )
        completed_ids = {
            item.id for item in self.batch.items if item.status is BatchItemStatus.COMPLETED
        }
        if set(item_ids) != completed_ids:
            raise InvalidBatchDefinitionError(
                "Every completed document item requires one output."
            )


def batch_convert_documents(
    request: BatchDocumentConvertRequest, *, engine: OfficeConversionEngine
) -> BatchDocumentResult:
    """Convert supported Office items sequentially while isolating expected failures."""
    if not isinstance(request, BatchDocumentConvertRequest):
        raise TypeError("request must be a BatchDocumentConvertRequest")
    if not callable(getattr(engine, "convert_to_pdf", None)):
        raise TypeError("engine must implement OfficeConversionEngine")
    _validate_output_directory(request.output_directory)
    batch = Batch(
        BatchRequest(
            request.batch_id,
            _OPERATION,
            tuple(
                BatchItemRequest(item.id, position, item.descriptor)
                for position, item in enumerate(request.items)
            ),
        )
    )
    outputs: list[BatchDocumentOutput] = []
    temporary_directory: TemporaryDirectory[str] | None = None
    try:
        try:
            temporary_directory = TemporaryDirectory(
                dir=request.output_directory,
                prefix=".docuforge-batch-documents-",
            )
        except OSError as error:
            raise BatchProcessingError("Unable to process the document batch.") from error
        workspace = Path(temporary_directory.name)
        for position, item in enumerate(request.items):
            batch = batch.start_item(item.id)
            source_format = _FORMAT_BY_SUFFIX.get(item.input_path.suffix.lower())
            if source_format is None:
                batch = batch.fail_item(item.id, _UNSUPPORTED_FORMAT_FAILURE)
                continue
            item_workspace = workspace / f"item-{position + 1:04d}"
            final_output = request.output_directory / _output_name(item.input_path, position)
            try:
                if any(
                    _paths_resolve_equal(source.input_path, final_output)
                    for source in request.items
                ):
                    batch = batch.fail_item(item.id, _INVALID_REQUEST_FAILURE)
                    continue
                item_workspace.mkdir()
            except OSError:
                batch = batch.fail_item(item.id, _INVALID_OUTPUT_FAILURE)
                continue
            staged_output = item_workspace / final_output.name
            try:
                returned_output = _convert_item(
                    item.input_path,
                    staged_output,
                    source_format=source_format,
                    engine=engine,
                )
            except InvalidConversionRequestError:
                batch = batch.fail_item(item.id, _INVALID_REQUEST_FAILURE)
                continue
            except UnsupportedConversionError:
                batch = batch.fail_item(item.id, _UNSUPPORTED_FORMAT_FAILURE)
                continue
            except OfficeConversionError:
                batch = batch.fail_item(item.id, _PROCESSING_FAILURE)
                continue
            if not _valid_staged_pdf(
                returned_output,
                staged_output=staged_output,
                item_workspace=item_workspace,
            ):
                batch = batch.fail_item(item.id, _INVALID_OUTPUT_FAILURE)
                continue
            try:
                os.replace(staged_output, final_output)
            except OSError:
                batch = batch.fail_item(item.id, _PUBLISH_FAILURE)
                continue
            outputs.append(
                BatchDocumentOutput(
                    item.id,
                    position,
                    item.input_path,
                    final_output,
                    source_format,
                )
            )
            batch = batch.complete_item(item.id, BatchItemResult(final_output.name))
        return BatchDocumentResult(batch, request.output_directory, tuple(outputs))
    finally:
        if temporary_directory is not None:
            try:
                temporary_directory.cleanup()
            except OSError as error:
                raise BatchProcessingError("Unable to process the document batch.") from error


def _convert_item(
    input_path: Path,
    output_path: Path,
    *,
    source_format: DocumentFormat,
    engine: OfficeConversionEngine,
) -> Path:
    if source_format is DocumentFormat.DOCX:
        return convert_docx_to_pdf(DocxToPdfRequest(input_path, output_path), engine=engine)
    if source_format is DocumentFormat.PPTX:
        return convert_pptx_to_pdf(PptxToPdfRequest(input_path, output_path), engine=engine)
    return convert_xlsx_to_pdf(XlsxToPdfRequest(input_path, output_path), engine=engine)


def _validate_output_directory(output_directory: Path) -> None:
    try:
        valid = output_directory.exists() and output_directory.is_dir()
    except OSError:
        valid = False
    if not valid:
        raise InvalidBatchDefinitionError("Batch output directory must exist and be a directory.")


def _output_name(input_path: Path, position: int) -> str:
    stem = input_path.stem
    if not stem.strip() or stem in {".", ".."}:
        stem = "document"
    return f"{position + 1:04d}-{stem}.pdf"


def _paths_resolve_equal(first: Path, second: Path) -> bool:
    try:
        return first.resolve(strict=False) == second.resolve(strict=False)
    except OSError:
        return False


def _valid_staged_pdf(
    returned_output: object,
    *,
    staged_output: Path,
    item_workspace: Path,
) -> bool:
    if not isinstance(returned_output, Path):
        return False
    try:
        if returned_output.resolve(strict=False) != staged_output.resolve(strict=False):
            return False
        node = staged_output.lstat()
        if stat.S_ISLNK(node.st_mode) or not stat.S_ISREG(node.st_mode):
            return False
        if not staged_output.resolve(strict=True).is_relative_to(
            item_workspace.resolve(strict=True)
        ):
            return False
        if staged_output.suffix != ".pdf" or node.st_size == 0:
            return False
        with staged_output.open("rb") as stream:
            return stream.read(5) == b"%PDF-"
    except (OSError, RuntimeError, ValueError):
        return False

"""Batch Office-to-PDF model, lifecycle, and trust-boundary coverage."""

import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

import pytest

import docuforge.batch.document as document_module
from docuforge.batch import (
    BatchDocumentConvertRequest,
    BatchDocumentInput,
    BatchDocumentOutput,
    BatchDocumentResult,
    BatchId,
    BatchItemId,
    BatchProcessingError,
    BatchStatus,
    InvalidBatchDefinitionError,
    batch_convert_documents,
)
from docuforge.converters.office import (
    OfficeConversionError,
    OfficeConversionRequest,
    OfficeConversionResult,
)
from docuforge.core import (
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)


class RecordingEngine:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.requests: list[OfficeConversionRequest] = []
        self.error = error

    def convert_to_pdf(self, request: OfficeConversionRequest) -> OfficeConversionResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        source_format = DocumentFormat.normalize(request.input_path.suffix)
        artifact = request.output_directory / f"{request.input_path.stem}.pdf"
        artifact.write_bytes(b"%PDF-1.7\nvalid\n")
        return OfficeConversionResult(request.input_path, artifact, source_format)


def write_office(path: Path) -> None:
    required = {
        ".docx": "word/document.xml",
        ".pptx": "ppt/presentation.xml",
        ".xlsx": "xl/workbook.xml",
    }[path.suffix.lower()]
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(required, "<document/>")


def assert_no_workspace(directory: Path) -> None:
    assert list(directory.glob(".docuforge-batch-documents-*")) == []


def test_document_models_normalize_ids_descriptors_and_are_immutable() -> None:
    item_id = BatchItemId.new()
    item = BatchDocumentInput(Path("private/report.docx"), str(item_id), "  report  ")
    batch_id = BatchId.new()
    request = BatchDocumentConvertRequest((item,), Path("out"), str(batch_id))
    assert item.id == item_id
    assert item.descriptor == "report"
    assert BatchDocumentInput(Path("private/report.docx")).descriptor == "report.docx"
    assert BatchDocumentInput(Path("   ")).descriptor == "document"
    assert request.batch_id == batch_id
    assert not hasattr(item, "__dict__")
    with pytest.raises(FrozenInstanceError):
        item.descriptor = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("descriptor", ["", "  ", 4])
def test_document_input_rejects_bad_descriptors(descriptor: object) -> None:
    with pytest.raises(InvalidBatchDefinitionError):
        BatchDocumentInput(Path("a.docx"), descriptor=descriptor)  # type: ignore[arg-type]


def test_document_request_validates_structure_but_not_source_existence() -> None:
    item = BatchDocumentInput(Path("missing.docx"))
    BatchDocumentConvertRequest((item,), Path("out"))
    with pytest.raises(InvalidBatchDefinitionError):
        BatchDocumentInput("a.docx")  # type: ignore[arg-type]
    with pytest.raises(InvalidBatchDefinitionError):
        BatchDocumentConvertRequest([], Path("out"))  # type: ignore[arg-type]
    with pytest.raises(InvalidBatchDefinitionError):
        BatchDocumentConvertRequest((object(),), Path("out"))  # type: ignore[arg-type]
    with pytest.raises(InvalidBatchDefinitionError):
        BatchDocumentConvertRequest((item,), "out")  # type: ignore[arg-type]
    duplicate = BatchDocumentInput(Path("b.docx"), item.id)
    with pytest.raises(InvalidBatchDefinitionError):
        BatchDocumentConvertRequest((item, duplicate), Path("out"))


def test_heterogeneous_batch_routes_in_order_with_stable_names(tmp_path: Path) -> None:
    sources = [
        tmp_path / "report.DOCX",
        tmp_path / "slides deck.pptx",
        tmp_path / "résumé.xlsx",
    ]
    for source in sources:
        write_office(source)
    output = tmp_path / "output"
    output.mkdir()
    engine = RecordingEngine()
    batch_id = BatchId.new()
    items = tuple(BatchDocumentInput(source) for source in sources)

    result = batch_convert_documents(
        BatchDocumentConvertRequest(items, output, batch_id), engine=engine
    )

    assert result.batch.id == batch_id
    assert result.batch.operation == "office.to_pdf"
    assert result.batch.status is BatchStatus.COMPLETED
    assert [item.id for item in result.batch.items] == [item.id for item in items]
    assert [request.input_path for request in engine.requests] == sources
    assert [entry.source_format for entry in result.outputs] == [
        DocumentFormat.DOCX,
        DocumentFormat.PPTX,
        DocumentFormat.XLSX,
    ]
    assert [entry.output_path.name for entry in result.outputs] == [
        "0001-report.pdf",
        "0002-slides deck.pdf",
        "0003-résumé.pdf",
    ]
    assert all(entry.output_path.read_bytes().startswith(b"%PDF-") for entry in result.outputs)
    assert_no_workspace(output)


def test_duplicate_source_names_are_disambiguated_and_success_replaces(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    sources = (first_dir / "same.docx", second_dir / "same.docx")
    for source in sources:
        write_office(source)
    output = tmp_path / "output"
    output.mkdir()
    destination = output / "0001-same.pdf"
    destination.write_bytes(b"old")
    result = batch_convert_documents(
        BatchDocumentConvertRequest(tuple(map(BatchDocumentInput, sources)), output),
        engine=RecordingEngine(),
    )
    assert [entry.output_path.name for entry in result.outputs] == [
        "0001-same.pdf",
        "0002-same.pdf",
    ]
    assert destination.read_bytes() != b"old"
    assert all(source.exists() for source in sources)


def test_partial_batch_continues_and_all_failed_is_a_result(tmp_path: Path) -> None:
    good = tmp_path / "good.docx"
    write_office(good)
    malformed = tmp_path / "bad.pptx"
    malformed.write_bytes(b"not OOXML")
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("text")
    output = tmp_path / "output"
    output.mkdir()
    result = batch_convert_documents(
        BatchDocumentConvertRequest(
            tuple(
                BatchDocumentInput(path)
                for path in (tmp_path / "missing.xlsx", good, malformed, unsupported)
            ),
            output,
        ),
        engine=RecordingEngine(),
    )
    assert result.batch.status is BatchStatus.PARTIAL
    assert [entry.position for entry in result.outputs] == [1]
    assert result.outputs[0].output_path.name == "0002-good.pdf"
    assert [item.failure.code if item.failure else None for item in result.batch.items] == [
        "invalid_document_request",
        None,
        "invalid_document_request",
        "unsupported_document_format",
    ]
    assert str(tmp_path) not in result.batch.items[0].failure.message

    failed = batch_convert_documents(
        BatchDocumentConvertRequest(
            (BatchDocumentInput(tmp_path / "missing.docx"), BatchDocumentInput(unsupported)),
            output,
        ),
        engine=RecordingEngine(),
    )
    assert failed.batch.status is BatchStatus.FAILED
    assert failed.outputs == ()
    assert_no_workspace(output)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (InvalidConversionRequestError("private"), "invalid_document_request"),
        (UnsupportedConversionError("private"), "unsupported_document_format"),
        (OfficeConversionError("private"), "document_processing_failed"),
    ],
)
def test_expected_converter_errors_are_safe_and_isolated(
    tmp_path: Path, error: Exception, code: str
) -> None:
    first = tmp_path / "first.docx"
    second = tmp_path / "second.docx"
    write_office(first)
    write_office(second)
    output = tmp_path / "output"
    output.mkdir()
    real = document_module.convert_docx_to_pdf
    calls = 0

    def converter(request: object, *, engine: object) -> Path:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error
        return real(request, engine=engine)  # type: ignore[arg-type]

    with patch.object(document_module, "convert_docx_to_pdf", side_effect=converter):
        result = batch_convert_documents(
            BatchDocumentConvertRequest(
                (BatchDocumentInput(first), BatchDocumentInput(second)), output
            ),
            engine=RecordingEngine(),
        )
    assert result.batch.status is BatchStatus.PARTIAL
    assert result.batch.items[0].failure.code == code
    assert "private" not in result.batch.items[0].failure.message
    assert result.outputs[0].position == 1


@pytest.mark.parametrize("case", ["wrong-type", "outside", "missing", "directory", "empty", "bad-signature"])
def test_invalid_staged_outputs_are_rejected(tmp_path: Path, case: str) -> None:
    source = tmp_path / "source.docx"
    write_office(source)
    output = tmp_path / "output"
    output.mkdir()
    old = output / "0001-source.pdf"
    old.write_bytes(b"OLD")

    def converter(request: object, *, engine: object) -> object:
        staged = request.output_path  # type: ignore[attr-defined]
        if case == "wrong-type":
            return object()
        if case == "outside":
            outside = tmp_path / "outside.pdf"
            outside.write_bytes(b"%PDF-outside")
            return outside
        if case == "directory":
            staged.mkdir()
        elif case == "empty":
            staged.write_bytes(b"")
        elif case == "bad-signature":
            staged.write_bytes(b"not a pdf")
        return staged

    with patch.object(document_module, "convert_docx_to_pdf", side_effect=converter):
        result = batch_convert_documents(
            BatchDocumentConvertRequest((BatchDocumentInput(source),), output),
            engine=RecordingEngine(),
        )
    assert result.batch.status is BatchStatus.FAILED
    assert result.batch.items[0].failure.code == "invalid_document_output"
    assert old.read_bytes() == b"OLD"
    assert_no_workspace(output)


@pytest.mark.parametrize("outside", [False, True])
def test_staged_symlink_is_rejected(tmp_path: Path, outside: bool) -> None:
    source = tmp_path / "source.docx"
    write_office(source)
    output = tmp_path / "output"
    output.mkdir()

    def converter(request: object, *, engine: object) -> Path:
        staged = request.output_path  # type: ignore[attr-defined]
        target = (tmp_path if outside else staged.parent) / "target.pdf"
        target.write_bytes(b"%PDF-valid")
        try:
            staged.symlink_to(target)
        except OSError:
            pytest.skip("symlink creation is not available")
        return staged

    with patch.object(document_module, "convert_docx_to_pdf", side_effect=converter):
        result = batch_convert_documents(
            BatchDocumentConvertRequest((BatchDocumentInput(source),), output),
            engine=RecordingEngine(),
        )
    assert result.batch.items[0].failure.code == "invalid_document_output"
    assert_no_workspace(output)


def test_publication_failure_preserves_destination_and_continues(tmp_path: Path) -> None:
    sources = (tmp_path / "first.docx", tmp_path / "second.docx")
    for source in sources:
        write_office(source)
    output = tmp_path / "output"
    output.mkdir()
    old = output / "0001-first.pdf"
    old.write_bytes(b"OLD")
    real_replace = os.replace

    def replace(source: Path, destination: Path) -> None:
        if Path(destination) == old:
            raise OSError("private")
        real_replace(source, destination)

    with patch.object(document_module.os, "replace", side_effect=replace):
        result = batch_convert_documents(
            BatchDocumentConvertRequest(tuple(map(BatchDocumentInput, sources)), output),
            engine=RecordingEngine(),
        )
    assert result.batch.status is BatchStatus.PARTIAL
    assert result.batch.items[0].failure.code == "document_output_publish_failed"
    assert result.outputs[0].position == 1
    assert old.read_bytes() == b"OLD"


def test_source_collision_is_rejected_without_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "first.docx"
    write_office(source)
    output = tmp_path / "output"
    output.mkdir()
    collision = output / "0001-first.pdf"
    collision.write_bytes(b"SOURCE")
    result = batch_convert_documents(
        BatchDocumentConvertRequest(
            (BatchDocumentInput(source), BatchDocumentInput(collision)),
            output,
        ),
        engine=RecordingEngine(),
    )
    assert result.batch.status is BatchStatus.FAILED
    assert result.batch.items[0].failure.code == "invalid_document_request"
    assert result.batch.items[1].failure.code == "unsupported_document_format"
    assert collision.read_bytes() == b"SOURCE"


def test_global_validation_and_workspace_failures(tmp_path: Path) -> None:
    request = BatchDocumentConvertRequest(
        (BatchDocumentInput(tmp_path / "source.docx"),), tmp_path / "missing"
    )
    with pytest.raises(InvalidBatchDefinitionError):
        batch_convert_documents(request, engine=RecordingEngine())
    output = tmp_path / "output"
    output.mkdir()
    request = BatchDocumentConvertRequest(request.items, output)
    with (
        patch.object(document_module, "TemporaryDirectory", side_effect=OSError("private")),
        pytest.raises(BatchProcessingError, match="Unable to process the document batch"),
    ):
        batch_convert_documents(request, engine=RecordingEngine())
    with pytest.raises(TypeError):
        batch_convert_documents(request, engine=object())  # type: ignore[arg-type]


def test_cleanup_failure_maps_to_safe_batch_error(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    request = BatchDocumentConvertRequest(
        (BatchDocumentInput(tmp_path / "missing.docx"),), output
    )

    class FailingCleanup:
        def __init__(self, **kwargs: object) -> None:
            self._temporary = TemporaryDirectory(**kwargs)  # type: ignore[arg-type]
            self.name = self._temporary.name

        def cleanup(self) -> None:
            self._temporary.cleanup()
            raise OSError("private")

    with (
        patch.object(document_module, "TemporaryDirectory", FailingCleanup),
        pytest.raises(BatchProcessingError, match="Unable to process the document batch"),
    ):
        batch_convert_documents(request, engine=RecordingEngine())
    assert_no_workspace(output)


def test_unexpected_converter_error_propagates_and_workspace_is_cleaned(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    write_office(source)
    output = tmp_path / "output"
    output.mkdir()
    with (
        patch.object(document_module, "convert_docx_to_pdf", side_effect=RuntimeError("bug")),
        pytest.raises(RuntimeError, match="bug"),
    ):
        batch_convert_documents(
            BatchDocumentConvertRequest((BatchDocumentInput(source),), output),
            engine=RecordingEngine(),
        )
    assert_no_workspace(output)


def test_document_output_and_result_validate_invariants(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    write_office(source)
    output = tmp_path / "output"
    output.mkdir()
    result = batch_convert_documents(
        BatchDocumentConvertRequest((BatchDocumentInput(source),), output),
        engine=RecordingEngine(),
    )
    value = result.outputs[0]
    assert value.target_format is DocumentFormat.PDF
    with pytest.raises(FrozenInstanceError):
        value.position = 2  # type: ignore[misc]
    with pytest.raises(InvalidBatchDefinitionError):
        BatchDocumentOutput(
            value.item_id,
            -1,
            value.input_path,
            value.output_path,
            value.source_format,
        )
    with pytest.raises(InvalidBatchDefinitionError):
        BatchDocumentResult(result.batch, output, ())

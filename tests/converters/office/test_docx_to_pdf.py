"""Tests for the concrete DOCX-to-PDF workflow."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import cast

import pytest

import docuforge.converters.office.docx_to_pdf as docx_module
from docuforge.converters import (
    DocxToPdfConverter,
    DocxToPdfRequest,
    convert_docx_to_pdf,
)
from docuforge.converters.office import (
    OfficeConversionError,
    OfficeConversionRequest,
    OfficeConversionResult,
)
from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    ConverterNotFoundError,
    ConverterRegistry,
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)

EngineHandler = Callable[[OfficeConversionRequest], object]


class FakeOfficeEngine:
    """Configurable engine fake that records workflow isolation boundaries."""

    def __init__(self, handler: EngineHandler | None = None) -> None:
        self.handler = handler
        self.calls: list[OfficeConversionRequest] = []
        self.workspaces: list[Path] = []

    def convert_to_pdf(self, request: OfficeConversionRequest) -> OfficeConversionResult:
        self.calls.append(request)
        self.workspaces.append(request.output_directory)
        if self.handler is not None:
            return cast(OfficeConversionResult, self.handler(request))
        output_path = request.output_directory / f"{request.input_path.stem}.pdf"
        output_path.write_bytes(b"%PDF-1.7\nconverted DOCX")
        return OfficeConversionResult(
            input_path=request.input_path,
            output_path=output_path,
            source_format=DocumentFormat.DOCX,
        )


def make_request(
    tmp_path: Path,
    *,
    input_name: str = "source.docx",
    output_name: str = "result.pdf",
) -> DocxToPdfRequest:
    input_path = tmp_path / input_name
    input_path.write_bytes(b"DOCX fixture")
    return DocxToPdfRequest(input_path, tmp_path / output_name)


def mutate_result(result: OfficeConversionResult, field: str, value: object) -> object:
    object.__setattr__(result, field, value)
    return result


def test_request_has_intrinsic_single_docx_to_pdf_identity() -> None:
    input_path = Path("source.docx")
    output_path = Path("custom.pdf")

    request = DocxToPdfRequest(input_path, output_path)

    assert request.input_paths == (input_path,)
    assert request.input_path == input_path
    assert request.output_path == output_path
    assert request.source_format is DocumentFormat.DOCX
    assert request.target_format is DocumentFormat.PDF
    assert request.operation is ConversionOperation.CONVERT
    with pytest.raises(FrozenInstanceError):
        request.output_path = Path("other.pdf")  # type: ignore[misc]


def test_converter_identity_and_injected_engine() -> None:
    engine = FakeOfficeEngine()
    converter = DocxToPdfConverter(engine)

    assert converter.operation is ConversionOperation.CONVERT
    assert converter.source_format is DocumentFormat.DOCX
    assert converter.target_format is DocumentFormat.PDF


def test_converter_rejects_object_without_engine_contract() -> None:
    with pytest.raises(TypeError, match="OfficeConversionEngine"):
        DocxToPdfConverter(object())  # type: ignore[arg-type]


def test_success_uses_isolated_workspace_and_exact_custom_destination(tmp_path: Path) -> None:
    request = make_request(
        tmp_path,
        input_name="résumé draft.docx",
        output_name="final client résumé.pdf",
    )
    engine = FakeOfficeEngine()

    result = DocxToPdfConverter(engine).convert(request)

    assert result == request.output_path
    assert result.read_bytes() == b"%PDF-1.7\nconverted DOCX"
    assert len(engine.calls) == 1
    assert engine.calls[0].input_path == request.input_path
    assert engine.workspaces[0].parent == request.output_path.parent
    assert engine.workspaces[0].name.startswith(".docuforge-docx-")
    assert not engine.workspaces[0].exists()


def test_public_helper_delegates_through_injected_engine(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    engine = FakeOfficeEngine()

    assert convert_docx_to_pdf(request, engine=engine) == request.output_path
    assert len(engine.calls) == 1


@pytest.mark.parametrize("suffix", [".doc", ".pptx", ".xlsx", ".txt"])
def test_non_docx_source_suffixes_are_rejected(tmp_path: Path, suffix: str) -> None:
    request = make_request(tmp_path, input_name=f"source{suffix}")
    engine = FakeOfficeEngine()

    with pytest.raises(InvalidConversionRequestError, match=".docx"):
        DocxToPdfConverter(engine).convert(request)

    assert engine.calls == []


def test_uppercase_docx_and_pdf_suffixes_are_accepted(tmp_path: Path) -> None:
    request = make_request(tmp_path, input_name="SOURCE.DOCX", output_name="RESULT.PDF")

    assert DocxToPdfConverter(FakeOfficeEngine()).convert(request) == request.output_path


def test_missing_source_is_rejected_before_engine_call(tmp_path: Path) -> None:
    request = DocxToPdfRequest(tmp_path / "missing.docx", tmp_path / "result.pdf")
    engine = FakeOfficeEngine()

    with pytest.raises(InvalidConversionRequestError, match="does not exist"):
        DocxToPdfConverter(engine).convert(request)

    assert engine.calls == []


def test_directory_source_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    source.mkdir()

    with pytest.raises(InvalidConversionRequestError, match="not a file"):
        DocxToPdfConverter(FakeOfficeEngine()).convert(
            DocxToPdfRequest(source, tmp_path / "result.pdf")
        )


def test_missing_output_parent_is_rejected(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    request = DocxToPdfRequest(request.input_path, tmp_path / "missing" / "result.pdf")

    with pytest.raises(InvalidConversionRequestError, match="existing directory"):
        DocxToPdfConverter(FakeOfficeEngine()).convert(request)


def test_output_parent_file_is_rejected(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    parent_file = tmp_path / "parent"
    parent_file.write_text("not a directory")

    with pytest.raises(InvalidConversionRequestError, match="existing directory"):
        DocxToPdfConverter(FakeOfficeEngine()).convert(
            DocxToPdfRequest(request.input_path, parent_file / "result.pdf")
        )


def test_directory_output_is_rejected(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    output = tmp_path / "directory.pdf"
    output.mkdir()

    with pytest.raises(InvalidConversionRequestError, match="is a directory"):
        DocxToPdfConverter(FakeOfficeEngine()).convert(DocxToPdfRequest(request.input_path, output))


@pytest.mark.parametrize("output_name", ["result", "result.docx", "result.png"])
def test_non_pdf_output_suffix_is_rejected(tmp_path: Path, output_name: str) -> None:
    request = make_request(tmp_path, output_name=output_name)

    with pytest.raises(InvalidConversionRequestError, match=".pdf"):
        DocxToPdfConverter(FakeOfficeEngine()).convert(request)


def test_same_filesystem_object_is_rejected(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    linked_output = tmp_path / "linked.pdf"
    try:
        os.link(request.input_path, linked_output)
    except OSError:
        pytest.skip("hard links are unavailable")

    with pytest.raises(InvalidConversionRequestError, match="different files"):
        DocxToPdfConverter(FakeOfficeEngine()).convert(
            DocxToPdfRequest(request.input_path, linked_output)
        )


def test_wrong_request_type_and_generic_request_are_rejected(tmp_path: Path) -> None:
    converter = DocxToPdfConverter(FakeOfficeEngine())
    with pytest.raises(TypeError):
        converter.convert(object())  # type: ignore[arg-type]

    source = tmp_path / "source.docx"
    source.write_bytes(b"fixture")
    generic = ConversionRequest(
        input_paths=(source,),
        output_path=tmp_path / "result.pdf",
        source_format=DocumentFormat.DOCX,
        target_format=DocumentFormat.PDF,
    )
    with pytest.raises(InvalidConversionRequestError, match="DocxToPdfRequest"):
        converter.convert(generic)



@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operation", ConversionOperation.MERGE),
        ("source_format", DocumentFormat.PPTX),
        ("target_format", DocumentFormat.PNG),
    ],
)
def test_wrong_request_identity_is_rejected(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    wrong_identity = make_request(tmp_path)
    object.__setattr__(wrong_identity, field, value)

    with pytest.raises(UnsupportedConversionError):
        DocxToPdfConverter(FakeOfficeEngine()).convert(wrong_identity)


def test_request_with_more_than_one_input_is_rejected(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    object.__setattr__(request, "input_paths", (request.input_path, request.input_path))

    with pytest.raises(InvalidConversionRequestError, match="exactly one"):
        DocxToPdfConverter(FakeOfficeEngine()).convert(request)


def engine_result(
    request: OfficeConversionRequest,
    *,
    input_path: Path | None = None,
    output_path: Path | None = None,
) -> OfficeConversionResult:
    result_path = output_path or request.output_directory / "source.pdf"
    if not result_path.exists():
        result_path.write_bytes(b"%PDF-1.7\nengine output")
    return OfficeConversionResult(
        input_path=input_path or request.input_path,
        output_path=result_path,
        source_format=DocumentFormat.DOCX,
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_format", DocumentFormat.PPTX, "format"),
        ("target_format", DocumentFormat.PNG, "format"),
    ],
)
def test_wrong_engine_format_identity_is_rejected(
    tmp_path: Path,
    field: str,
    value: DocumentFormat,
    message: str,
) -> None:
    request = make_request(tmp_path)

    def wrong_format(engine_request: OfficeConversionRequest) -> object:
        return mutate_result(engine_result(engine_request), field, value)

    with pytest.raises(OfficeConversionError, match=message):
        DocxToPdfConverter(FakeOfficeEngine(wrong_format)).convert(request)


def test_wrong_engine_input_path_is_rejected(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    other = tmp_path / "other.docx"
    other.write_bytes(b"other")

    with pytest.raises(OfficeConversionError, match="input path"):
        DocxToPdfConverter(
            FakeOfficeEngine(lambda engine_request: engine_result(engine_request, input_path=other))
        ).convert(request)


def test_non_result_object_is_rejected(tmp_path: Path) -> None:
    request = make_request(tmp_path)

    with pytest.raises(OfficeConversionError, match="invalid conversion result"):
        DocxToPdfConverter(FakeOfficeEngine(lambda _: object())).convert(request)


def test_output_outside_workspace_is_rejected_and_preserved(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    request.output_path.write_bytes(b"%PDF-1.7\nexisting")
    outside = tmp_path / "outside.pdf"

    with pytest.raises(OfficeConversionError, match="outside"):
        DocxToPdfConverter(
            FakeOfficeEngine(
                lambda engine_request: engine_result(engine_request, output_path=outside)
            )
        ).convert(request)

    assert request.output_path.read_bytes() == b"%PDF-1.7\nexisting"


def test_symlink_to_output_outside_workspace_is_rejected(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.7\noutside")

    def symlink_result(engine_request: OfficeConversionRequest) -> OfficeConversionResult:
        link = engine_request.output_directory / "linked.pdf"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("file symlinks are unavailable")
        return engine_result(engine_request, output_path=link)

    with pytest.raises(OfficeConversionError, match="outside"):
        DocxToPdfConverter(FakeOfficeEngine(symlink_result)).convert(request)


def test_missing_engine_artifact_is_rejected(tmp_path: Path) -> None:
    request = make_request(tmp_path)

    def missing(engine_request: OfficeConversionRequest) -> OfficeConversionResult:
        return OfficeConversionResult(
            input_path=engine_request.input_path,
            output_path=engine_request.output_directory / "missing.pdf",
            source_format=DocumentFormat.DOCX,
        )

    with pytest.raises(OfficeConversionError, match="usable PDF"):
        DocxToPdfConverter(FakeOfficeEngine(missing)).convert(request)


def test_engine_directory_artifact_is_rejected(tmp_path: Path) -> None:
    request = make_request(tmp_path)

    def directory(engine_request: OfficeConversionRequest) -> OfficeConversionResult:
        output = engine_request.output_directory / "source.pdf"
        output.mkdir()
        return OfficeConversionResult(
            input_path=engine_request.input_path,
            output_path=output,
            source_format=DocumentFormat.DOCX,
        )

    with pytest.raises(OfficeConversionError, match="usable PDF"):
        DocxToPdfConverter(FakeOfficeEngine(directory)).convert(request)


def test_success_atomically_replaces_existing_destination(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    request.output_path.write_bytes(b"%PDF-1.7\nexisting")

    DocxToPdfConverter(FakeOfficeEngine()).convert(request)

    assert request.output_path.read_bytes() == b"%PDF-1.7\nconverted DOCX"


def test_engine_failure_preserves_destination_and_cleans_workspace(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    request.output_path.write_bytes(b"%PDF-1.7\nexisting")

    def fail(_: OfficeConversionRequest) -> object:
        raise OfficeConversionError("engine failed")

    engine = FakeOfficeEngine(fail)
    with pytest.raises(OfficeConversionError, match="engine failed"):
        DocxToPdfConverter(engine).convert(request)

    assert request.output_path.read_bytes() == b"%PDF-1.7\nexisting"
    assert not engine.workspaces[0].exists()


def test_invalid_result_preserves_destination_and_cleans_workspace(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    request.output_path.write_bytes(b"%PDF-1.7\nexisting")
    engine = FakeOfficeEngine(lambda _: object())

    with pytest.raises(OfficeConversionError):
        DocxToPdfConverter(engine).convert(request)

    assert request.output_path.read_bytes() == b"%PDF-1.7\nexisting"
    assert not engine.workspaces[0].exists()


def test_publication_failure_is_safe_and_preserves_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = make_request(tmp_path)
    existing = b"%PDF-1.7\nexisting"
    request.output_path.write_bytes(existing)
    engine = FakeOfficeEngine()
    secret = "private operating system details"

    def fail_publication(source: Path, destination: Path) -> None:
        raise OSError(secret)

    monkeypatch.setattr(docx_module.os, "replace", fail_publication)
    with pytest.raises(OfficeConversionError) as raised:
        DocxToPdfConverter(engine).convert(request)

    assert secret not in str(raised.value)
    assert request.output_path.read_bytes() == existing
    assert not engine.workspaces[0].exists()


def test_registry_registers_and_resolves_without_global_state(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    converter = DocxToPdfConverter(FakeOfficeEngine())
    registry = ConverterRegistry()

    registry.register(converter)

    assert registry.get_converter_for(request) is converter
    assert (
        registry.get_converter(
            ConversionOperation.CONVERT,
            DocumentFormat.DOCX,
            DocumentFormat.PDF,
        )
        is converter
    )
    with pytest.raises(ConverterNotFoundError):
        registry.get_converter(
            ConversionOperation.CONVERT,
            DocumentFormat.PPTX,
            DocumentFormat.PDF,
        )

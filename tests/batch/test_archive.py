"""Reusable atomic batch ZIP packaging coverage."""

import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import docuforge.batch.archive as archive_module
from docuforge.batch import (
    Batch,
    BatchArchiveResult,
    BatchDocumentConvertRequest,
    BatchDocumentInput,
    BatchId,
    BatchImageOutput,
    BatchImageResult,
    BatchItemFailure,
    BatchItemId,
    BatchItemRequest,
    BatchItemResult,
    BatchProcessingError,
    BatchRequest,
    InvalidBatchDefinitionError,
    package_batch_outputs,
)
from docuforge.converters.office import OfficeConversionRequest, OfficeConversionResult
from docuforge.core import DocumentFormat
from docuforge.jobs import OperationKey


def image_result(
    output_directory: Path,
    names: tuple[str | None, ...] = ("0001-a.png",),
) -> BatchImageResult:
    identities = tuple(BatchItemId.new() for _ in names)
    batch = Batch(
        BatchRequest(
            BatchId.new(),
            OperationKey("image.convert"),
            tuple(
                BatchItemRequest(identity, position, f"input-{position}.png")
                for position, identity in enumerate(identities)
            ),
        )
    )
    outputs = []
    for position, (identity, name) in enumerate(zip(identities, names, strict=True)):
        if name is None:
            batch = batch.fail_item(identity, BatchItemFailure("failed", "Failed safely."))
            continue
        path = output_directory / name
        path.write_bytes(f"image-{position}".encode())
        batch = batch.start_item(identity).complete_item(identity, BatchItemResult(name))
        outputs.append(
            BatchImageOutput(
                identity,
                position,
                Path(f"input-{position}.png"),
                path,
                DocumentFormat.PNG,
                DocumentFormat.PNG,
            )
        )
    return BatchImageResult(batch, output_directory, tuple(outputs))


class PdfEngine:
    def convert_to_pdf(self, request: OfficeConversionRequest) -> OfficeConversionResult:
        artifact = request.output_directory / "rendered.pdf"
        artifact.write_bytes(b"%PDF-1.7\n")
        return OfficeConversionResult(request.input_path, artifact, request.input_path.suffix)


def write_docx(path: Path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")


def assert_no_workspace(directory: Path) -> None:
    assert list(directory.glob(".docuforge-batch-archive-*")) == []


def test_archive_result_is_validated_frozen_and_slotted() -> None:
    valid_names = ("0001-report.pdf", "0003-雪 image.png", "résumé.pdf")
    result = BatchArchiveResult(Path("batch.zip"), valid_names)
    assert result.member_names == valid_names
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.archive_path = Path("other.zip")  # type: ignore[misc]
    for names in (
        (),
        ("../a.pdf",),
        ("nested/a.pdf",),
        (str(Path.cwd() / "a.pdf"),),
        ("..\\evil.pdf",),
        ("nested\\evil.pdf",),
        ("C:\\evil.pdf",),
        ("C:evil.pdf",),
        ("\\evil.pdf",),
        ("\\\\server\\share\\evil.pdf",),
        ("a.pdf", "a.pdf"),
    ):
        with pytest.raises(InvalidBatchDefinitionError):
            BatchArchiveResult(Path("batch.zip"), names)


def test_packaging_uses_the_same_member_safety_predicate(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    result = image_result(output)
    with (
        patch.object(archive_module, "_safe_member_name", return_value=False) as safety_check,
        pytest.raises(InvalidBatchDefinitionError, match="safe basenames"),
    ):
        package_batch_outputs(result, tmp_path / "archive.zip")
    safety_check.assert_called_once_with("0001-a.png")


def test_packages_image_outputs_in_exact_partial_order(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    batch = image_result(output, ("0001-a.png", None, "0003-雪 image.png"))
    archive_path = tmp_path / "result.zip"
    result = package_batch_outputs(batch, archive_path)
    assert result.archive_path == archive_path
    assert result.member_names == ("0001-a.png", "0003-雪 image.png")
    with ZipFile(archive_path) as archive:
        assert tuple(archive.namelist()) == result.member_names
        assert archive.testzip() is None
        assert archive.read("0001-a.png") == b"image-0"
    assert_no_workspace(tmp_path)


def test_packages_document_outputs(tmp_path: Path) -> None:
    source = tmp_path / "report.docx"
    write_docx(source)
    output = tmp_path / "output"
    output.mkdir()
    from docuforge.batch import batch_convert_documents

    document_result = batch_convert_documents(
        BatchDocumentConvertRequest((BatchDocumentInput(source),), output), engine=PdfEngine()
    )
    archive_path = tmp_path / "documents.zip"
    result = package_batch_outputs(document_result, archive_path)
    assert result.member_names == ("0001-report.pdf",)
    with ZipFile(archive_path) as archive:
        assert archive.read("0001-report.pdf").startswith(b"%PDF-")


def test_all_failed_and_invalid_destinations_are_definition_errors(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    failed = image_result(output, (None,))
    with pytest.raises(InvalidBatchDefinitionError):
        package_batch_outputs(failed, tmp_path / "empty.zip")
    successful = image_result(output)
    for destination in (
        tmp_path / "archive.ZIP",
        tmp_path / "archive.tar",
        tmp_path / "missing" / "archive.zip",
    ):
        with pytest.raises(InvalidBatchDefinitionError):
            package_batch_outputs(successful, destination)
    directory = tmp_path / "directory.zip"
    directory.mkdir()
    with pytest.raises(InvalidBatchDefinitionError):
        package_batch_outputs(successful, directory)
    with pytest.raises(InvalidBatchDefinitionError):
        package_batch_outputs(successful, "archive.zip")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        package_batch_outputs(object(), tmp_path / "archive.zip")  # type: ignore[arg-type]


@pytest.mark.parametrize("case", ["missing", "directory", "outside", "metadata"])
def test_revalidates_mutable_output_state(tmp_path: Path, case: str) -> None:
    output = tmp_path / "output"
    output.mkdir()
    result = image_result(output)
    path = result.outputs[0].output_path
    if case == "missing":
        path.unlink()
    elif case == "directory":
        path.unlink()
        path.mkdir()
    elif case == "outside":
        outside = tmp_path / path.name
        outside.write_bytes(b"outside")
        object.__setattr__(result.outputs[0], "output_path", outside)
    else:
        replacement = output / "renamed.png"
        replacement.write_bytes(b"replacement")
        object.__setattr__(result.outputs[0], "output_path", replacement)
    with pytest.raises(BatchProcessingError, match="Unable to package the batch outputs"):
        package_batch_outputs(result, tmp_path / "archive.zip")
    assert not (tmp_path / "archive.zip").exists()
    assert_no_workspace(tmp_path)


def test_rejects_symlink_output(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    result = image_result(output)
    path = result.outputs[0].output_path
    path.unlink()
    target = tmp_path / "outside.png"
    target.write_bytes(b"outside")
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not available")
    with pytest.raises(BatchProcessingError):
        package_batch_outputs(result, tmp_path / "archive.zip")
    assert_no_workspace(tmp_path)


def test_rejects_duplicate_members_and_archive_output_collision(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    duplicate = image_result(output, ("same.png", "same.png"))
    with pytest.raises(InvalidBatchDefinitionError, match="unique"):
        package_batch_outputs(duplicate, tmp_path / "archive.zip")

    collision_path = output / "member.zip"
    collision = image_result(output, ("member.zip",))
    with pytest.raises(InvalidBatchDefinitionError, match="must not replace"):
        package_batch_outputs(collision, collision_path)


def test_existing_archive_is_preserved_on_creation_or_validation_failure(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    result = image_result(output)
    destination = tmp_path / "archive.zip"
    destination.write_bytes(b"OLD ARCHIVE")
    with (
        patch.object(archive_module, "ZipFile", side_effect=OSError("private")),
        pytest.raises(BatchProcessingError),
    ):
        package_batch_outputs(result, destination)
    assert destination.read_bytes() == b"OLD ARCHIVE"
    assert_no_workspace(tmp_path)
    with (
        patch.object(archive_module, "_valid_staged_archive", return_value=False),
        pytest.raises(BatchProcessingError),
    ):
        package_batch_outputs(result, destination)
    assert destination.read_bytes() == b"OLD ARCHIVE"
    assert_no_workspace(tmp_path)


def test_publication_failure_is_safe_and_success_replaces(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    result = image_result(output)
    destination = tmp_path / "archive.zip"
    destination.write_bytes(b"OLD")
    real_replace = os.replace

    def replace(source: Path, target: Path) -> None:
        if Path(target) == destination:
            raise OSError("private")
        real_replace(source, target)

    with (
        patch.object(archive_module.os, "replace", side_effect=replace),
        pytest.raises(BatchProcessingError),
    ):
        package_batch_outputs(result, destination)
    assert destination.read_bytes() == b"OLD"
    assert_no_workspace(tmp_path)
    packaged = package_batch_outputs(result, destination)
    assert destination.read_bytes() != b"OLD"
    assert packaged.member_names == ("0001-a.png",)


def test_staged_archive_validation_checks_sequence_duplicates_and_integrity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    staged = workspace / "archive.zip"
    with ZipFile(staged, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("a.txt", "a")
        archive.writestr("b.txt", "b")
    assert archive_module._valid_staged_archive(
        staged, workspace=workspace, expected_names=("a.txt", "b.txt")
    )
    assert not archive_module._valid_staged_archive(
        staged, workspace=workspace, expected_names=("b.txt", "a.txt")
    )
    staged.write_bytes(b"not a zip")
    assert not archive_module._valid_staged_archive(
        staged, workspace=workspace, expected_names=("a.txt", "b.txt")
    )


def test_staged_archive_validation_honors_testzip(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    staged = workspace / "archive.zip"
    with ZipFile(staged, "w") as archive:
        archive.writestr("a.txt", "a")
    real_zip_file = ZipFile

    class FailedIntegrityZip:
        def __init__(self, path: Path, mode: str) -> None:
            self._archive = real_zip_file(path, mode)

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            self._archive.close()

        def namelist(self) -> list[str]:
            return self._archive.namelist()

        def testzip(self) -> str:
            return "a.txt"

    with patch.object(archive_module, "ZipFile", FailedIntegrityZip):
        assert not archive_module._valid_staged_archive(
            staged, workspace=workspace, expected_names=("a.txt",)
        )


def test_workspace_failure_maps_safely_and_unexpected_errors_propagate(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    result = image_result(output)
    destination = tmp_path / "archive.zip"
    with (
        patch.object(archive_module, "TemporaryDirectory", side_effect=OSError("private")),
        pytest.raises(BatchProcessingError, match="Unable to package the batch outputs"),
    ):
        package_batch_outputs(result, destination)
    with (
        patch.object(archive_module, "ZipFile", side_effect=RuntimeError("bug")),
        pytest.raises(RuntimeError, match="bug"),
    ):
        package_batch_outputs(result, destination)
    assert_no_workspace(tmp_path)


def test_archive_cleanup_failure_maps_to_safe_batch_error(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    result = image_result(output)

    class FailingCleanup:
        def __init__(self, **kwargs: object) -> None:
            self._temporary = TemporaryDirectory(**kwargs)  # type: ignore[arg-type]
            self.name = self._temporary.name

        def cleanup(self) -> None:
            self._temporary.cleanup()
            raise OSError("private")

    with (
        patch.object(archive_module, "TemporaryDirectory", FailingCleanup),
        pytest.raises(BatchProcessingError, match="Unable to package the batch outputs"),
    ):
        package_batch_outputs(result, tmp_path / "archive.zip")
    assert_no_workspace(tmp_path)

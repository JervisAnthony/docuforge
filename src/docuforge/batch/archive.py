"""Safe atomic ZIP packaging for successful batch outputs."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, BadZipFile, LargeZipFile, ZipFile

from docuforge.batch.document import BatchDocumentResult
from docuforge.batch.exceptions import BatchProcessingError, InvalidBatchDefinitionError
from docuforge.batch.image import BatchImageResult
from docuforge.batch.models import BatchItemStatus


@dataclass(frozen=True, slots=True)
class BatchArchiveResult:
    """Published archive path and its exact ordered member names."""

    archive_path: Path
    member_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.archive_path, Path):
            raise InvalidBatchDefinitionError("Batch archive path must be a Path.")
        if not isinstance(self.member_names, tuple) or not self.member_names:
            raise InvalidBatchDefinitionError("Batch archive members must be a nonempty tuple.")
        if any(not _safe_member_name(name) for name in self.member_names):
            raise InvalidBatchDefinitionError("Batch archive member names must be safe basenames.")
        if len(set(self.member_names)) != len(self.member_names):
            raise InvalidBatchDefinitionError("Batch archive member names must be unique.")


def package_batch_outputs(
    result: BatchImageResult | BatchDocumentResult,
    archive_path: Path,
) -> BatchArchiveResult:
    """Atomically package successful image or document batch outputs."""
    if not isinstance(result, (BatchImageResult, BatchDocumentResult)):
        raise TypeError("result must be a BatchImageResult or BatchDocumentResult")
    if not isinstance(archive_path, Path):
        raise InvalidBatchDefinitionError("Batch archive path must be a Path.")
    if archive_path.suffix != ".zip":
        raise InvalidBatchDefinitionError("Batch archive path must use the .zip suffix.")
    if not result.outputs:
        raise InvalidBatchDefinitionError("A batch archive requires successful outputs.")
    _validate_archive_parent(archive_path)
    _validate_outputs(result)
    member_names = tuple(output.output_path.name for output in result.outputs)
    if any(not _safe_member_name(name) for name in member_names):
        raise InvalidBatchDefinitionError("Batch archive member names must be safe basenames.")
    if len(set(member_names)) != len(member_names):
        raise InvalidBatchDefinitionError("Batch archive member names must be unique.")
    if any(_paths_resolve_equal(output.output_path, archive_path) for output in result.outputs):
        raise InvalidBatchDefinitionError("Batch archive must not replace a batch output.")

    temporary_directory: TemporaryDirectory[str] | None = None
    try:
        try:
            temporary_directory = TemporaryDirectory(
                dir=archive_path.parent,
                prefix=".docuforge-batch-archive-",
            )
        except OSError as error:
            raise BatchProcessingError("Unable to package the batch outputs.") from error
        workspace = Path(temporary_directory.name)
        staged_archive = workspace / "archive.zip"
        try:
            with ZipFile(staged_archive, mode="w", compression=ZIP_DEFLATED) as archive:
                for output, member_name in zip(result.outputs, member_names, strict=True):
                    archive.write(output.output_path, arcname=member_name)
            if not _valid_staged_archive(
                staged_archive,
                workspace=workspace,
                expected_names=member_names,
            ):
                raise BatchProcessingError("Unable to package the batch outputs.")
            os.replace(staged_archive, archive_path)
        except BatchProcessingError:
            raise
        except (OSError, BadZipFile, LargeZipFile) as error:
            raise BatchProcessingError("Unable to package the batch outputs.") from error
        return BatchArchiveResult(archive_path, member_names)
    finally:
        if temporary_directory is not None:
            try:
                temporary_directory.cleanup()
            except OSError as error:
                raise BatchProcessingError("Unable to package the batch outputs.") from error


def _validate_archive_parent(archive_path: Path) -> None:
    try:
        valid = archive_path.parent.exists() and archive_path.parent.is_dir()
        destination_is_directory = archive_path.exists() and archive_path.is_dir()
    except OSError:
        valid = False
        destination_is_directory = False
    if not valid:
        raise InvalidBatchDefinitionError(
            "Batch archive parent must be an existing directory."
        )
    if destination_is_directory:
        raise InvalidBatchDefinitionError("Batch archive destination must not be a directory.")


def _validate_outputs(result: BatchImageResult | BatchDocumentResult) -> None:
    try:
        output_directory = result.output_directory.resolve(strict=True)
        if not output_directory.is_dir():
            raise OSError
        batch_items = {item.id: item for item in result.batch.items}
        for output in result.outputs:
            if not isinstance(output.output_path, Path):
                raise OSError
            item = batch_items.get(output.item_id)
            if (
                item is None
                or item.status is not BatchItemStatus.COMPLETED
                or item.result is None
                or item.position != output.position
                or item.result.descriptor != output.output_path.name
            ):
                raise OSError
            node = output.output_path.lstat()
            if stat.S_ISLNK(node.st_mode) or not stat.S_ISREG(node.st_mode):
                raise OSError
            resolved = output.output_path.resolve(strict=True)
            if not resolved.is_relative_to(output_directory):
                raise OSError
    except (OSError, RuntimeError, ValueError) as error:
        raise BatchProcessingError("Unable to package the batch outputs.") from error


def _valid_staged_archive(
    staged_archive: Path,
    *,
    workspace: Path,
    expected_names: tuple[str, ...],
) -> bool:
    try:
        node = staged_archive.lstat()
        if stat.S_ISLNK(node.st_mode) or not stat.S_ISREG(node.st_mode):
            return False
        if not staged_archive.resolve(strict=True).is_relative_to(workspace.resolve(strict=True)):
            return False
        with ZipFile(staged_archive, mode="r") as archive:
            actual_names = tuple(archive.namelist())
            if actual_names != expected_names or len(set(actual_names)) != len(actual_names):
                return False
            return archive.testzip() is None
    except (OSError, BadZipFile, LargeZipFile, RuntimeError, ValueError):
        return False


def _safe_member_name(name: object) -> bool:
    if not isinstance(name, str) or not name or name in {".", ".."}:
        return False
    posix_path = PurePosixPath(name)
    windows_path = PureWindowsPath(name)
    return (
        posix_path.name == name
        and windows_path.name == name
        and not posix_path.is_absolute()
        and not windows_path.is_absolute()
        and not posix_path.root
        and not windows_path.root
        and not windows_path.drive
        and ".." not in posix_path.parts
        and ".." not in windows_path.parts
    )


def _paths_resolve_equal(first: Path, second: Path) -> bool:
    try:
        return first.resolve(strict=False) == second.resolve(strict=False)
    except OSError:
        return False

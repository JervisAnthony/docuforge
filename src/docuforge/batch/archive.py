"""Safe atomic ZIP packaging for successful batch outputs."""

from __future__ import annotations

import os
import stat
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory
from zipfile import ZIP64_LIMIT, ZIP_DEFLATED, BadZipFile, LargeZipFile, ZipFile, ZipInfo

from docuforge.batch.document import BatchDocumentResult
from docuforge.batch.exceptions import BatchProcessingError, InvalidBatchDefinitionError
from docuforge.batch.image import BatchImageResult
from docuforge.batch.models import BatchItemStatus

ARCHIVE_CHUNK_BYTES = 1024 * 1024
_DIRECTORY_RELATIVE_OPEN = (
    os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
    and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
)


@dataclass(frozen=True, slots=True)
class _ArchiveSource:
    path: Path
    node: os.stat_result
    directories: tuple[tuple[Path, os.stat_result], ...]


def _unsafe_link(node: os.stat_result) -> bool:
    return stat.S_ISLNK(node.st_mode) or bool(
        getattr(node, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _identity(node: os.stat_result) -> tuple[int, int, int]:
    return node.st_dev, node.st_ino, node.st_mode


def _source_metadata(node: os.stat_result) -> tuple[int, ...]:
    # Windows lstat/fstat ctime can differ; creation/change time is not comparable.
    return (*_identity(node), node.st_size, node.st_mtime_ns,
            node.st_ctime_ns if os.name != "nt" else 0)


def _check_source_node(node: os.stat_result, expected: os.stat_result) -> None:
    if (_unsafe_link(node) or not stat.S_ISREG(node.st_mode)
            or _source_metadata(node) != _source_metadata(expected)):
        raise OSError("Archive source changed.")


def _check_directory(node: os.stat_result, expected: os.stat_result) -> None:
    if (_unsafe_link(node) or not stat.S_ISDIR(node.st_mode)
            or _identity(node) != _identity(expected)):
        raise OSError("Archive source directory changed.")


def _verify_source_path(source: _ArchiveSource) -> None:
    for directory, expected in source.directories:
        _check_directory(directory.lstat(), expected)
    _check_source_node(source.path.lstat(), source.node)


@contextmanager
def _verified_source_parent(source: _ArchiveSource):
    """Pin each POSIX ancestry component; Windows uses checked path identities."""
    with ExitStack() as stack:
        parent_fd = None
        for directory, expected in source.directories:
            _check_directory(directory.lstat(), expected)
            if _DIRECTORY_RELATIVE_OPEN:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
                descriptor = os.open(
                    directory if parent_fd is None else directory.name,
                    flags, dir_fd=parent_fd,
                )
                stack.callback(os.close, descriptor)
                _check_directory(os.fstat(descriptor), expected)
                parent_fd = descriptor
        yield parent_fd


@contextmanager
def _open_verified_archive_source(source: _ArchiveSource):
    """Read only the descriptor matching the preliminary source snapshot."""
    with _verified_source_parent(source) as parent_fd:
        before = (source.path.lstat() if parent_fd is None else os.stat(
            source.path.name, dir_fd=parent_fd, follow_symlinks=False,
        ))
        _check_source_node(before, source.node)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(
            source.path if parent_fd is None else source.path.name, flags, dir_fd=parent_fd,
        )
        try:
            _check_source_node(os.fstat(descriptor), source.node)
            # Check path and ancestry again before consuming any source bytes.
            _verify_source_path(source)
            stream = os.fdopen(descriptor, "rb")
            descriptor = None  # The stream now owns cleanup, including failed reads/writes.
            with stream:
                yield stream
                _check_source_node(os.fstat(stream.fileno()), source.node)
                _verify_source_path(source)
        finally:
            if descriptor is not None:
                os.close(descriptor)


def _stream_archive_member(archive: ZipFile, source: _ArchiveSource, member_name: str) -> None:
    with _open_verified_archive_source(source) as stream:
        timestamp = time.localtime(source.node.st_mtime)[:6]
        # DOS timestamps have a bounded year range; no path-based metadata reads.
        if timestamp[0] < 1980:
            timestamp = (1980, 1, 1, 0, 0, 0)
        elif timestamp[0] > 2107:
            timestamp = (2107, 12, 31, 23, 59, 58)
        info = ZipInfo(member_name, date_time=timestamp)
        info.compress_type = ZIP_DEFLATED
        info.external_attr = (source.node.st_mode & 0xFFFF) << 16
        info.file_size = source.node.st_size
        copied = 0
        with archive.open(info, "w", force_zip64=info.file_size * 1.05 > ZIP64_LIMIT) as member:
            while chunk := stream.read(ARCHIVE_CHUNK_BYTES):
                copied += len(chunk)
                if copied > source.node.st_size:
                    raise OSError("Archive source grew.")
                member.write(chunk)
        if copied != source.node.st_size:
            raise OSError("Archive source size changed.")


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
    sources = _validate_outputs(result)
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
                for source, member_name in zip(sources, member_names, strict=True):
                    _stream_archive_member(archive, source, member_name)
            if not _valid_staged_archive(
                staged_archive,
                workspace=workspace,
                expected_names=member_names,
            ):
                raise BatchProcessingError("Unable to package the batch outputs.")
            # Earlier members may have changed while later members or CRCs were read.
            for source in sources:
                _verify_source_path(source)
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


def _validate_outputs(
    result: BatchImageResult | BatchDocumentResult,
) -> tuple[_ArchiveSource, ...]:
    try:
        root = result.output_directory.absolute()
        if ".." in root.parts:
            raise OSError
        directory_nodes: dict[Path, os.stat_result] = {}
        sources = []
        for directory in (*reversed(root.parents), root):
            node = directory.lstat()
            _check_directory(node, node)
            directory_nodes[directory] = node
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
            if _unsafe_link(node) or not stat.S_ISREG(node.st_mode):
                raise OSError
            path = output.output_path.absolute()
            if ".." in path.parts or not path.is_relative_to(root) or path == root:
                raise OSError
            directories = []
            for directory in reversed(path.parents):
                current = directory.lstat()
                expected = directory_nodes.setdefault(directory, current)
                _check_directory(current, expected)
                directories.append((directory, expected))
            resolved = output.output_path.resolve(strict=True)
            if not resolved.is_relative_to(output_directory):
                raise OSError
            sources.append(_ArchiveSource(path, node, tuple(directories)))
        return tuple(sources)
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

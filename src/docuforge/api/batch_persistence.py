"""Durable metadata, serialization, and workspace storage for batch sessions."""

from __future__ import annotations

import json
import math
import shutil
import sqlite3
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from threading import RLock
from zipfile import BadZipFile, ZipFile

from docuforge.batch import (
    Batch,
    BatchDocumentConvertRequest,
    BatchDocumentInput,
    BatchDocumentOutput,
    BatchDocumentResult,
    BatchId,
    BatchImageCompressRequest,
    BatchImageConvertRequest,
    BatchImageInput,
    BatchImageOutput,
    BatchImageResizeRequest,
    BatchImageResult,
    BatchItemFailure,
    BatchItemRequest,
    BatchItemResult,
    BatchItemStatus,
    BatchRequest,
    InvalidBatchDefinitionError,
    InvalidBatchTransitionError,
)
from docuforge.batch.document import _valid_preserved_pdf
from docuforge.batch.image import _valid_preserved_image

SCHEMA_VERSION = 1
DATABASE_NAME = "batch-sessions.sqlite3"
_PHASES = frozenset({"queued", "processing", "cancelling", "packaging", "ready", "error"})


class BatchPersistenceError(RuntimeError):
    """Safe internal failure for durable batch state."""


@dataclass(frozen=True, slots=True)
class BatchSessionRecord:
    """One transactionally stored session record."""

    batch_id: str
    operation: str
    attempt: int
    phase: str
    cancellation_requested: bool
    request_json: str
    batch_json: str
    result_json: str | None
    session_error_json: str | None
    archive_available: bool
    updated_at: float
    schema_version: int = SCHEMA_VERSION


class BatchSessionRepository:
    """Thread-safe SQLite repository using one connection per operation."""

    def __init__(self, storage_root: Path) -> None:
        self.storage_root = Path(storage_root)
        self._lock = RLock()
        try:
            self.storage_root.mkdir(parents=True, exist_ok=True)
            root_node = self.storage_root.lstat()
            if stat.S_ISLNK(root_node.st_mode) or not stat.S_ISDIR(root_node.st_mode):
                raise OSError
            self.database_path = self.storage_root / DATABASE_NAME
            self._initialize()
        except (OSError, sqlite3.Error) as error:
            raise BatchPersistenceError("Batch persistence could not be initialized.") from error

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, SCHEMA_VERSION}:
                raise BatchPersistenceError("Unsupported batch persistence schema version.")
            if version == 0:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute(
                    """CREATE TABLE batch_sessions (
                    batch_id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    cancellation_requested INTEGER NOT NULL,
                    request_json TEXT NOT NULL,
                    batch_json TEXT NOT NULL,
                    result_json TEXT,
                    session_error_json TEXT,
                    archive_available INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                    )"""
                )
                connection.execute("PRAGMA user_version = 1")

    def add(self, record: BatchSessionRecord) -> None:
        self._write(record, insert=True)

    def save(self, record: BatchSessionRecord) -> None:
        self._write(record, insert=False)

    def _write(self, record: BatchSessionRecord, *, insert: bool) -> None:
        _validate_record(record)
        verb = "INSERT" if insert else "UPDATE"
        sql = (
            "INSERT INTO batch_sessions (batch_id, schema_version, operation, attempt, phase, "
            "cancellation_requested, request_json, batch_json, result_json, session_error_json, "
            "archive_available, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            if insert
            else "UPDATE batch_sessions SET schema_version=?, operation=?, attempt=?, phase=?, "
            "cancellation_requested=?, request_json=?, batch_json=?, result_json=?, "
            "session_error_json=?, archive_available=?, updated_at=? WHERE batch_id=?"
        )
        insert_values = (
            record.batch_id,
            record.schema_version,
            record.operation,
            record.attempt,
            record.phase,
            int(record.cancellation_requested),
            record.request_json,
            record.batch_json,
            record.result_json,
            record.session_error_json,
            int(record.archive_available),
            record.updated_at,
        )
        update_values = (*insert_values[1:], record.batch_id)
        try:
            with self._lock, self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(sql, insert_values if insert else update_values)
                if not insert and cursor.rowcount != 1:
                    raise BatchPersistenceError("Batch session does not exist.")
                connection.commit()
        except BatchPersistenceError:
            raise
        except sqlite3.Error as error:
            raise BatchPersistenceError(f"Batch session could not be {verb.lower()}ed.") from error

    def get(self, batch_id: str) -> BatchSessionRecord | None:
        try:
            normalized = str(BatchId(batch_id))
            with self._lock, self._connection() as connection:
                row = connection.execute(
                    "SELECT batch_id, schema_version, operation, attempt, phase, "
                    "cancellation_requested, request_json, batch_json, result_json, "
                    "session_error_json, archive_available, updated_at "
                    "FROM batch_sessions WHERE batch_id=?",
                    (normalized,),
                ).fetchone()
            return None if row is None else _record_from_row(row)
        except BatchPersistenceError:
            raise
        except (sqlite3.Error, ValueError) as error:
            raise BatchPersistenceError("Batch session could not be read.") from error

    def list_all(self) -> tuple[BatchSessionRecord, ...]:
        try:
            with self._lock, self._connection() as connection:
                rows = connection.execute(
                    "SELECT batch_id, schema_version, operation, attempt, phase, "
                    "cancellation_requested, request_json, batch_json, result_json, "
                    "session_error_json, archive_available, updated_at "
                    "FROM batch_sessions ORDER BY batch_id"
                ).fetchall()
            return tuple(_record_from_row(row) for row in rows)
        except BatchPersistenceError:
            raise
        except sqlite3.Error as error:
            raise BatchPersistenceError("Batch sessions could not be read.") from error

    def delete(self, batch_id: str) -> None:
        try:
            normalized = str(BatchId(batch_id))
            with self._lock, self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM batch_sessions WHERE batch_id=?", (normalized,))
                connection.commit()
        except (sqlite3.Error, ValueError) as error:
            raise BatchPersistenceError("Batch session could not be deleted.") from error


class BatchSessionWorkspace:
    """One deterministic batch workspace in ephemeral or durable storage."""

    __slots__ = ("_cleaned", "batch_id", "durable", "path")

    def __init__(self, path: Path, batch_id: BatchId, *, durable: bool, create: bool) -> None:
        self.batch_id = BatchId(batch_id)
        self.path = Path(path)
        self.durable = durable
        self._cleaned = False
        try:
            if create:
                self.path.mkdir(parents=False, exist_ok=False)
                self.inputs_directory.mkdir()
                self.output_directory.mkdir()
            node = self.path.lstat()
            if stat.S_ISLNK(node.st_mode) or not stat.S_ISDIR(node.st_mode):
                raise OSError
            for directory in (self.inputs_directory, self.output_directory):
                child = directory.lstat()
                if stat.S_ISLNK(child.st_mode) or not stat.S_ISDIR(child.st_mode):
                    raise OSError
                directory.resolve(strict=True).relative_to(self.path.resolve(strict=True))
        except (OSError, ValueError) as error:
            raise BatchPersistenceError("Batch workspace could not be prepared.") from error

    @classmethod
    def ephemeral(cls) -> BatchSessionWorkspace:
        batch_id = BatchId.new()
        path = Path(tempfile.mkdtemp(prefix=f"docuforge-batch-{batch_id}-"))
        # mkdtemp creates the root, so create its children before reconstruction validation.
        (path / "inputs").mkdir()
        (path / "outputs").mkdir()
        return cls(path, batch_id, durable=False, create=False)

    @classmethod
    def durable_new(cls, sessions_root: Path) -> BatchSessionWorkspace:
        batch_id = BatchId.new()
        return cls(sessions_root / str(batch_id), batch_id, durable=True, create=True)

    @classmethod
    def durable_existing(
        cls, sessions_root: Path, batch_id: BatchId
    ) -> BatchSessionWorkspace:
        return cls(sessions_root / str(batch_id), batch_id, durable=True, create=False)

    @property
    def inputs_directory(self) -> Path:
        return self.path / "inputs"

    @property
    def output_directory(self) -> Path:
        return self.path / "outputs"

    @property
    def archive_path(self) -> Path:
        return self.path / "result.zip"

    def cleanup(self) -> None:
        if self._cleaned:
            return
        try:
            shutil.rmtree(self.path)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise BatchPersistenceError("Batch workspace could not be removed.") from error
        self._cleaned = True


def prepare_durable_storage(
    storage_root: Path,
) -> tuple[Path, BatchSessionRepository]:
    """Create and validate the sessions root plus SQLite repository."""
    repository = BatchSessionRepository(storage_root)
    sessions_root = repository.storage_root / "sessions"
    try:
        sessions_root.mkdir(exist_ok=True)
        node = sessions_root.lstat()
        if stat.S_ISLNK(node.st_mode) or not stat.S_ISDIR(node.st_mode):
            raise OSError
    except OSError as error:
        raise BatchPersistenceError("Batch workspace storage could not be initialized.") from error
    return sessions_root, repository


def reconcile_orphan_workspaces(
    sessions_root: Path, referenced_batch_ids: set[str]
) -> None:
    """Remove rowless UUID session directories without touching unrelated entries."""
    try:
        for child in sessions_root.iterdir():
            try:
                batch_id = str(BatchId(child.name))
            except (InvalidBatchDefinitionError, ValueError):
                continue
            if batch_id in referenced_batch_ids:
                continue
            node = child.lstat()
            if stat.S_ISLNK(node.st_mode):
                raise BatchPersistenceError("Batch workspace reconciliation failed.")
            if not stat.S_ISDIR(node.st_mode):
                continue
            child.resolve(strict=True).relative_to(sessions_root.resolve(strict=True))
            shutil.rmtree(child)
    except BatchPersistenceError:
        raise
    except (OSError, ValueError) as error:
        raise BatchPersistenceError("Batch workspace reconciliation failed.") from error


def encode_record(
    *,
    request: object,
    batch: Batch,
    result: BatchImageResult | BatchDocumentResult | None,
    attempt: int,
    phase: str,
    cancellation_requested: bool,
    session_error: tuple[str, str] | None,
    archive_available: bool,
    updated_at: float,
    workspace: BatchSessionWorkspace,
) -> BatchSessionRecord:
    request_payload = _encode_request(request, workspace)
    return BatchSessionRecord(
        batch_id=str(batch.id),
        operation=str(batch.operation),
        attempt=attempt,
        phase=phase,
        cancellation_requested=cancellation_requested,
        request_json=_dump(request_payload),
        batch_json=_dump(_encode_batch(batch)),
        result_json=None if result is None else _dump(_encode_result(result, workspace)),
        session_error_json=(
            None
            if session_error is None
            else _dump({"code": session_error[0], "message": session_error[1]})
        ),
        archive_available=archive_available,
        updated_at=updated_at,
    )


def decode_record(
    record: BatchSessionRecord, workspace: BatchSessionWorkspace
) -> tuple[object, Batch, BatchImageResult | BatchDocumentResult | None, tuple[str, str] | None]:
    """Strictly decode and revalidate all persisted state."""
    try:
        if (
            record.schema_version != SCHEMA_VERSION
            or record.attempt <= 0
            or record.phase not in _PHASES
        ):
            raise TypeError
        request = _decode_request(_load_object(record.request_json), workspace)
        if str(request.batch_id) != record.batch_id:  # type: ignore[attr-defined]
            raise ValueError
        batch = _decode_batch(_load_object(record.batch_json), request)
        if str(batch.operation) != record.operation or str(batch.id) != record.batch_id:
            raise ValueError
        result = (
            None
            if record.result_json is None
            else _decode_result(_load_object(record.result_json), request, batch, workspace)
        )
        if record.phase in {"packaging", "ready"} and result is None:
            raise ValueError
        if record.archive_available and result is None:
            raise ValueError
        error = None
        if record.session_error_json is not None:
            payload = _load_object(record.session_error_json)
            _require_keys(payload, {"code", "message"})
            if not all(isinstance(payload[key], str) and payload[key].strip() for key in payload):
                raise ValueError
            error = (payload["code"], payload["message"])
        if record.phase == "ready" and error is not None:
            raise ValueError
        if record.phase == "error" and error is None:
            raise ValueError
        if record.archive_available and (result is None or not result.outputs):
            raise ValueError
        return request, batch, result, error
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        InvalidBatchDefinitionError,
        InvalidBatchTransitionError,
    ) as error:
        raise BatchPersistenceError("Stored batch session metadata is invalid.") from error


def archive_is_valid(
    path: Path, result: BatchImageResult | BatchDocumentResult, workspace: BatchSessionWorkspace
) -> bool:
    expected = tuple(output.output_path.name for output in result.outputs)
    try:
        node = path.lstat()
        if stat.S_ISLNK(node.st_mode) or not stat.S_ISREG(node.st_mode):
            return False
        if path.resolve(strict=True) != workspace.archive_path.resolve(strict=True):
            return False
        with ZipFile(path) as archive:
            names = tuple(archive.namelist())
            return names == expected and len(set(names)) == len(names) and archive.testzip() is None
    except (OSError, ValueError, BadZipFile):
        return False


def _encode_request(request: object, workspace: BatchSessionWorkspace) -> dict[str, object]:
    items = [
        {
            "id": str(item.id),
            "descriptor": item.descriptor,
            "input": _relative_file(item.input_path, workspace.path),
        }
        for item in request.items  # type: ignore[attr-defined]
    ]
    common: dict[str, object] = {
        "batch_id": str(request.batch_id),  # type: ignore[attr-defined]
        "items": items,
    }
    if isinstance(request, BatchImageConvertRequest):
        return {**common, "kind": "image.convert", "target_format": request.target_format.value}
    if isinstance(request, BatchImageResizeRequest):
        return {
            **common,
            "kind": "image.resize",
            "target_format": request.target_format.value,
            "max_width": request.max_width,
            "max_height": request.max_height,
            "allow_upscale": request.allow_upscale,
        }
    if isinstance(request, BatchImageCompressRequest):
        return {
            **common,
            "kind": "image.compress",
            "target_format": request.target_format.value,
            "quality": request.quality,
            "max_bytes": request.max_bytes,
        }
    if isinstance(request, BatchDocumentConvertRequest):
        return {**common, "kind": "office.to_pdf"}
    raise BatchPersistenceError("Unsupported batch request type.")


def _decode_request(payload: dict[str, object], workspace: BatchSessionWorkspace) -> object:
    kind = payload.get("kind")
    keys = {"kind", "batch_id", "items"}
    if kind == "image.convert":
        keys |= {"target_format"}
    elif kind == "image.resize":
        keys |= {"target_format", "max_width", "max_height", "allow_upscale"}
    elif kind == "image.compress":
        keys |= {"target_format", "quality", "max_bytes"}
    elif kind != "office.to_pdf":
        raise TypeError
    _require_keys(payload, keys)
    batch_id = BatchId(payload["batch_id"])  # type: ignore[arg-type]
    raw_items = payload["items"]
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError
    item_values: list[tuple[Path, object, str]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise TypeError
        _require_keys(raw, {"id", "descriptor", "input"})
        descriptor = raw["descriptor"]
        if not isinstance(descriptor, str) or not descriptor.strip():
            raise ValueError
        path = _resolve_relative_file(raw["input"], workspace.path, require_file=True)
        item_values.append((path, raw["id"], descriptor))
    if kind == "office.to_pdf":
        items = tuple(BatchDocumentInput(path, item_id, descriptor) for path, item_id, descriptor in item_values)
        return BatchDocumentConvertRequest(items, workspace.output_directory, batch_id)
    items = tuple(BatchImageInput(path, item_id, descriptor) for path, item_id, descriptor in item_values)
    target = payload["target_format"]
    if kind == "image.convert":
        return BatchImageConvertRequest(items, workspace.output_directory, target, batch_id)
    if kind == "image.resize":
        return BatchImageResizeRequest(
            items, workspace.output_directory, target,
            max_width=payload["max_width"], max_height=payload["max_height"],
            allow_upscale=payload["allow_upscale"], batch_id=batch_id,
        )
    return BatchImageCompressRequest(
        items, workspace.output_directory, target,
        quality=payload["quality"], max_bytes=payload["max_bytes"], batch_id=batch_id,
    )


def _encode_batch(batch: Batch) -> dict[str, object]:
    return {
        "items": [
            {
                "id": str(item.id),
                "position": item.position,
                "descriptor": item.descriptor,
                "status": item.status.value,
                "result": None if item.result is None else item.result.descriptor,
                "failure": (
                    None
                    if item.failure is None
                    else {"code": item.failure.code, "message": item.failure.message}
                ),
            }
            for item in batch.items
        ]
    }


def _decode_batch(payload: dict[str, object], request: object) -> Batch:
    _require_keys(payload, {"items"})
    raw_items = payload["items"]
    if not isinstance(raw_items, list):
        raise TypeError
    batch = Batch(
        BatchRequest(
            request.batch_id,  # type: ignore[attr-defined]
            _request_operation(request),
            tuple(
                # Request constructors already validate identity and ordering.
                BatchItemRequest(item.id, position, item.descriptor)
                for position, item in enumerate(request.items)  # type: ignore[attr-defined]
            ),
        )
    )
    if len(raw_items) != len(batch.items):
        raise ValueError
    for position, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise TypeError
        _require_keys(raw, {"id", "position", "descriptor", "status", "result", "failure"})
        expected = batch.items[position]
        if raw["id"] != str(expected.id) or raw["position"] != position or raw["descriptor"] != expected.descriptor:
            raise ValueError
        status = BatchItemStatus(raw["status"])
        if status is BatchItemStatus.PENDING:
            if raw["result"] is not None or raw["failure"] is not None:
                raise ValueError
        elif status is BatchItemStatus.RUNNING:
            if raw["result"] is not None or raw["failure"] is not None:
                raise ValueError
            batch = batch.start_item(expected.id)
        elif status is BatchItemStatus.COMPLETED:
            if not isinstance(raw["result"], str) or raw["failure"] is not None:
                raise ValueError
            batch = batch.start_item(expected.id).complete_item(
                expected.id, BatchItemResult(raw["result"])
            )
        elif status is BatchItemStatus.FAILED:
            failure = raw["failure"]
            if not isinstance(failure, dict) or raw["result"] is not None:
                raise ValueError
            _require_keys(failure, {"code", "message"})
            batch = batch.fail_item(expected.id, BatchItemFailure(failure["code"], failure["message"]))
        else:
            if raw["result"] is not None or raw["failure"] is not None:
                raise ValueError
            batch = batch.cancel_item(expected.id)
    return batch


def _encode_result(
    result: BatchImageResult | BatchDocumentResult, workspace: BatchSessionWorkspace
) -> dict[str, object]:
    kind = "image" if isinstance(result, BatchImageResult) else "document"
    return {
        "kind": kind,
        "outputs": [
            {
                "item_id": str(output.item_id),
                "position": output.position,
                "input": _relative_file(output.input_path, workspace.path),
                "output": _relative_file(output.output_path, workspace.path),
                "source_format": output.source_format.value,
                "target_format": output.target_format.value,
            }
            for output in result.outputs
        ],
    }


def _decode_result(
    payload: dict[str, object], request: object, batch: Batch, workspace: BatchSessionWorkspace
) -> BatchImageResult | BatchDocumentResult:
    _require_keys(payload, {"kind", "outputs"})
    raw_outputs = payload["outputs"]
    if not isinstance(raw_outputs, list):
        raise TypeError
    values = []
    for raw in raw_outputs:
        if not isinstance(raw, dict):
            raise TypeError
        _require_keys(raw, {"item_id", "position", "input", "output", "source_format", "target_format"})
        input_path = _resolve_relative_file(raw["input"], workspace.path, require_file=True)
        output_path = _resolve_relative_file(raw["output"], workspace.path, require_file=True)
        values.append((raw, input_path, output_path))
    if payload["kind"] == "image" and isinstance(
        request, (BatchImageConvertRequest, BatchImageResizeRequest, BatchImageCompressRequest)
    ):
        outputs = tuple(
            BatchImageOutput(
                raw["item_id"], raw["position"], input_path, output_path,
                raw["source_format"], raw["target_format"],
            )
            for raw, input_path, output_path in values
        )
        result = BatchImageResult(batch, workspace.output_directory, outputs)
        if any(
            not _valid_preserved_image(output, source=request.items[output.position], request=request)
            for output in outputs
        ):
            raise ValueError
        return result
    if payload["kind"] == "document" and isinstance(request, BatchDocumentConvertRequest):
        outputs = tuple(
            BatchDocumentOutput(
                raw["item_id"], raw["position"], input_path, output_path,
                raw["source_format"], raw["target_format"],
            )
            for raw, input_path, output_path in values
        )
        result = BatchDocumentResult(batch, workspace.output_directory, outputs)
        if any(
            not _valid_preserved_pdf(output, source=request.items[output.position], request=request)
            for output in outputs
        ):
            raise ValueError
        return result
    raise ValueError


def _request_operation(request: object) -> str:
    if isinstance(request, BatchImageConvertRequest):
        return "image.convert"
    if isinstance(request, BatchImageResizeRequest):
        return "image.resize"
    if isinstance(request, BatchImageCompressRequest):
        return "image.compress"
    if isinstance(request, BatchDocumentConvertRequest):
        return "office.to_pdf"
    raise ValueError


def _relative_file(path: Path, root: Path) -> str:
    try:
        node = path.lstat()
        if stat.S_ISLNK(node.st_mode) or not stat.S_ISREG(node.st_mode):
            raise OSError
        relative = path.resolve(strict=True).relative_to(root.resolve(strict=True))
        return relative.as_posix()
    except (OSError, ValueError) as error:
        raise BatchPersistenceError("Batch artifact path is unsafe.") from error


def _resolve_relative_file(value: object, root: Path, *, require_file: bool) -> Path:
    if not isinstance(value, str) or not value:
        raise TypeError
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute() or windows.is_absolute() or windows.drive or windows.root
        or ".." in posix.parts or ".." in windows.parts or "\\" in value
    ):
        raise ValueError
    candidate = root.joinpath(*posix.parts)
    resolved = candidate.resolve(strict=require_file)
    resolved.relative_to(root.resolve(strict=True))
    if require_file:
        node = candidate.lstat()
        if stat.S_ISLNK(node.st_mode) or not stat.S_ISREG(node.st_mode):
            raise ValueError
    return candidate


def _dump(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_object(value: str) -> dict[str, object]:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise TypeError
    return payload


def _require_keys(payload: dict[object, object], expected: set[str]) -> None:
    if set(payload) != expected:
        raise ValueError


def _validate_record(record: BatchSessionRecord) -> None:
    if (
        not isinstance(record, BatchSessionRecord)
        or type(record.schema_version) is not int
        or record.schema_version != SCHEMA_VERSION
    ):
        raise BatchPersistenceError("Batch session record is invalid.")
    try:
        BatchId(record.batch_id)
        if (
            record.operation not in {
                "image.convert",
                "image.resize",
                "image.compress",
                "office.to_pdf",
            }
            or record.phase not in _PHASES
            or type(record.attempt) is not int
            or record.attempt <= 0
            or not isinstance(record.cancellation_requested, bool)
            or not isinstance(record.archive_available, bool)
            or isinstance(record.updated_at, bool)
            or not isinstance(record.updated_at, (int, float))
            or not math.isfinite(record.updated_at)
        ):
            raise ValueError
        for value in (record.request_json, record.batch_json):
            _load_object(value)
        if record.result_json is not None:
            _load_object(record.result_json)
        if record.session_error_json is not None:
            _load_object(record.session_error_json)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise BatchPersistenceError("Batch session record is invalid.") from error


def _record_from_row(row: tuple[object, ...]) -> BatchSessionRecord:
    try:
        record = BatchSessionRecord(
            batch_id=row[0], schema_version=row[1], operation=row[2], attempt=row[3],
            phase=row[4], cancellation_requested=bool(row[5]), request_json=row[6],
            batch_json=row[7], result_json=row[8], session_error_json=row[9],
            archive_available=bool(row[10]), updated_at=row[11],
        )
        _validate_record(record)
        if row[5] not in {0, 1} or row[10] not in {0, 1}:
            raise ValueError
        return record
    except (TypeError, ValueError) as error:
        raise BatchPersistenceError("Stored batch session record is invalid.") from error

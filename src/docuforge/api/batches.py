"""Single-process execution with optional durable batch-session storage."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from threading import RLock
from time import time

from docuforge.api.batch_access import (
    generate_access_token,
    hash_access_token,
    verify_access_token,
)
from docuforge.api.batch_persistence import (
    BatchPersistenceError,
    BatchSessionRepository,
    BatchSessionWorkspace,
    archive_is_valid,
    cleanup_durable_workspace,
    decode_record,
    encode_record,
    prepare_durable_storage,
    reconcile_orphan_workspaces,
)
from docuforge.api.batch_storage_lock import BatchStorageOwnerLock
from docuforge.api.errors import ApiError
from docuforge.api.office import OfficeEngineFactory
from docuforge.batch import (
    Batch,
    BatchCancellationToken,
    BatchDocumentConvertRequest,
    BatchDocumentResult,
    BatchId,
    BatchImageCompressRequest,
    BatchImageConvertRequest,
    BatchImageResizeRequest,
    BatchImageResult,
    BatchItemFailure,
    BatchItemRequest,
    BatchItemStatus,
    BatchRequest,
    batch_compress_images,
    batch_convert_documents,
    batch_convert_images,
    batch_resize_images,
    package_batch_outputs,
)
from docuforge.jobs import OperationKey

BatchExecutionRequest = (
    BatchImageConvertRequest
    | BatchImageResizeRequest
    | BatchImageCompressRequest
    | BatchDocumentConvertRequest
)
BatchExecutionResult = BatchImageResult | BatchDocumentResult

_EXECUTION_FAILURE = BatchItemFailure(
    "batch_execution_failed", "The batch could not be completed."
)


class BatchExecutionPhase(str, Enum):
    """Orchestration phase separate from item outcome status."""

    QUEUED = "queued"
    PROCESSING = "processing"
    CANCELLING = "cancelling"
    PACKAGING = "packaging"
    READY = "ready"
    ERROR = "error"
    DELETING = "deleting"


@dataclass(frozen=True, slots=True)
class BatchSessionError:
    """Safe session-level failure details."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class BatchExecutionSnapshot:
    """Immutable service state returned to HTTP adapters and tests."""

    batch: Batch
    attempt: int
    phase: BatchExecutionPhase
    cancellation_requested: bool
    session_error: BatchSessionError | None
    can_cancel: bool
    can_recover: bool
    can_download: bool


@dataclass(frozen=True, slots=True)
class BatchSessionGrant:
    """A newly accepted session and its one-time plaintext capability."""

    snapshot: BatchExecutionSnapshot
    access_token: str = field(repr=False)


@dataclass(slots=True)
class _Session:
    access_token_hash: str
    request: BatchExecutionRequest
    workspace: BatchSessionWorkspace
    batch: Batch
    cancellation: BatchCancellationToken
    attempt: int
    phase: BatchExecutionPhase
    result: BatchExecutionResult | None
    archive_path: Path | None
    session_error: BatchSessionError | None
    updated_at: float


class BatchExecutionService:
    """Own bounded workers and isolated ephemeral or durable batch sessions."""

    def __init__(
        self,
        *,
        office_engine_factory: OfficeEngineFactory,
        max_workers: int = 2,
        max_inflight_sessions: int = 8,
        terminal_ttl_seconds: int = 3600,
        clock: Callable[[], float] = time,
        storage_directory: Path | None = None,
    ) -> None:
        if type(max_workers) is not int or max_workers <= 0:
            raise ValueError("max_workers must be a positive integer")
        if type(max_inflight_sessions) is not int or max_inflight_sessions <= 0:
            raise ValueError("max_inflight_sessions must be a positive integer")
        if max_inflight_sessions < max_workers:
            raise ValueError("max_inflight_sessions must be at least max_workers")
        if type(terminal_ttl_seconds) is not int or terminal_ttl_seconds <= 0:
            raise ValueError("terminal_ttl_seconds must be a positive integer")
        self._office_engine_factory = office_engine_factory
        self._max_inflight_sessions = max_inflight_sessions
        self._terminal_ttl_seconds = terminal_ttl_seconds
        self._clock = clock
        self._durable = storage_directory is not None
        self._sessions_root: Path | None = None
        self._repository: BatchSessionRepository | None = None
        self._storage_owner_lock: BatchStorageOwnerLock | None = None
        self._sessions: dict[str, _Session] = {}
        self._admitted_batch_ids: set[str] = set()
        self._lock = RLock()
        self._shutdown = False
        try:
            if storage_directory is not None:
                storage_root = Path(storage_directory)
                self._storage_owner_lock = BatchStorageOwnerLock.acquire(storage_root)
                self._sessions_root, self._repository = prepare_durable_storage(storage_root)
                self._restore_sessions()
            self._executor = ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix="docuforge-batch"
            )
        except BaseException:
            if self._storage_owner_lock is not None:
                self._storage_owner_lock.release()
            raise

    def create_workspace(self) -> BatchSessionWorkspace:
        """Reserve execution admission before returning an upload workspace."""
        with self._lock:
            self._expire_locked()
            if self._shutdown:
                raise RuntimeError("batch execution service is shut down")
            self._require_capacity_locked()
            batch_id = BatchId.new()
            normalized_id = str(batch_id)
            self._admitted_batch_ids.add(normalized_id)
            try:
                if self._sessions_root is None:
                    return BatchSessionWorkspace.ephemeral(batch_id)
                return BatchSessionWorkspace.durable_new(self._sessions_root, batch_id)
            except BaseException:
                self._admitted_batch_ids.discard(normalized_id)
                raise

    def abandon_workspace(self, workspace: BatchSessionWorkspace) -> None:
        """Release and clean a preparation workspace that was not accepted."""
        if not isinstance(workspace, BatchSessionWorkspace):
            raise TypeError("workspace must be a BatchSessionWorkspace")
        batch_id = str(workspace.batch_id)
        with self._lock:
            if batch_id in self._sessions:
                raise ValueError("a registered batch workspace cannot be abandoned")
            self._admitted_batch_ids.discard(batch_id)
        workspace.cleanup()

    def create_session(
        self, request: BatchExecutionRequest, workspace: BatchSessionWorkspace
    ) -> BatchSessionGrant:
        """Register and queue one new batch attempt."""
        if not isinstance(workspace, BatchSessionWorkspace):
            raise TypeError("workspace must be a BatchSessionWorkspace")
        batch = _initial_batch(request)
        if batch.id != workspace.batch_id:
            raise ValueError("batch request identity must match its workspace")
        access_token = generate_access_token()
        session = _Session(
            access_token_hash=hash_access_token(access_token),
            request=request,
            workspace=workspace,
            batch=batch,
            cancellation=BatchCancellationToken(),
            attempt=1,
            phase=BatchExecutionPhase.QUEUED,
            result=None,
            archive_path=None,
            session_error=None,
            updated_at=self._clock(),
        )
        with self._lock:
            self._expire_locked()
            if self._shutdown:
                raise RuntimeError("batch execution service is shut down")
            batch_id = str(batch.id)
            if batch_id not in self._admitted_batch_ids:
                raise ValueError("batch workspace does not own execution admission")
            self._sessions[batch_id] = session
            try:
                self._executor.submit(self._execute, batch_id, False, False, 1)
            except Exception:  # noqa: BLE001 - submission is an infrastructure boundary
                self._sessions.pop(batch_id, None)
                self._admitted_batch_ids.discard(batch_id)
                with suppress(BatchPersistenceError):
                    workspace.cleanup()
                raise ApiError(
                    status_code=503,
                    code="batch_persistence_failed",
                    message="The batch session could not be persisted.",
                ) from None
            try:
                self._persist_locked(session, add=True)
            except BatchPersistenceError:
                self._sessions.pop(batch_id, None)
                self._admitted_batch_ids.discard(batch_id)
                with suppress(BatchPersistenceError):
                    workspace.cleanup()
                raise ApiError(
                    status_code=503,
                    code="batch_persistence_failed",
                    message="The batch session could not be persisted.",
                ) from None
            return BatchSessionGrant(self._snapshot_locked(session), access_token)

    def get(self, batch_id: str, access_token: object) -> BatchExecutionSnapshot:
        with self._lock:
            session = self._get_authorized_locked(batch_id, access_token)
            return self._snapshot_locked(session)

    def cancel(self, batch_id: str, access_token: object) -> BatchExecutionSnapshot:
        with self._lock:
            session = self._get_authorized_locked(batch_id, access_token)
            if (
                session.phase is BatchExecutionPhase.CANCELLING
                and session.cancellation.cancellation_requested
            ):
                return self._snapshot_locked(session)
            if not _can_request_cancellation(session):
                raise ApiError(
                    status_code=409,
                    code="batch_not_cancellable",
                    message="The batch can no longer be cancelled.",
                )
            updated_at = self._clock()
            if self._repository is not None:
                candidate_cancellation = BatchCancellationToken()
                candidate_cancellation.request_cancellation()
                candidate = _Session(
                    access_token_hash=session.access_token_hash,
                    request=session.request,
                    workspace=session.workspace,
                    batch=session.batch,
                    cancellation=candidate_cancellation,
                    attempt=session.attempt,
                    phase=BatchExecutionPhase.CANCELLING,
                    result=session.result,
                    archive_path=session.archive_path,
                    session_error=session.session_error,
                    updated_at=updated_at,
                )
                self._persist_or_api_error(candidate)
            session.cancellation.request_cancellation()
            session.phase = BatchExecutionPhase.CANCELLING
            session.updated_at = updated_at
            return self._snapshot_locked(session)

    def recover(self, batch_id: str, access_token: object) -> BatchExecutionSnapshot:
        with self._lock:
            session = self._get_authorized_locked(batch_id, access_token)
            if session.phase not in {BatchExecutionPhase.READY, BatchExecutionPhase.ERROR}:
                raise ApiError(
                    status_code=409,
                    code="batch_not_recoverable",
                    message="The batch is not ready for recovery.",
                )
            packaging_only = (
                session.phase is BatchExecutionPhase.ERROR
                and session.result is not None
                and session.session_error is not None
                and session.session_error.code
                in {"batch_packaging_failed", "batch_packaging_interrupted"}
            )
            selective = session.result is not None and any(
                item.status in {BatchItemStatus.FAILED, BatchItemStatus.CANCELLED}
                for item in session.result.batch.items
            )
            if not packaging_only and not selective and session.phase is not BatchExecutionPhase.ERROR:
                raise ApiError(
                    status_code=409,
                    code="batch_not_recoverable",
                    message="The batch has no recoverable items.",
                )
            normalized_id = str(session.batch.id)
            self._reserve_admission_locked(normalized_id)
            submitted = False
            try:
                if packaging_only:
                    next_batch = session.batch
                    next_result = session.result
                elif selective and session.result is not None:
                    next_batch = session.result.batch.recover_items()
                    next_result = session.result
                else:
                    next_batch = _initial_batch(session.request)
                    next_result = None
                next_cancellation = BatchCancellationToken()
                updated_at = self._clock()
                candidate = _Session(
                    access_token_hash=session.access_token_hash,
                    request=session.request,
                    workspace=session.workspace,
                    # A selective retry's preserved result belongs to the previous terminal
                    # snapshot. Persist that self-consistent pair until the worker records
                    # the new processing snapshot without the preserved result.
                    batch=session.batch if selective else next_batch,
                    cancellation=next_cancellation,
                    attempt=session.attempt + 1,
                    phase=BatchExecutionPhase.QUEUED,
                    result=next_result,
                    archive_path=None,
                    session_error=None,
                    updated_at=updated_at,
                )
                try:
                    self._executor.submit(
                        self._execute,
                        normalized_id,
                        selective,
                        packaging_only,
                        candidate.attempt,
                    )
                except Exception:  # noqa: BLE001 - submission is an infrastructure boundary
                    raise ApiError(
                        status_code=503,
                        code="batch_persistence_failed",
                        message="The batch session could not be persisted.",
                    ) from None
                self._persist_or_api_error(candidate)
                session.attempt = candidate.attempt
                session.cancellation = next_cancellation
                session.session_error = None
                session.archive_path = None
                session.result = next_result
                session.batch = next_batch
                session.phase = BatchExecutionPhase.QUEUED
                session.updated_at = updated_at
                submitted = True
                return self._snapshot_locked(session)
            finally:
                if not submitted:
                    self._admitted_batch_ids.discard(normalized_id)

    def download_path(self, batch_id: str, access_token: object) -> Path:
        with self._lock:
            session = self._get_authorized_locked(batch_id, access_token)
            if session.phase in {
                BatchExecutionPhase.QUEUED,
                BatchExecutionPhase.PROCESSING,
                BatchExecutionPhase.CANCELLING,
                BatchExecutionPhase.PACKAGING,
            }:
                raise ApiError(
                    status_code=409,
                    code="batch_not_ready",
                    message="The batch download is not ready.",
                )
            if session.result is not None and not session.result.outputs:
                raise ApiError(
                    status_code=409,
                    code="batch_has_no_outputs",
                    message="The batch has no successful outputs.",
                )
            if session.archive_path is None or not session.archive_path.is_file():
                raise ApiError(
                    status_code=409,
                    code="batch_packaging_failed",
                    message="The batch archive is unavailable.",
                )
            return session.archive_path

    def delete_session(self, batch_id: str, access_token: object) -> None:
        """Delete a terminal session after committing irreversible deletion intent."""
        with self._lock:
            session = self._get_authorized_locked(batch_id, access_token, allow_deleting=True)
            if session.phase not in {
                BatchExecutionPhase.READY,
                BatchExecutionPhase.ERROR,
                BatchExecutionPhase.DELETING,
            }:
                raise ApiError(
                    status_code=409,
                    code="batch_not_deletable",
                    message="The batch must finish or be cancelled before it can be deleted.",
                )
            if session.phase is not BatchExecutionPhase.DELETING:
                candidate = replace(
                    session, phase=BatchExecutionPhase.DELETING, updated_at=self._clock()
                )
                self._persist_or_api_error(candidate)
                session.phase = candidate.phase
                session.updated_at = candidate.updated_at
            try:
                self._finalize_deletion_locked(str(batch_id), session)
            except BatchPersistenceError:
                raise ApiError(
                    status_code=503,
                    code="batch_deletion_failed",
                    message="The batch could not be deleted. Retry the deletion.",
                ) from None

    def shutdown(self) -> None:
        """Cooperatively stop work while retaining durable sessions."""
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            sessions = tuple(self._sessions.values())
            for session in sessions:
                if session.phase in {
                    BatchExecutionPhase.QUEUED,
                    BatchExecutionPhase.PROCESSING,
                    BatchExecutionPhase.CANCELLING,
                    BatchExecutionPhase.PACKAGING,
                }:
                    session.cancellation.request_cancellation()
        self._executor.shutdown(wait=True, cancel_futures=False)
        with self._lock:
            if not self._durable:
                for session in self._sessions.values():
                    session.workspace.cleanup()
            self._sessions.clear()
            self._admitted_batch_ids.clear()
            if self._storage_owner_lock is not None:
                self._storage_owner_lock.release()

    def _execute(
        self,
        batch_id: str,
        selective: bool,
        packaging_only: bool,
        expected_attempt: int,
    ) -> None:
        with self._lock:
            session = self._sessions.get(batch_id)
            if session is None or session.attempt != expected_attempt:
                return
            attempt = expected_attempt
            previous = session.result if selective else None
            result = session.result if packaging_only else None
        try:
            if not packaging_only:
                with self._lock:
                    session.phase = (
                        BatchExecutionPhase.CANCELLING
                        if session.cancellation.cancellation_requested
                        else BatchExecutionPhase.PROCESSING
                    )
                    if selective:
                        session.result = None
                    session.updated_at = self._clock()
                    self._persist_locked(session)
                result = self._run_request(session, previous, attempt)
                with self._lock:
                    if session.attempt != attempt:
                        return
                    session.result = result
                    session.batch = result.batch
                    session.phase = BatchExecutionPhase.PACKAGING
                    session.updated_at = self._clock()
                    self._persist_locked(session)
            if result is None:
                raise RuntimeError("batch result missing")
            if result.outputs:
                package_batch_outputs(result, session.workspace.archive_path)
                archive_path: Path | None = session.workspace.archive_path
            else:
                archive_path = None
            with self._lock:
                session.archive_path = archive_path
                session.phase = BatchExecutionPhase.READY
                session.session_error = None
                session.updated_at = self._clock()
                self._persist_locked(session)
                self._admitted_batch_ids.discard(batch_id)
        except Exception:  # noqa: BLE001 - process boundary must expose only safe state
            with self._lock:
                if result is not None:
                    session.result = result
                    session.batch = result.batch
                    session.session_error = BatchSessionError(
                        "batch_packaging_failed", "The batch outputs could not be packaged."
                    )
                else:
                    session.result = None
                    session.batch = session.batch.fail_nonterminal_items(_EXECUTION_FAILURE)
                    session.session_error = BatchSessionError(
                        "batch_execution_failed", "The batch could not be completed."
                    )
                session.archive_path = None
                session.phase = BatchExecutionPhase.ERROR
                session.updated_at = self._clock()
                try:
                    self._persist_locked(session)
                except BatchPersistenceError:
                    session.session_error = BatchSessionError(
                        "batch_persistence_failed",
                        "The batch session could not be persisted.",
                    )
                finally:
                    self._admitted_batch_ids.discard(batch_id)

    def _run_request(
        self,
        session: _Session,
        previous: BatchExecutionResult | None,
        attempt: int,
    ) -> BatchExecutionResult:
        def progress(batch: Batch) -> None:
            with self._lock:
                if session.attempt != attempt:
                    return
                session.batch = batch
                if session.phase is not BatchExecutionPhase.CANCELLING:
                    session.phase = BatchExecutionPhase.PROCESSING
                session.updated_at = self._clock()
                self._persist_locked(session)

        request = session.request
        controls = {
            "cancellation": session.cancellation,
            "on_progress": progress,
            "recover_from": previous,
        }
        if isinstance(request, BatchImageConvertRequest):
            return batch_convert_images(request, **controls)
        if isinstance(request, BatchImageResizeRequest):
            return batch_resize_images(request, **controls)
        if isinstance(request, BatchImageCompressRequest):
            return batch_compress_images(request, **controls)
        return batch_convert_documents(
            request,
            engine=self._office_engine_factory(),
            **controls,
        )

    def _get_authorized_locked(
        self, batch_id: str, access_token: object, *, allow_deleting: bool = False
    ) -> _Session:
        self._expire_locked()
        session = self._sessions.get(str(batch_id))
        if (
            session is None
            or (session.phase is BatchExecutionPhase.DELETING and not allow_deleting)
            or not verify_access_token(access_token, session.access_token_hash)
        ):
            raise ApiError(
                status_code=404,
                code="batch_not_found",
                message="The batch session was not found.",
            )
        return session

    def _expire_locked(self) -> None:
        now = self._clock()
        expired = [
            batch_id
            for batch_id, session in self._sessions.items()
            if session.phase in {BatchExecutionPhase.READY, BatchExecutionPhase.ERROR}
            and now - session.updated_at >= self._terminal_ttl_seconds
        ]
        for batch_id in expired:
            session = self._sessions[batch_id]
            candidate = replace(session, phase=BatchExecutionPhase.DELETING, updated_at=now)
            self._persist_locked(candidate)
            session.phase = candidate.phase
            session.updated_at = now
            self._finalize_deletion_locked(batch_id, session)

    def _finalize_deletion_locked(self, batch_id: str, session: _Session) -> None:
        session.workspace.cleanup()
        if self._repository is not None:
            self._repository.delete(batch_id)
        self._sessions.pop(batch_id, None)

    def _require_capacity_locked(self) -> None:
        if len(self._admitted_batch_ids) >= self._max_inflight_sessions:
            raise ApiError(
                status_code=503,
                code="batch_capacity_exceeded",
                message="The batch service is temporarily at capacity. Try again later.",
            )

    def _reserve_admission_locked(self, batch_id: str) -> None:
        if batch_id in self._admitted_batch_ids:
            raise RuntimeError("batch already owns execution admission")
        self._require_capacity_locked()
        self._admitted_batch_ids.add(batch_id)

    def _persist_or_api_error(self, session: _Session) -> None:
        try:
            self._persist_locked(session)
        except BatchPersistenceError:
            raise ApiError(
                status_code=503,
                code="batch_persistence_failed",
                message="The batch session could not be persisted.",
            ) from None

    def _persist_locked(self, session: _Session, *, add: bool = False) -> None:
        if self._repository is None:
            return
        record = encode_record(
            request=session.request,
            access_token_hash=session.access_token_hash,
            batch=session.batch,
            result=session.result,
            attempt=session.attempt,
            phase=session.phase.value,
            cancellation_requested=session.cancellation.cancellation_requested,
            session_error=(
                None
                if session.session_error is None
                else (session.session_error.code, session.session_error.message)
            ),
            archive_available=session.archive_path is not None,
            updated_at=session.updated_at,
            workspace=session.workspace,
        )
        if add:
            self._repository.add(record)
        else:
            self._repository.save(record)

    def _restore_sessions(self) -> None:
        if self._repository is None or self._sessions_root is None:
            return
        now = self._clock()
        for batch_id in self._repository.list_legacy_batch_ids():
            workspace_path = self._sessions_root / batch_id
            if workspace_path.exists() or workspace_path.is_symlink():
                workspace = BatchSessionWorkspace.durable_existing(
                    self._sessions_root, BatchId(batch_id)
                )
                workspace.cleanup()
            self._repository.delete(batch_id)
        for batch_id in self._repository.list_deleting_batch_ids():
            cleanup_durable_workspace(self._sessions_root, batch_id)
            self._repository.delete(batch_id)
        records = self._repository.list_all()
        reconcile_orphan_workspaces(
            self._sessions_root, {record.batch_id for record in records}
        )
        for record in records:
            try:
                phase = BatchExecutionPhase(record.phase)
                workspace = BatchSessionWorkspace.durable_existing(
                    self._sessions_root, BatchId(record.batch_id)
                )
                if (
                    phase in {BatchExecutionPhase.READY, BatchExecutionPhase.ERROR}
                    and now - record.updated_at >= self._terminal_ttl_seconds
                ):
                    self._repository.save(replace(record, phase="deleting", updated_at=now))
                    cleanup_durable_workspace(self._sessions_root, record.batch_id)
                    self._repository.delete(record.batch_id)
                    continue
                request, batch, result, error = decode_record(record, workspace)
            except (TypeError, ValueError) as decode_error:
                raise BatchPersistenceError(
                    "Stored batch session could not be restored."
                ) from decode_error
            session = _Session(
                access_token_hash=record.access_token_hash,
                request=request,  # type: ignore[arg-type]
                workspace=workspace,
                batch=batch,
                cancellation=BatchCancellationToken(),
                attempt=record.attempt,
                phase=phase,
                result=result,
                archive_path=None,
                session_error=None if error is None else BatchSessionError(*error),
                updated_at=record.updated_at,
            )
            if phase in {
                BatchExecutionPhase.QUEUED,
                BatchExecutionPhase.PROCESSING,
                BatchExecutionPhase.CANCELLING,
            }:
                session.batch = batch.fail_nonterminal_items(_EXECUTION_FAILURE)
                session.result = None
                session.phase = BatchExecutionPhase.ERROR
                session.session_error = BatchSessionError(
                    "batch_execution_interrupted",
                    "The batch was interrupted by a server restart. Retry the batch.",
                )
                session.updated_at = now
            elif phase is BatchExecutionPhase.PACKAGING:
                if result is None:
                    raise BatchPersistenceError(
                        "Stored packaging session has no trustworthy result."
                    )
                session.phase = BatchExecutionPhase.ERROR
                session.session_error = BatchSessionError(
                    "batch_packaging_interrupted",
                    "The batch archive was interrupted by a server restart. Retry packaging.",
                )
                session.updated_at = now
            elif phase is BatchExecutionPhase.READY and result is not None and result.outputs:
                if record.archive_available and archive_is_valid(
                    workspace.archive_path, result, workspace
                ):
                    session.archive_path = workspace.archive_path
                else:
                    session.phase = BatchExecutionPhase.ERROR
                    session.session_error = BatchSessionError(
                        "batch_packaging_failed",
                        "The batch outputs could not be packaged.",
                    )
                    session.updated_at = now
            self._sessions[record.batch_id] = session
            if session.phase is not phase or session.updated_at != record.updated_at:
                self._persist_locked(session)

    def _snapshot_locked(self, session: _Session) -> BatchExecutionSnapshot:
        recoverable_items = any(
            item.status in {BatchItemStatus.FAILED, BatchItemStatus.CANCELLED}
            for item in session.batch.items
        )
        active = session.phase in {
            BatchExecutionPhase.QUEUED,
            BatchExecutionPhase.PROCESSING,
            BatchExecutionPhase.CANCELLING,
            BatchExecutionPhase.PACKAGING,
        }
        return BatchExecutionSnapshot(
            batch=session.batch,
            attempt=session.attempt,
            phase=session.phase,
            cancellation_requested=session.cancellation.cancellation_requested,
            session_error=session.session_error,
            can_cancel=_can_request_cancellation(session),
            can_recover=not active
            and (recoverable_items or session.phase is BatchExecutionPhase.ERROR),
            can_download=(
                session.phase is BatchExecutionPhase.READY
                and session.archive_path is not None
                and session.archive_path.is_file()
            ),
        )


def _can_request_cancellation(session: _Session) -> bool:
    """Return whether cooperative cancellation can still stop pending work."""
    return (
        session.phase
        in {BatchExecutionPhase.QUEUED, BatchExecutionPhase.PROCESSING}
        and not session.cancellation.cancellation_requested
        and not session.batch.is_terminal
        and any(item.status is BatchItemStatus.PENDING for item in session.batch.items)
    )


def _initial_batch(request: BatchExecutionRequest) -> Batch:
    operation = _operation_for(request)
    return Batch(
        BatchRequest(
            request.batch_id,
            operation,
            tuple(
                BatchItemRequest(item.id, position, item.descriptor)
                for position, item in enumerate(request.items)
            ),
        )
    )


def _operation_for(request: BatchExecutionRequest) -> OperationKey:
    if isinstance(request, BatchImageConvertRequest):
        return OperationKey("image.convert")
    if isinstance(request, BatchImageResizeRequest):
        return OperationKey("image.resize")
    if isinstance(request, BatchImageCompressRequest):
        return OperationKey("image.compress")
    if isinstance(request, BatchDocumentConvertRequest):
        return OperationKey("office.to_pdf")
    raise TypeError("request must be a supported batch request")

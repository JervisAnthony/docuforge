"""Process-local execution sessions for browser-visible batch workflows."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import RLock
from time import monotonic

from docuforge.api.errors import ApiError
from docuforge.api.office import OfficeEngineFactory
from docuforge.batch import (
    Batch,
    BatchCancellationToken,
    BatchDocumentConvertRequest,
    BatchDocumentResult,
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
    """Process-local orchestration phase separate from item outcome status."""

    QUEUED = "queued"
    PROCESSING = "processing"
    CANCELLING = "cancelling"
    PACKAGING = "packaging"
    READY = "ready"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class BatchSessionError:
    """Safe session-level failure details."""

    code: str
    message: str


class BatchSessionWorkspace:
    """Retained workspace owned by exactly one process-local session."""

    __slots__ = ("_cleaned", "path")

    def __init__(self) -> None:
        self.path = Path(tempfile.mkdtemp(prefix="docuforge-batch-session-"))
        self._cleaned = False
        self.inputs_directory.mkdir()
        self.output_directory.mkdir()

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
        self._cleaned = True


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


@dataclass(slots=True)
class _Session:
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
    """Own bounded workers and isolated process-local batch sessions."""

    def __init__(
        self,
        *,
        office_engine_factory: OfficeEngineFactory,
        max_workers: int = 2,
        terminal_ttl_seconds: int = 3600,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if type(max_workers) is not int or max_workers <= 0:
            raise ValueError("max_workers must be a positive integer")
        if type(terminal_ttl_seconds) is not int or terminal_ttl_seconds <= 0:
            raise ValueError("terminal_ttl_seconds must be a positive integer")
        self._office_engine_factory = office_engine_factory
        self._terminal_ttl_seconds = terminal_ttl_seconds
        self._clock = clock
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="docuforge-batch"
        )
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()
        self._shutdown = False

    def create_workspace(self) -> BatchSessionWorkspace:
        """Create an unregistered workspace for validated upload storage."""
        return BatchSessionWorkspace()

    def create_session(
        self, request: BatchExecutionRequest, workspace: BatchSessionWorkspace
    ) -> BatchExecutionSnapshot:
        """Register and queue one new batch attempt."""
        if not isinstance(workspace, BatchSessionWorkspace):
            raise TypeError("workspace must be a BatchSessionWorkspace")
        batch = _initial_batch(request)
        session = _Session(
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
            self._sessions[str(batch.id)] = session
            self._executor.submit(self._execute, str(batch.id), False, False)
            return self._snapshot_locked(session)

    def get(self, batch_id: str) -> BatchExecutionSnapshot:
        with self._lock:
            session = self._get_locked(batch_id)
            return self._snapshot_locked(session)

    def cancel(self, batch_id: str) -> BatchExecutionSnapshot:
        with self._lock:
            session = self._get_locked(batch_id)
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
            session.cancellation.request_cancellation()
            session.phase = BatchExecutionPhase.CANCELLING
            session.updated_at = self._clock()
            return self._snapshot_locked(session)

    def recover(self, batch_id: str) -> BatchExecutionSnapshot:
        with self._lock:
            session = self._get_locked(batch_id)
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
                and session.session_error.code == "batch_packaging_failed"
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
            session.attempt += 1
            session.cancellation = BatchCancellationToken()
            session.session_error = None
            session.archive_path = None
            session.workspace.archive_path.unlink(missing_ok=True)
            if packaging_only:
                session.phase = BatchExecutionPhase.QUEUED
            elif selective and session.result is not None:
                session.batch = session.result.batch.recover_items()
                session.phase = BatchExecutionPhase.QUEUED
            else:
                session.result = None
                session.batch = _initial_batch(session.request)
                session.phase = BatchExecutionPhase.QUEUED
            session.updated_at = self._clock()
            self._executor.submit(self._execute, batch_id, selective, packaging_only)
            return self._snapshot_locked(session)

    def download_path(self, batch_id: str) -> Path:
        with self._lock:
            session = self._get_locked(batch_id)
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

    def shutdown(self) -> None:
        """Cooperatively stop work, join workers, and remove every workspace."""
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
            for session in self._sessions.values():
                session.workspace.cleanup()
            self._sessions.clear()

    def _execute(self, batch_id: str, selective: bool, packaging_only: bool) -> None:
        with self._lock:
            session = self._sessions.get(batch_id)
            if session is None:
                return
            attempt = session.attempt
            previous = session.result if selective else None
            if packaging_only:
                result = session.result
            else:
                session.phase = (
                    BatchExecutionPhase.CANCELLING
                    if session.cancellation.cancellation_requested
                    else BatchExecutionPhase.PROCESSING
                )
                session.updated_at = self._clock()
                result = None
        try:
            if not packaging_only:
                result = self._run_request(session, previous, attempt)
                with self._lock:
                    if session.attempt != attempt:
                        return
                    session.result = result
                    session.batch = result.batch
            if result is None:
                raise RuntimeError("batch result missing")
            if result.outputs:
                with self._lock:
                    session.phase = BatchExecutionPhase.PACKAGING
                    session.updated_at = self._clock()
                package_batch_outputs(result, session.workspace.archive_path)
                archive_path: Path | None = session.workspace.archive_path
            else:
                archive_path = None
            with self._lock:
                session.archive_path = archive_path
                session.phase = BatchExecutionPhase.READY
                session.session_error = None
                session.updated_at = self._clock()
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

    def _get_locked(self, batch_id: str) -> _Session:
        self._expire_locked()
        session = self._sessions.get(str(batch_id))
        if session is None:
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
            self._sessions.pop(batch_id).workspace.cleanup()

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

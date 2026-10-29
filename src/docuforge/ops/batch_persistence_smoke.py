"""Verify durable batch sessions survive service recreation."""

from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch
from zipfile import ZipFile

from PIL import Image

from docuforge.api.batch_persistence import BatchPersistenceError
from docuforge.api.batch_storage_lock import BatchStorageOwnershipError
from docuforge.api.batches import BatchExecutionPhase, BatchExecutionService
from docuforge.api.errors import ApiError
from docuforge.batch import (
    BatchImageConvertRequest,
    BatchImageInput,
    BatchProcessingError,
    batch_convert_images,
    package_batch_outputs,
)
from docuforge.converters.office import LibreOfficeEngine


class BatchPersistenceSmokeError(RuntimeError):
    """Safe operational persistence-smoke failure."""


def run_batch_persistence_smoke() -> tuple[str, ...]:
    """Create, restart, and re-read one synthetic durable image batch."""
    configured_root = os.getenv("DOCUFORGE_BATCH_STORAGE_DIRECTORY")
    parent = Path(configured_root) if configured_root else None
    try:
        with tempfile.TemporaryDirectory(
            prefix="docuforge-persistence-smoke-", dir=parent
        ) as directory:
            storage = Path(directory)
            first = BatchExecutionService(
                office_engine_factory=LibreOfficeEngine,
                max_workers=1,
                max_inflight_sessions=1,
                storage_directory=storage,
            )
            try:
                BatchExecutionService(
                    office_engine_factory=LibreOfficeEngine,
                    max_workers=1,
                    storage_directory=storage,
                )
            except BatchStorageOwnershipError:
                pass
            else:
                raise BatchPersistenceSmokeError("competing storage owner was accepted")
            workspace = first.create_workspace()
            try:
                first.create_workspace()
            except ApiError as error:
                if error.status_code != 503 or error.code != "batch_capacity_exceeded":
                    raise BatchPersistenceSmokeError("admission failure was not safe") from None
            else:
                raise BatchPersistenceSmokeError("excess batch admission was accepted")
            item_directory = workspace.inputs_directory / "item-0001"
            item_directory.mkdir()
            source = item_directory / "smoke.png"
            Image.new("RGB", (8, 8), "blue").save(source)
            request = BatchImageConvertRequest(
                (BatchImageInput(source, descriptor="smoke.png"),),
                workspace.output_directory,
                "jpg",
                workspace.batch_id,
            )
            grant = first.create_session(request, workspace)
            _wait_ready(first, str(request.batch_id), grant.access_token)
            _verify_archive(first.download_path(str(request.batch_id), grant.access_token))
            first.shutdown()

            second = BatchExecutionService(
                office_engine_factory=LibreOfficeEngine,
                max_workers=1,
                storage_directory=storage,
            )
            restored = second.get(str(request.batch_id), grant.access_token)
            if restored.phase is not BatchExecutionPhase.READY:
                raise BatchPersistenceSmokeError("restored batch was not ready")
            _verify_archive(second.download_path(str(request.batch_id), grant.access_token))
            try:
                second.get(str(request.batch_id), "wrong-token")
            except ApiError as error:
                if error.status_code != 404 or error.code != "batch_not_found":
                    raise BatchPersistenceSmokeError(
                        "wrong token was not safely rejected"
                    ) from None
            else:
                raise BatchPersistenceSmokeError("wrong token was accepted")
            normal = second.acquire_download(str(request.batch_id), grant.access_token)
            normal.release()
            session = second._sessions[str(request.batch_id)]
            result, updated_at = session.result, session.updated_at
            workspace.archive_path.write_bytes(b"not a zip")
            try:
                second.acquire_download(str(request.batch_id), grant.access_token)
            except ApiError as error:
                if (error.status_code, error.code) != (409, "batch_packaging_failed"):
                    raise BatchPersistenceSmokeError("archive rejection was unsafe") from None
            else:
                raise BatchPersistenceSmokeError("invalid archive was accepted")
            if (
                second._active_downloads
                or session.phase is not BatchExecutionPhase.ERROR
                or session.result is not result
                or session.archive_path is not None
                or session.updated_at != updated_at
                or result is None
                or not all(output.output_path.is_file() for output in result.outputs)
            ):
                raise BatchPersistenceSmokeError("archive failure lost retained results")
            second.recover(str(request.batch_id), grant.access_token)
            _wait_ready(second, str(request.batch_id), grant.access_token)
            if session.result is not result:
                raise BatchPersistenceSmokeError("archive recovery repeated conversion")
            output = session.result.outputs[0].output_path
            second.shutdown()
            output.write_bytes(b"not an image")
            second = BatchExecutionService(
                office_engine_factory=LibreOfficeEngine,
                max_workers=1,
                storage_directory=storage,
            )
            restored = second.get(str(request.batch_id), grant.access_token)
            session = second._sessions[str(request.batch_id)]
            if (
                restored.phase is not BatchExecutionPhase.ERROR
                or restored.session_error is None
                or restored.session_error.code != "batch_output_integrity_failed"
                or session.result is not None
            ):
                raise BatchPersistenceSmokeError("untrusted output was not recoverable")
            second.recover(str(request.batch_id), grant.access_token)
            _wait_ready(second, str(request.batch_id), grant.access_token)
            with Image.open(session.result.outputs[0].output_path) as image:
                image.load()
            _verify_archive(second.download_path(str(request.batch_id), grant.access_token))
            handle = second.acquire_download(str(request.batch_id), grant.access_token)
            try:
                second.delete_session(str(request.batch_id), grant.access_token)
                _verify_archive(handle.path)
                if not workspace.path.exists():
                    raise BatchPersistenceSmokeError("pinned workspace was removed")
                try:
                    second.get(str(request.batch_id), grant.access_token)
                except ApiError as error:
                    if error.code != "batch_not_found":
                        raise BatchPersistenceSmokeError("pinned deletion was not hidden") from None
                else:
                    raise BatchPersistenceSmokeError("pinned deletion remained accessible")
            finally:
                handle.release()
            if str(request.batch_id) in second._sessions:
                raise BatchPersistenceSmokeError("released deletion remained in memory")
            if workspace.path.exists():
                raise BatchPersistenceSmokeError("deleted workspace remained")
            repository = second._repository
            if repository is None or repository.get(str(request.batch_id)) is not None:
                raise BatchPersistenceSmokeError("deleted metadata remained")
            try:
                second.get(str(request.batch_id), grant.access_token)
            except ApiError as error:
                if error.status_code != 404 or error.code != "batch_not_found":
                    raise BatchPersistenceSmokeError("deleted batch was not hidden") from None
            else:
                raise BatchPersistenceSmokeError("deleted batch remained accessible")
            second.shutdown()
            _verify_idle_expiry(storage)
            _verify_storage_pressure(storage)
            _verify_output_budget(storage)
            _verify_worker_publication(storage)
            _verify_input_integrity(storage)
            _verify_archive_source_pinning(storage)
            _verify_download_descriptor_pinning(storage)
    except BatchPersistenceSmokeError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise BatchPersistenceSmokeError("batch-session-restart check failed") from error
    return (
        "batch-storage-owner-lock",
        "batch-admission-control",
        "batch-session-restart",
        "batch-session-delete",
        "batch-ttl-sweeper",
        "batch-storage-pressure",
        "batch-output-budget",
        "batch-download-lifecycle",
        "batch-archive-integrity",
        "batch-output-integrity",
        "batch-worker-publication",
        "batch-input-integrity",
        "batch-archive-source-pinning",
        "batch-download-descriptor-pinning",
    )


def _verify_download_descriptor_pinning(storage: Path) -> None:
    """Validate, pin and transmit one synthetic ZIP without a second pathname open."""
    from docuforge.api.routes.batches import _PinnedFileResponse

    runner = BatchExecutionService(office_engine_factory=LibreOfficeEngine, storage_directory=storage)
    handle = None
    try:
        workspace = runner.create_workspace()
        source = workspace.inputs_directory / "descriptor-smoke.png"
        Image.new("RGB", (8, 8), "green").save(source)
        request = BatchImageConvertRequest(
            (BatchImageInput(source),), workspace.output_directory, "jpg", workspace.batch_id,
        )
        grant = runner.create_session(request, workspace)
        batch_id, token = str(request.batch_id), grant.access_token
        _wait_ready(runner, batch_id, token)
        handle = runner.acquire_download(batch_id, token)
        identity = os.fstat(handle.reader.fileno())
        original = handle.read_chunk(0, handle.size_bytes)
        if (identity.st_dev, identity.st_ino, identity.st_size) != (
            handle.stat_result.st_dev, handle.stat_result.st_ino, handle.size_bytes,
        ):
            raise BatchPersistenceSmokeError("download descriptor identity changed")
        try:
            workspace.archive_path.rename(workspace.path / "original.zip")
        except PermissionError:
            pass  # Windows may deny replacing an open file; the open-rejection seam still runs.
        else:
            workspace.archive_path.write_bytes(b"SYNTHETIC UNVALIDATED REPLACEMENT")
        response = _PinnedFileResponse(handle, media_type="application/zip")
        messages = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.pathsend":
                raise BatchPersistenceSmokeError("download attempted pathsend")
            messages.append(message)

        with patch("anyio.open_file", side_effect=BatchPersistenceSmokeError("download reopened path")):
            asyncio.run(response(
                {"type": "http", "method": "GET", "headers": [],
                 "asgi": {"spec_version": "2.4"}, "extensions": {"http.response.pathsend": {}}},
                receive, send,
            ))
        transmitted = b"".join(message.get("body", b"") for message in messages)
        if (messages[0]["status"] != 200 or transmitted != original
                or not handle.reader.closed or runner._active_downloads):
            raise BatchPersistenceSmokeError("download did not retain the validated descriptor")
        with ZipFile(io.BytesIO(transmitted)) as archive:
            if archive.testzip() is not None or len(archive.namelist()) != 1:
                raise BatchPersistenceSmokeError("download descriptor ZIP was invalid")
        runner.delete_session(batch_id, token)
        if workspace.path.exists():
            raise BatchPersistenceSmokeError("released download did not permit deletion")
    finally:
        if handle is not None:
            handle.release()
        runner.shutdown()


def _verify_archive_source_pinning(storage: Path) -> None:
    """Reject a controlled source swap, retaining a previously valid synthetic ZIP."""
    from docuforge.batch import archive as packaging

    with tempfile.TemporaryDirectory(prefix="archive-source-smoke-", dir=storage) as directory:
        root = Path(directory)
        source = root / "smoke.png"
        Image.new("RGB", (8, 8), "blue").save(source)
        outputs = root / "outputs"
        outputs.mkdir()
        result = batch_convert_images(BatchImageConvertRequest(
            (BatchImageInput(source),), outputs, "jpg",
        ))
        destination = root / "result.zip"
        package_batch_outputs(result, destination)
        previous = destination.read_bytes()
        output = result.outputs[0].output_path
        with ZipFile(destination) as archive:
            if (archive.namelist() != [output.name] or archive.testzip() is not None
                    or archive.read(output.name) != output.read_bytes()):
                raise BatchPersistenceSmokeError("source pinning stable ZIP was invalid")
        sentinel = root / "external-sentinel"
        sentinel.write_bytes(b"SYNTHETIC EXTERNAL SENTINEL")
        opening = packaging._open_verified_archive_source
        injected = []

        def replace_before_open(reference):
            output.rename(outputs / "original")
            # A regular replacement is portable on Windows and POSIX and checks
            # descriptor identity without needing privileged symlink creation.
            output.write_bytes(sentinel.read_bytes())
            injected.append(True)
            return opening(reference)

        with patch.object(packaging, "_open_verified_archive_source", replace_before_open):
            try:
                package_batch_outputs(result, destination)
            except BatchProcessingError as error:
                if str(error) != "Unable to package the batch outputs.":
                    raise BatchPersistenceSmokeError("source pinning failure was unsafe") from None
            else:
                raise BatchPersistenceSmokeError("replaced archive source was accepted")
        if (not injected or destination.read_bytes() != previous
                or sentinel.read_bytes() != b"SYNTHETIC EXTERNAL SENTINEL"
                or list(root.glob(".docuforge-batch-archive-*"))):
            raise BatchPersistenceSmokeError("source pinning did not preserve the prior ZIP")
        with ZipFile(destination) as archive:
            if archive.testzip() is not None or archive.read(output.name) == sentinel.read_bytes():
                raise BatchPersistenceSmokeError("untrusted source bytes were published")


def _verify_input_integrity(storage: Path) -> None:
    """Refuse same-size altered uploads after restart, then retry exact originals."""
    first = BatchExecutionService(
        office_engine_factory=LibreOfficeEngine, storage_directory=storage,
        max_published_output_bytes=1,
    )
    try:
        workspace = first.create_workspace()
        source = workspace.inputs_directory / "smoke.png"
        Image.new("RGB", (8, 8), "blue").save(source)
        original = source.read_bytes()
        request = BatchImageConvertRequest(
            (BatchImageInput(source),), workspace.output_directory, "jpg", workspace.batch_id,
        )
        grant = first.create_session(request, workspace)
        batch_id, token = str(request.batch_id), grant.access_token
        _wait_ready(first, batch_id, token)
        if first.get(batch_id, token).batch.items[0].failure.code != "batch_output_limit_exceeded":
            raise BatchPersistenceSmokeError("input integrity fixture did not reach policy failure")
    finally:
        first.shutdown()
    source.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    second = BatchExecutionService(office_engine_factory=LibreOfficeEngine, storage_directory=storage)
    try:
        before = second._repository.get(batch_id)
        attempt = second.get(batch_id, token).attempt
        outputs = tuple(workspace.output_directory.iterdir())
        try:
            second.recover(batch_id, token)
        except ApiError as error:
            if (error.status_code, error.code, error.message) != (
                409, "batch_input_integrity_failed", "The original batch inputs could not be verified.",
            ):
                raise BatchPersistenceSmokeError("input integrity rejection was unsafe") from None
        else:
            raise BatchPersistenceSmokeError("changed original input was accepted")
        if (
            second._repository.get(batch_id) != before
            or second.get(batch_id, token).attempt != attempt
            or tuple(workspace.output_directory.iterdir()) != outputs
            or workspace.archive_path.exists() or second._admitted_batch_ids
        ):
            raise BatchPersistenceSmokeError("input integrity rejection changed batch state")
        source.write_bytes(original)
        second.recover(batch_id, token)
        _wait_ready(second, batch_id, token)
        _verify_archive(second.download_path(batch_id, token))
        second.delete_session(batch_id, token)
    finally:
        second.shutdown()


def _verify_worker_publication(storage: Path) -> None:
    """Reject one READY save and prove publication waits for durable state."""
    runner = BatchExecutionService(
        office_engine_factory=LibreOfficeEngine,
        max_workers=1,
        storage_directory=storage,
    )
    try:
        for fail_ready in (False, True):
            workspace = runner.create_workspace()
            source = workspace.inputs_directory / "smoke.png"
            Image.new("RGB", (8, 8), "blue").save(source)
            request = BatchImageConvertRequest(
                (BatchImageInput(source),),
                workspace.output_directory,
                "jpg",
                workspace.batch_id,
            )
            repository = runner._repository
            save = repository.save
            rejected = False

            def persist(row, *, fail_ready=fail_ready, save=save):
                nonlocal rejected
                live = runner._sessions[row.batch_id]
                if row.phase == "ready" and fail_ready and not rejected:
                    if (
                        live.phase is not BatchExecutionPhase.PACKAGING
                        or live.archive_path is not None
                    ):
                        raise BatchPersistenceSmokeError("worker published before persistence")
                    rejected = True
                    raise BatchPersistenceError("Controlled worker checkpoint failure.")
                save(row)

            with patch.object(repository, "save", side_effect=persist):
                grant = runner.create_session(request, workspace)
                batch_id, token = str(request.batch_id), grant.access_token
                if fail_ready:
                    _wait_ready(runner, batch_id, token, phase=BatchExecutionPhase.ERROR)
                else:
                    _wait_ready(runner, batch_id, token)
            session = runner._sessions[batch_id]
            row = repository.get(batch_id)
            if row.phase != session.phase.value or row.updated_at != session.updated_at:
                raise BatchPersistenceSmokeError("worker state did not match durable commit")
            if fail_ready:
                if not rejected or session.archive_path is not None or runner._admitted_batch_ids:
                    raise BatchPersistenceSmokeError("failed worker checkpoint was published")
                retained = session.result
                runner.recover(batch_id, token)
                _wait_ready(runner, batch_id, token)
                if session.result is not retained:
                    raise BatchPersistenceSmokeError(
                        "worker checkpoint recovery repeated conversion"
                    )
            if repository.get(batch_id).phase != "ready":
                raise BatchPersistenceSmokeError("worker recovery was not committed")
            _verify_archive(runner.download_path(batch_id, token))
            runner.delete_session(batch_id, token)
    finally:
        runner.shutdown()


def _verify_output_budget(storage: Path) -> None:
    """Persist an item policy failure, then recover with a larger deployment cap."""
    first = BatchExecutionService(
        office_engine_factory=LibreOfficeEngine,
        storage_directory=storage,
        max_published_output_bytes=1,
    )
    try:
        workspace = first.create_workspace()
        source = workspace.inputs_directory / "smoke.png"
        Image.new("RGB", (8, 8), "blue").save(source)
        request = BatchImageConvertRequest(
            (BatchImageInput(source),), workspace.output_directory, "jpg", workspace.batch_id
        )
        grant = first.create_session(request, workspace)
        batch_id, token = str(request.batch_id), grant.access_token
        _wait_ready(first, batch_id, token)
        snapshot = first.get(batch_id, token)
        if (
            snapshot.batch.status.value != "failed"
            or snapshot.batch.items[0].failure.code != "batch_output_limit_exceeded"
            or snapshot.session_error is not None
            or snapshot.can_download
            or not snapshot.can_recover
            or any(workspace.output_directory.iterdir())
            or workspace.archive_path.exists()
        ):
            raise BatchPersistenceSmokeError("output budget did not isolate item failure")
    finally:
        first.shutdown()
    second = BatchExecutionService(
        office_engine_factory=LibreOfficeEngine,
        storage_directory=storage,
        max_published_output_bytes=1024 * 1024,
    )
    try:
        second.recover(batch_id, token)
        _wait_ready(second, batch_id, token)
        snapshot = second.get(batch_id, token)
        if snapshot.batch.status.value != "completed" or snapshot.session_error is not None:
            raise BatchPersistenceSmokeError("output budget recovery failed")
        _verify_archive(second.download_path(batch_id, token))
        second.delete_session(batch_id, token)
    finally:
        second.shutdown()


def _verify_storage_pressure(storage: Path) -> None:
    free = [0]
    service = BatchExecutionService(
        office_engine_factory=LibreOfficeEngine,
        storage_directory=storage,
        min_free_storage_bytes=10,
        max_upload_request_bytes=10,
        free_storage_bytes=lambda _root: free[0],
    )
    try:
        try:
            service.create_workspace()
        except ApiError as error:
            if (
                error.status_code != 507 or error.code != "batch_storage_pressure"
                or error.message != "Batch storage is temporarily full. Try again later."
            ):
                raise BatchPersistenceSmokeError("storage pressure was not safely rejected") from None
        else:
            raise BatchPersistenceSmokeError("insufficient storage was accepted")
        if service._admitted_batch_ids or any(service._sessions_root.iterdir()):
            raise BatchPersistenceSmokeError("rejected storage admission retained a workspace")
        free[0] = 20
        workspace = service.create_workspace()
        service.abandon_workspace(workspace)
    finally:
        service.shutdown()


def _verify_idle_expiry(storage: Path) -> None:
    """Observe autonomous removal without invoking access-triggered expiry."""
    service = BatchExecutionService(
        office_engine_factory=LibreOfficeEngine,
        max_workers=1,
        storage_directory=storage,
        terminal_ttl_seconds=2,
        cleanup_interval_seconds=1,
    )
    try:
        workspace = service.create_workspace()
        item_directory = workspace.inputs_directory / "item-0001"
        item_directory.mkdir()
        source = item_directory / "smoke.png"
        Image.new("RGB", (8, 8), "blue").save(source)
        request = BatchImageConvertRequest(
            (BatchImageInput(source, descriptor="smoke.png"),),
            workspace.output_directory,
            "jpg",
            workspace.batch_id,
        )
        grant = service.create_session(request, workspace)
        batch_id = str(request.batch_id)
        _wait_ready(service, batch_id, grant.access_token)
        deadline = monotonic() + 10
        while monotonic() < deadline:
            with service._lock:
                removed = batch_id not in service._sessions
            if removed:
                if workspace.path.exists() or service._repository.get(batch_id) is not None:
                    raise BatchPersistenceSmokeError("expired batch storage remained")
                return
            sleep(0.02)
        raise BatchPersistenceSmokeError("idle batch retention did not complete")
    finally:
        service.shutdown()


def _wait_ready(
    service: BatchExecutionService,
    batch_id: str,
    access_token: str,
    *,
    phase: BatchExecutionPhase = BatchExecutionPhase.READY,
) -> None:
    deadline = monotonic() + 15
    while monotonic() < deadline:
        snapshot = service.get(batch_id, access_token)
        if snapshot.phase is phase:
            return
        if snapshot.phase is BatchExecutionPhase.ERROR:
            raise BatchPersistenceSmokeError("batch execution failed")
        sleep(0.02)
    raise BatchPersistenceSmokeError("batch execution did not finish")


def _verify_archive(path: Path) -> None:
    try:
        with ZipFile(path) as archive:
            if archive.namelist() != ["0001-smoke.jpg"] or archive.testzip() is not None:
                raise BatchPersistenceSmokeError("batch archive was invalid")
    except OSError as error:
        raise BatchPersistenceSmokeError("batch archive was unavailable") from error


def main() -> int:
    try:
        checks = run_batch_persistence_smoke()
    except BatchPersistenceSmokeError:
        print("FAIL durable batch persistence check failed", file=sys.stderr)
        return 1
    for check in checks:
        print(f"PASS {check}")
    suffix = "check" if len(checks) == 1 else "checks"
    print(f"Durable batch persistence smoke passed: {len(checks)} {suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

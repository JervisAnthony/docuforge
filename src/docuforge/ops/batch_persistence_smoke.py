"""Verify durable batch sessions survive service recreation."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from time import monotonic, sleep
from zipfile import ZipFile

from PIL import Image

from docuforge.api.batch_storage_lock import BatchStorageOwnershipError
from docuforge.api.batches import BatchExecutionPhase, BatchExecutionService
from docuforge.api.errors import ApiError
from docuforge.batch import BatchImageConvertRequest, BatchImageInput
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
                    raise BatchPersistenceSmokeError("wrong token was not safely rejected") from None
            else:
                raise BatchPersistenceSmokeError("wrong token was accepted")
            second.delete_session(str(request.batch_id), grant.access_token)
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
    except BatchPersistenceSmokeError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise BatchPersistenceSmokeError("batch-session-restart check failed") from error
    return (
        "batch-storage-owner-lock",
        "batch-admission-control",
        "batch-session-restart",
        "batch-session-delete",
    )


def _wait_ready(
    service: BatchExecutionService, batch_id: str, access_token: str
) -> None:
    deadline = monotonic() + 15
    while monotonic() < deadline:
        snapshot = service.get(batch_id, access_token)
        if snapshot.phase is BatchExecutionPhase.READY:
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

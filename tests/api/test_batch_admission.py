"""Bounded process-local batch admission coverage."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import docuforge.api.batches as batches_module
from docuforge.api import ApiSettings, create_app
from docuforge.api.batch_persistence import (
    BatchPersistenceError,
    BatchSessionWorkspace,
)
from docuforge.api.batches import BatchExecutionPhase, BatchExecutionService
from docuforge.api.errors import ApiError
from docuforge.batch import BatchImageConvertRequest, BatchImageInput
from tests.api.image_test_support import make_image
from tests.batch.test_document import RecordingEngine
from tests.batch.test_image_processing import write_image


def service(
    *, max_inflight_sessions: int = 1, storage_directory: Path | None = None
) -> BatchExecutionService:
    return BatchExecutionService(
        office_engine_factory=RecordingEngine,
        max_workers=1,
        max_inflight_sessions=max_inflight_sessions,
        storage_directory=storage_directory,
    )


def request_for(
    runner: BatchExecutionService, name: str = "one.png"
) -> tuple[BatchSessionWorkspace, BatchImageConvertRequest]:
    workspace = runner.create_workspace()
    item_directory = workspace.inputs_directory / "item-0001"
    item_directory.mkdir()
    source = item_directory / name
    write_image(source)
    request = BatchImageConvertRequest(
        (BatchImageInput(source, descriptor=name),),
        workspace.output_directory,
        "jpg",
        workspace.batch_id,
    )
    return workspace, request


def wait_for_phase(
    runner: BatchExecutionService,
    batch_id: str,
    access_token: str,
    phase: BatchExecutionPhase,
) -> object:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        snapshot = runner.get(batch_id, access_token)
        if snapshot.phase is phase:
            return snapshot
        sleep(0.01)
    raise AssertionError(f"batch did not reach {phase.value}")


def assert_capacity_error(error: ApiError) -> None:
    assert (error.status_code, error.code, error.message) == (
        503,
        "batch_capacity_exceeded",
        "The batch service is temporarily at capacity. Try again later.",
    )


@pytest.mark.parametrize(
    ("workers", "inflight"),
    [(1, 0), (1, -1), (1, True), (1, 1.5), (1, "1"), (2, 1)],
)
def test_service_rejects_invalid_admission_configuration(
    workers: int, inflight: object
) -> None:
    with pytest.raises(ValueError):
        BatchExecutionService(
            office_engine_factory=RecordingEngine,
            max_workers=workers,
            max_inflight_sessions=inflight,  # type: ignore[arg-type]
        )


def test_preparing_workspace_reserves_capacity_before_another_workspace(
    tmp_path: Path,
) -> None:
    runner = service(storage_directory=tmp_path)
    workspace = runner.create_workspace()
    created = {path.name for path in (tmp_path / "sessions").iterdir()}
    with pytest.raises(ApiError) as captured:
        runner.create_workspace()
    assert_capacity_error(captured.value)
    assert {path.name for path in (tmp_path / "sessions").iterdir()} == created
    assert runner._admitted_batch_ids == {str(workspace.batch_id)}
    runner.abandon_workspace(workspace)
    runner.shutdown()


def test_abandonment_is_idempotent_and_releases_capacity() -> None:
    runner = service()
    workspace = runner.create_workspace()
    runner.abandon_workspace(workspace)
    runner.abandon_workspace(workspace)
    replacement = runner.create_workspace()
    assert runner._admitted_batch_ids == {str(replacement.batch_id)}
    runner.abandon_workspace(replacement)
    runner.shutdown()


def test_workspace_creation_failure_releases_preparation_reservation() -> None:
    runner = service()
    with (
        patch.object(
            BatchSessionWorkspace,
            "ephemeral",
            side_effect=BatchPersistenceError("private"),
        ),
        pytest.raises(BatchPersistenceError),
    ):
        runner.create_workspace()
    assert not runner._admitted_batch_ids
    replacement = runner.create_workspace()
    runner.abandon_workspace(replacement)
    runner.shutdown()


def test_create_session_rejects_unreserved_workspace() -> None:
    runner = service()
    workspace = BatchSessionWorkspace.ephemeral()
    item_directory = workspace.inputs_directory / "item-0001"
    item_directory.mkdir()
    source = item_directory / "one.png"
    write_image(source)
    request = BatchImageConvertRequest(
        (BatchImageInput(source, descriptor="one.png"),),
        workspace.output_directory,
        "jpg",
        workspace.batch_id,
    )
    with pytest.raises(ValueError, match="does not own execution admission"):
        runner.create_session(request, workspace)
    workspace.cleanup()
    runner.shutdown()


def test_creation_submission_failure_never_touches_durable_state(tmp_path: Path) -> None:
    runner = service(storage_directory=tmp_path)
    repository = runner._repository
    assert repository is not None
    workspace, request = request_for(runner)
    batch_id = str(request.batch_id)
    with (
        patch.object(repository, "add", wraps=repository.add) as add,
        patch.object(repository, "delete", wraps=repository.delete) as delete,
        patch.object(runner._executor, "submit", side_effect=RuntimeError("private")),
        pytest.raises(ApiError) as captured,
    ):
        runner.create_session(request, workspace)
    assert captured.value.code == "batch_persistence_failed"
    add.assert_not_called()
    delete.assert_not_called()
    assert repository.get(batch_id) is None
    assert batch_id not in runner._sessions
    assert not workspace.path.exists()
    assert not runner._admitted_batch_ids
    replacement = runner.create_workspace()
    runner.abandon_workspace(replacement)
    runner.shutdown()

    restarted = service(storage_directory=tmp_path)
    assert restarted._repository is not None
    assert restarted._repository.get(batch_id) is None
    assert batch_id not in restarted._sessions
    replacement = restarted.create_workspace()
    restarted.abandon_workspace(replacement)
    restarted.shutdown()


def test_creation_persistence_failure_stops_submitted_worker(tmp_path: Path) -> None:
    runner = service(storage_directory=tmp_path)
    repository = runner._repository
    assert repository is not None
    workspace, request = request_for(runner)
    batch_id = str(request.batch_id)
    with patch.object(batches_module, "batch_convert_images") as converter:
        with (
            patch.object(repository, "add", side_effect=BatchPersistenceError("private")),
            pytest.raises(ApiError) as captured,
        ):
            runner.create_session(request, workspace)
        assert captured.value.code == "batch_persistence_failed"
        assert repository.get(batch_id) is None
        assert batch_id not in runner._sessions
        assert not workspace.path.exists()
        assert not runner._admitted_batch_ids
        runner.shutdown()
        converter.assert_not_called()

    restarted = service(storage_directory=tmp_path)
    assert restarted._repository is not None
    assert restarted._repository.get(batch_id) is None
    assert batch_id not in restarted._sessions
    restarted.shutdown()


def test_ready_and_error_release_admission() -> None:
    runner = service()
    workspace, request = request_for(runner)
    grant = runner.create_session(request, workspace)
    wait_for_phase(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    replacement = runner.create_workspace()
    runner.abandon_workspace(replacement)

    workspace, request = request_for(runner)
    with patch.object(batches_module, "batch_convert_images", side_effect=RuntimeError("private")):
        grant = runner.create_session(request, workspace)
        wait_for_phase(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.ERROR)
    replacement = runner.create_workspace()
    runner.abandon_workspace(replacement)
    runner.shutdown()


def test_terminal_error_persistence_failure_still_releases_admission(
    tmp_path: Path,
) -> None:
    runner = service(storage_directory=tmp_path)
    workspace, request = request_for(runner)
    repository = runner._repository
    assert repository is not None
    with patch.object(repository, "save", side_effect=BatchPersistenceError("private")):
        grant = runner.create_session(request, workspace)
        failed = wait_for_phase(
            runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.ERROR
        )
    assert failed.session_error is not None
    assert failed.session_error.code == "batch_persistence_failed"
    replacement = runner.create_workspace()
    runner.abandon_workspace(replacement)
    runner.shutdown()


def test_cancelling_and_packaging_continue_to_occupy_admission() -> None:
    runner = service()
    workspace, request = request_for(runner)
    entered = Event()
    release = Event()
    real_runner = batches_module.batch_convert_images

    def blocked_execution(*args: object, **kwargs: object) -> object:
        entered.set()
        assert release.wait(5)
        return real_runner(*args, **kwargs)  # type: ignore[arg-type]

    with patch.object(batches_module, "batch_convert_images", side_effect=blocked_execution):
        grant = runner.create_session(request, workspace)
        assert entered.wait(5)
        runner.cancel(str(request.batch_id), grant.access_token)
        with pytest.raises(ApiError) as cancelling:
            runner.create_workspace()
        assert_capacity_error(cancelling.value)
        release.set()
        wait_for_phase(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)

    workspace, request = request_for(runner)
    entered.clear()
    release.clear()
    real_packager = batches_module.package_batch_outputs

    def blocked_packaging(*args: object, **kwargs: object) -> object:
        entered.set()
        assert release.wait(5)
        return real_packager(*args, **kwargs)  # type: ignore[arg-type]

    with patch.object(batches_module, "package_batch_outputs", side_effect=blocked_packaging):
        grant = runner.create_session(request, workspace)
        assert entered.wait(5)
        assert runner.get(str(request.batch_id), grant.access_token).phase is BatchExecutionPhase.PACKAGING
        with pytest.raises(ApiError) as packaging:
            runner.create_workspace()
        assert_capacity_error(packaging.value)
        release.set()
        wait_for_phase(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    runner.shutdown()


def test_recovery_saturation_is_atomic_and_recovery_works_after_capacity_frees() -> None:
    runner = service()
    workspace, request = request_for(runner)
    request.items[0].input_path.unlink()
    grant = runner.create_session(request, workspace)
    before = wait_for_phase(
        runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY
    )
    blocker = runner.create_workspace()
    with pytest.raises(ApiError) as captured:
        runner.recover(str(request.batch_id), grant.access_token)
    assert_capacity_error(captured.value)
    assert runner.get(str(request.batch_id), grant.access_token) == before
    runner.abandon_workspace(blocker)
    write_image(request.items[0].input_path)
    assert runner.recover(str(request.batch_id), grant.access_token).attempt == 2
    wait_for_phase(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    runner.shutdown()


def test_recovery_persistence_failure_preserves_durable_terminal_state(
    tmp_path: Path,
) -> None:
    runner = service(storage_directory=tmp_path)
    workspace, request = request_for(runner)
    with patch.object(
        batches_module, "package_batch_outputs", side_effect=RuntimeError("private")
    ):
        grant = runner.create_session(request, workspace)
        before = wait_for_phase(
            runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.ERROR
        )
    repository = runner._repository
    assert repository is not None
    batch_id = str(request.batch_id)
    before_record = repository.get(batch_id)
    assert before_record is not None
    with patch.object(batches_module, "package_batch_outputs") as packager:
        with (
            patch.object(
                repository, "save", side_effect=BatchPersistenceError("private")
            ) as save,
            pytest.raises(ApiError) as captured,
        ):
            runner.recover(batch_id, grant.access_token)
        assert captured.value.code == "batch_persistence_failed"
        assert repository.get(batch_id) == before_record
        assert runner.get(batch_id, grant.access_token) == before
        assert not runner._admitted_batch_ids
        runner.shutdown()
        packager.assert_not_called()
        save.assert_called_once()

    restarted = service(storage_directory=tmp_path)
    assert restarted._repository is not None
    assert restarted._repository.get(batch_id) == before_record
    assert restarted.get(batch_id, grant.access_token) == before
    replacement = restarted.create_workspace()
    restarted.abandon_workspace(replacement)
    restarted.shutdown()


def test_recovery_submission_failure_never_writes_candidate(tmp_path: Path) -> None:
    runner = service(storage_directory=tmp_path)
    workspace, request = request_for(runner)
    with patch.object(
        batches_module, "package_batch_outputs", side_effect=RuntimeError("private")
    ):
        grant = runner.create_session(request, workspace)
        before = wait_for_phase(
            runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.ERROR
        )
    repository = runner._repository
    assert repository is not None
    batch_id = str(request.batch_id)
    before_record = repository.get(batch_id)
    assert before_record is not None
    with (
        patch.object(repository, "save", wraps=repository.save) as save,
        patch.object(runner._executor, "submit", side_effect=RuntimeError("private")),
        pytest.raises(ApiError) as captured,
    ):
        runner.recover(batch_id, grant.access_token)
    assert captured.value.code == "batch_persistence_failed"
    save.assert_not_called()
    assert repository.get(batch_id) == before_record
    assert runner.get(batch_id, grant.access_token) == before
    assert not runner._admitted_batch_ids
    replacement = runner.create_workspace()
    runner.abandon_workspace(replacement)
    runner.shutdown()

    restarted = service(storage_directory=tmp_path)
    assert restarted._repository is not None
    assert restarted._repository.get(batch_id) == before_record
    assert restarted.get(batch_id, grant.access_token) == before
    restarted.shutdown()


def test_stale_attempt_worker_does_nothing_and_preserves_other_admission() -> None:
    runner = service()
    workspace, request = request_for(runner)
    with patch.object(
        batches_module, "package_batch_outputs", side_effect=RuntimeError("private")
    ):
        grant = runner.create_session(request, workspace)
        before = wait_for_phase(
            runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.ERROR
        )
    blocker = runner.create_workspace()
    admitted = {str(blocker.batch_id)}
    with (
        patch.object(batches_module, "batch_convert_images") as converter,
        patch.object(batches_module, "package_batch_outputs") as packager,
    ):
        runner._execute(str(request.batch_id), False, True, before.attempt + 1)
    converter.assert_not_called()
    packager.assert_not_called()
    assert runner.get(str(request.batch_id), grant.access_token) == before
    assert runner._admitted_batch_ids == admitted
    runner.abandon_workspace(blocker)
    runner.shutdown()


def test_restart_restores_interrupted_session_without_consuming_admission(
    tmp_path: Path,
) -> None:
    first = service(storage_directory=tmp_path)
    workspace, request = request_for(first)
    grant = first.create_session(request, workspace)
    wait_for_phase(first, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    repository = first._repository
    assert repository is not None
    record = repository.get(str(request.batch_id))
    assert record is not None
    repository.save(replace(record, phase="processing"))
    first.shutdown()

    second = service(storage_directory=tmp_path)
    restored = second.get(str(request.batch_id), grant.access_token)
    assert restored.phase is BatchExecutionPhase.ERROR
    assert restored.session_error is not None
    assert restored.session_error.code == "batch_execution_interrupted"
    assert not second._admitted_batch_ids
    replacement = second.create_workspace()
    second.abandon_workspace(replacement)
    second.shutdown()


def test_shutdown_clears_bookkeeping_and_rejects_new_admission() -> None:
    runner = service()
    workspace = runner.create_workspace()
    runner.shutdown()
    assert not runner._admitted_batch_ids
    assert workspace.path.exists()
    with pytest.raises(RuntimeError, match="shut down"):
        runner.create_workspace()
    workspace.cleanup()


@pytest.mark.parametrize(
    ("path", "files"),
    [
        (
            "/api/v1/batches/images/convert",
            [
                ("file", ("bad.txt", b"bad", "text/plain")),
                ("format", (None, "jpg", None)),
            ],
        ),
        ("/api/v1/batches/office/to-pdf", [("file", ("bad.txt", b"bad", "text/plain"))]),
    ],
)
def test_route_upload_failure_releases_preparation_reservation(
    path: str, files: list[tuple[str, tuple[str | None, bytes | str, str | None]]]
) -> None:
    settings = ApiSettings(batch_max_workers=1, batch_max_inflight_sessions=1)
    app = create_app(settings, office_engine_factory=RecordingEngine)
    with TestClient(app) as client:
        rejected = client.post(path, files=files)
        assert rejected.status_code == 415
        assert not app.state.batch_service._admitted_batch_ids
        accepted = client.post(
            "/api/v1/batches/images/convert",
            files=[("file", ("one.png", make_image(), "image/png")), ("format", (None, "jpg"))],
        )
        assert accepted.status_code == 202


def test_http_capacity_error_is_safe_immediate_and_creates_no_workspace(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "durable"
    settings = ApiSettings(
        batch_max_workers=1,
        batch_max_inflight_sessions=1,
        batch_storage_directory=storage,
    )
    app = create_app(settings)
    runner = app.state.batch_service
    blocker = runner.create_workspace()
    existing = {path.name for path in (storage / "sessions").iterdir()}
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/batches/images/convert",
            files=[("file", ("one.png", make_image(), "image/png")), ("format", (None, "jpg"))],
        )
        assert response.status_code == 503
        assert response.json() == {
            "code": "batch_capacity_exceeded",
            "message": "The batch service is temporarily at capacity. Try again later.",
        }
        assert "retry-after" not in response.headers
        assert {path.name for path in (storage / "sessions").iterdir()} == existing
        openapi = app.openapi()
        creation = openapi["paths"]["/api/v1/batches/images/convert"]["post"]
        recovery = openapi["paths"]["/api/v1/batches/{batch_id}/recover"]["post"]
        assert "503" in creation["responses"]
        assert "503" in recovery["responses"]
    runner.abandon_workspace(blocker)

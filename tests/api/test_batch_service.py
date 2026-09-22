"""Process-local batch execution service lifecycle coverage."""

from pathlib import Path
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

import pytest

import docuforge.api.batches as batches_module
import docuforge.batch.image as image_module
from docuforge.api.batch_persistence import BatchPersistenceError
from docuforge.api.batches import BatchExecutionPhase, BatchExecutionService
from docuforge.api.errors import ApiError
from docuforge.batch import (
    BatchImageConvertRequest,
    BatchImageInput,
    BatchProcessingError,
    BatchStatus,
)
from tests.batch.test_document import RecordingEngine
from tests.batch.test_image_processing import write_image


def service(**kwargs: object) -> BatchExecutionService:
    return BatchExecutionService(
        office_engine_factory=RecordingEngine,
        max_workers=1,
        **kwargs,  # type: ignore[arg-type]
    )


def create_request(
    runner: BatchExecutionService, names: tuple[str, ...] = ("one.png", "two.png")
) -> tuple[object, BatchImageConvertRequest]:
    workspace = runner.create_workspace()
    items = []
    for position, name in enumerate(names, start=1):
        item_dir = workspace.inputs_directory / f"item-{position:04d}"
        item_dir.mkdir()
        path = item_dir / name
        write_image(path)
        items.append(BatchImageInput(path, descriptor=name))
    return workspace, BatchImageConvertRequest(
        tuple(items), workspace.output_directory, "jpg", workspace.batch_id
    )


def wait_for(
    runner: BatchExecutionService,
    batch_id: str,
    access_token: str,
    *phases: BatchExecutionPhase,
) -> object:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        snapshot = runner.get(batch_id, access_token)
        if snapshot.phase in phases:
            return snapshot
        sleep(0.01)
    raise AssertionError("batch session did not reach the expected phase")


def test_session_executes_packages_and_shutdown_cleans_workspace() -> None:
    runner = service()
    workspace, request = create_request(runner)
    path = workspace.path  # type: ignore[attr-defined]
    accepted = runner.create_session(request, workspace)  # type: ignore[arg-type]
    assert accepted.snapshot.attempt == 1
    assert accepted.snapshot.phase in {BatchExecutionPhase.QUEUED, BatchExecutionPhase.PROCESSING}
    ready = wait_for(runner, str(request.batch_id), accepted.access_token, BatchExecutionPhase.READY)
    assert ready.batch.status is BatchStatus.COMPLETED  # type: ignore[attr-defined]
    assert ready.can_download is True  # type: ignore[attr-defined]
    assert runner.download_path(str(request.batch_id), accepted.access_token).is_file()
    runner.shutdown()
    assert not path.exists()


def test_cancellation_is_connected_and_repeated_request_is_safe() -> None:
    runner = service()
    workspace, request = create_request(runner, ("one.png", "two.png", "three.png"))
    entered = Event()
    release = Event()
    real_converter = image_module.convert_image_path

    def blocking_converter(request_value: object) -> object:
        entered.set()
        assert release.wait(5)
        return real_converter(request_value)  # type: ignore[arg-type]

    with patch.object(image_module, "convert_image_path", side_effect=blocking_converter):
        grant = runner.create_session(request, workspace)  # type: ignore[arg-type]
        assert entered.wait(5)
        first = runner.cancel(str(request.batch_id), grant.access_token)
        second = runner.cancel(str(request.batch_id), grant.access_token)
        assert first.cancellation_requested and second.cancellation_requested
        assert second.phase is BatchExecutionPhase.CANCELLING
        assert first.can_cancel is False
        assert second.can_cancel is False
        release.set()
        ready = wait_for(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    assert ready.batch.status is BatchStatus.PARTIAL  # type: ignore[attr-defined]
    assert ready.batch.cancelled_count == 2  # type: ignore[attr-defined]
    runner.shutdown()


def test_durable_cancel_save_failure_does_not_trigger_live_token(tmp_path: Path) -> None:
    runner = service(storage_directory=tmp_path)
    workspace, request = create_request(runner, ("one.png", "two.png"))
    entered = Event()
    release = Event()
    real_runner = batches_module.batch_convert_images

    def blocking_runner(*args: object, **kwargs: object) -> object:
        entered.set()
        assert release.wait(5)
        return real_runner(*args, **kwargs)  # type: ignore[arg-type]

    with patch.object(batches_module, "batch_convert_images", side_effect=blocking_runner):
        grant = runner.create_session(request, workspace)  # type: ignore[arg-type]
        assert entered.wait(5)
        before = runner.get(str(request.batch_id), grant.access_token)
        repository = runner._repository
        assert repository is not None
        with (
            patch.object(
                repository,
                "save",
                side_effect=BatchPersistenceError("private SQLite diagnostic"),
            ),
            pytest.raises(ApiError) as error,
        ):
            runner.cancel(str(request.batch_id), grant.access_token)
        assert error.value.status_code == 503
        assert error.value.code == "batch_persistence_failed"
        unchanged = runner.get(str(request.batch_id), grant.access_token)
        assert unchanged.phase is before.phase
        assert unchanged.cancellation_requested is False
        assert unchanged.can_cancel is True
        assert runner._sessions[str(request.batch_id)].cancellation.cancellation_requested is False

        cancelled = runner.cancel(str(request.batch_id), grant.access_token)
        assert cancelled.phase is BatchExecutionPhase.CANCELLING
        assert cancelled.cancellation_requested is True
        release.set()
        wait_for(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    runner.shutdown()


def test_packaging_and_terminal_processing_window_are_not_cancellable() -> None:
    runner = service()
    workspace, request = create_request(runner, ("one.png",))
    packaging_entered = Event()
    release_packaging = Event()
    real_packager = batches_module.package_batch_outputs

    def blocking_packager(*args: object, **kwargs: object) -> object:
        packaging_entered.set()
        assert release_packaging.wait(5)
        return real_packager(*args, **kwargs)  # type: ignore[arg-type]

    with patch.object(
        batches_module, "package_batch_outputs", side_effect=blocking_packager
    ):
        grant = runner.create_session(request, workspace)  # type: ignore[arg-type]
        assert packaging_entered.wait(5)
        packaging = runner.get(str(request.batch_id), grant.access_token)
        assert packaging.phase is BatchExecutionPhase.PACKAGING
        assert packaging.can_cancel is False
        with pytest.raises(ApiError) as error:
            runner.cancel(str(request.batch_id), grant.access_token)
        assert error.value.status_code == 409
        assert error.value.code == "batch_not_cancellable"
        release_packaging.set()
        wait_for(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    runner.shutdown()

    runner = service()
    workspace, request = create_request(runner, ("one.png",))
    terminal_observed = Event()
    release_runner = Event()
    real_runner = batches_module.batch_convert_images

    def blocking_terminal_runner(*args: object, **kwargs: object) -> object:
        result = real_runner(*args, **kwargs)  # type: ignore[arg-type]
        terminal_observed.set()
        assert release_runner.wait(5)
        return result

    with patch.object(
        batches_module, "batch_convert_images", side_effect=blocking_terminal_runner
    ):
        grant = runner.create_session(request, workspace)  # type: ignore[arg-type]
        assert terminal_observed.wait(5)
        terminal = runner.get(str(request.batch_id), grant.access_token)
        assert terminal.phase is BatchExecutionPhase.PROCESSING
        assert terminal.batch.is_terminal
        assert terminal.batch.summary.pending_count == 0
        assert terminal.can_cancel is False
        with pytest.raises(ApiError) as error:
            runner.cancel(str(request.batch_id), grant.access_token)
        assert error.value.code == "batch_not_cancellable"
        release_runner.set()
        wait_for(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    runner.shutdown()


def test_selective_recovery_increments_attempt_and_preserves_success(tmp_path: Path) -> None:
    runner = service()
    workspace, request = create_request(runner)
    missing = request.items[0].input_path
    missing.unlink()
    grant = runner.create_session(request, workspace)  # type: ignore[arg-type]
    first = wait_for(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    assert first.batch.status is BatchStatus.PARTIAL  # type: ignore[attr-defined]
    preserved = request.output_directory / "0002-two.jpg"
    before = preserved.read_bytes()
    write_image(missing)
    retried = runner.recover(str(request.batch_id), grant.access_token)
    assert retried.attempt == 2
    final = wait_for(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    assert final.batch.status is BatchStatus.COMPLETED  # type: ignore[attr-defined]
    assert preserved.read_bytes() == before
    runner.shutdown()


def test_packaging_failure_retries_without_reprocessing(tmp_path: Path) -> None:
    runner = service()
    workspace, request = create_request(runner, ("one.png",))
    real_packager = batches_module.package_batch_outputs
    with patch.object(
        batches_module,
        "package_batch_outputs",
        side_effect=BatchProcessingError("private"),
    ):
        grant = runner.create_session(request, workspace)  # type: ignore[arg-type]
        failed = wait_for(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.ERROR)
    assert failed.session_error.code == "batch_packaging_failed"  # type: ignore[attr-defined]
    output = request.output_directory / "0001-one.jpg"
    before = output.read_bytes()
    with patch.object(batches_module, "package_batch_outputs", wraps=real_packager) as package:
        runner.recover(str(request.batch_id), grant.access_token)
        ready = wait_for(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    assert ready.attempt == 2  # type: ignore[attr-defined]
    assert output.read_bytes() == before
    package.assert_called_once()
    runner.shutdown()


def test_unexpected_failure_is_safe_and_recovery_restarts_original_request() -> None:
    runner = service()
    workspace, request = create_request(runner, ("one.png",))
    real_runner = batches_module.batch_convert_images
    with patch.object(batches_module, "batch_convert_images", side_effect=RuntimeError("private")):
        grant = runner.create_session(request, workspace)  # type: ignore[arg-type]
        failed = wait_for(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.ERROR)
    assert failed.session_error.code == "batch_execution_failed"  # type: ignore[attr-defined]
    assert "private" not in failed.session_error.message  # type: ignore[attr-defined]
    with patch.object(batches_module, "batch_convert_images", wraps=real_runner):
        runner.recover(str(request.batch_id), grant.access_token)
        ready = wait_for(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    assert ready.batch.status is BatchStatus.COMPLETED  # type: ignore[attr-defined]
    runner.shutdown()


def test_terminal_expiry_removes_workspace_but_active_session_does_not() -> None:
    now = [100.0]
    runner = service(terminal_ttl_seconds=10, clock=lambda: now[0])
    workspace, request = create_request(runner, ("one.png",))
    path = workspace.path  # type: ignore[attr-defined]
    grant = runner.create_session(request, workspace)  # type: ignore[arg-type]
    wait_for(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.READY)
    now[0] += 11
    with pytest.raises(ApiError) as error:
        runner.get(str(request.batch_id), grant.access_token)
    assert error.value.status_code == 404
    assert not path.exists()
    runner.shutdown()


def test_service_instances_do_not_share_sessions() -> None:
    first = service()
    second = service()
    workspace, request = create_request(first, ("one.png",))
    grant = first.create_session(request, workspace)  # type: ignore[arg-type]
    with pytest.raises(ApiError) as error:
        second.get(str(request.batch_id), grant.access_token)
    assert error.value.status_code == 404
    first.shutdown()
    second.shutdown()


def test_session_capability_is_hash_only_and_authorizes_every_operation() -> None:
    runner = service()
    first_workspace, first_request = create_request(runner, ("one.png",))
    second_workspace, second_request = create_request(runner, ("two.png",))
    first = runner.create_session(first_request, first_workspace)  # type: ignore[arg-type]
    second = runner.create_session(second_request, second_workspace)  # type: ignore[arg-type]

    assert first.access_token != second.access_token
    assert len(first.access_token) == 43
    stored = runner._sessions[str(first_request.batch_id)]
    assert stored.access_token_hash != first.access_token
    assert len(stored.access_token_hash) == 64
    assert not hasattr(first.snapshot, "access_token")

    assert runner.get(str(first_request.batch_id), first.access_token).batch.id == first_request.batch_id
    for candidate in (None, "", " ", "wrong-token", "x" * 257, second.access_token):
        with pytest.raises(ApiError) as error:
            runner.get(str(first_request.batch_id), candidate)
        assert (error.value.status_code, error.value.code, error.value.message) == (
            404,
            "batch_not_found",
            "The batch session was not found.",
        )
    with pytest.raises(ApiError) as unknown:
        runner.get("unknown", first.access_token)
    assert (unknown.value.status_code, unknown.value.code, unknown.value.message) == (
        404,
        "batch_not_found",
        "The batch session was not found.",
    )
    runner.shutdown()

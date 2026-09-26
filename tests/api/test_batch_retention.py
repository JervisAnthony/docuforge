"""Service-owned retention, idle expiry and lifecycle failure coverage."""

from threading import Event, Thread
from threading import enumerate as threads
from time import monotonic, sleep
from unittest.mock import patch

import pytest

import docuforge.api.batches as module
from docuforge.api import ApiSettings, create_app
from docuforge.api.batch_persistence import BatchPersistenceError, BatchSessionWorkspace
from docuforge.api.batch_storage_lock import BatchStorageOwnershipError
from docuforge.api.batches import BatchExecutionPhase as Phase
from docuforge.api.errors import ApiError
from tests.api.test_batch_service import create_request, service, wait_for


def eventually(predicate):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    raise AssertionError("retention did not complete")


def terminal(runner, error=False):
    workspace, request = create_request(runner, ("one.png",))
    with (
        patch.object(module, "batch_convert_images", side_effect=RuntimeError("private"))
        if error
        else patch.object(module, "batch_convert_images", wraps=module.batch_convert_images)
    ):
        grant = runner.create_session(request, workspace)
        batch_id = str(request.batch_id)
        wait_for(runner, batch_id, grant.access_token, Phase.ERROR if error else Phase.READY)
    return workspace, batch_id, grant.access_token


@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("error", [False, True])
def test_idle_terminal_expiry(tmp_path, durable, error):
    now = [100.0]
    runner = service(
        storage_directory=tmp_path if durable else None,
        clock=lambda: now[0],
        terminal_ttl_seconds=10,
        cleanup_interval_seconds=1,
    )
    try:
        workspace, batch_id, token = terminal(runner, error)
        now[0] = 109
        sleep(1.1)
        assert batch_id in runner._sessions
        assert workspace.path.exists()
        now[0] = 110
        # No service operation after terminal observation: inspect state directly.
        eventually(lambda: batch_id not in runner._sessions)
        assert not workspace.path.exists()
        if durable:
            assert runner._repository.get(batch_id) is None
        with pytest.raises(ApiError) as failure:
            runner.get(batch_id, token)
        assert failure.value.code == "batch_not_found"
    finally:
        runner.shutdown()


@pytest.mark.parametrize("explicit", [False, True])
def test_background_tombstone_retry(tmp_path, explicit, caplog):
    now = [100.0]
    runner = service(
        storage_directory=tmp_path,
        clock=lambda: now[0],
        terminal_ttl_seconds=10,
        cleanup_interval_seconds=1,
    )
    failed = Event()
    original = BatchSessionWorkspace.cleanup

    def fail(workspace):
        failed.set()
        raise BatchPersistenceError("private path token")

    try:
        workspace, batch_id, token = terminal(runner)
        with patch.object(BatchSessionWorkspace, "cleanup", fail):
            if explicit:
                with pytest.raises(ApiError) as error:
                    runner.delete_session(batch_id, token)
                assert error.value.code == "batch_deletion_failed"
            else:
                now[0] = 110
            assert failed.wait(4)
            with runner._lock:
                assert runner._sessions[batch_id].phase is Phase.DELETING
                assert runner._repository.get(batch_id).phase == "deleting"
            assert runner._cleanup_thread.is_alive()
        eventually(lambda: batch_id not in runner._sessions)
        assert not workspace.path.exists()
        assert runner._repository.get(batch_id) is None
        assert "private path token" not in caplog.text
    finally:
        with patch.object(BatchSessionWorkspace, "cleanup", original):
            runner.shutdown()


def test_multiple_failures_do_not_starve_expiry(tmp_path):
    now = [100.0]
    runner = service(storage_directory=tmp_path, clock=lambda: now[0], terminal_ttl_seconds=10)
    try:
        first, first_id, token = terminal(runner)
        second, second_id, _ = terminal(runner)
        original = BatchSessionWorkspace.cleanup

        def fail_one(workspace):
            if workspace is first:
                raise BatchPersistenceError("safe")
            original(workspace)

        with patch.object(BatchSessionWorkspace, "cleanup", fail_one):
            with pytest.raises(ApiError):
                runner.delete_session(first_id, token)
            now[0] = 110
            with runner._lock, pytest.raises(BatchPersistenceError):
                runner._sweep_locked()
            assert first_id in runner._sessions
            assert second_id not in runner._sessions
            assert not second.path.exists()
    finally:
        runner.shutdown()


def test_tombstone_save_failure_preserves_terminal(tmp_path):
    now = [100.0]
    runner = service(storage_directory=tmp_path, clock=lambda: now[0], terminal_ttl_seconds=10)
    try:
        workspace, batch_id, _ = terminal(runner)
        now[0] = 110
        with (
            patch.object(runner._repository, "save", side_effect=BatchPersistenceError("safe")),
            runner._lock,
            pytest.raises(BatchPersistenceError),
        ):
            runner._sweep_locked()
        assert runner._sessions[batch_id].phase is Phase.READY
        assert workspace.path.exists()
        assert runner._repository.get(batch_id).phase == "ready"
        with runner._lock:
            runner._sweep_locked()
        assert batch_id not in runner._sessions
    finally:
        runner.shutdown()


@pytest.mark.parametrize(
    "phase", [Phase.QUEUED, Phase.PROCESSING, Phase.CANCELLING, Phase.PACKAGING]
)
def test_active_and_preparing_survive(tmp_path, phase):
    now = [100.0]
    runner = service(
        storage_directory=tmp_path,
        clock=lambda: now[0],
        terminal_ttl_seconds=10,
        cleanup_interval_seconds=1,
    )
    entered, release = Event(), Event()
    original = module.batch_convert_images

    def block(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    try:
        preparing = runner.create_workspace()
        with patch.object(module, "batch_convert_images", block):
            workspace, request = create_request(runner)
            runner.create_session(request, workspace)
            assert entered.wait(3)
            with runner._lock:
                runner._sessions[str(request.batch_id)].phase = phase
            admitted = runner._admitted_batch_ids.copy()
            now[0] = 1000
            sleep(2.1)
            assert workspace.path.exists() and preparing.path.exists()
            assert str(request.batch_id) in runner._sessions
            assert runner._admitted_batch_ids == admitted
            release.set()
        runner.abandon_workspace(preparing)
    finally:
        release.set()
        runner.shutdown()


@pytest.mark.parametrize("expired", [False, True])
def test_restored_and_startup_expiry(tmp_path, expired):
    now = [100.0]
    runner = service(storage_directory=tmp_path, clock=lambda: now[0], terminal_ttl_seconds=10)
    workspace, batch_id, _ = terminal(runner)
    runner.shutdown()
    now[0] = 110 if expired else 109
    restored = service(
        storage_directory=tmp_path,
        clock=lambda: now[0],
        terminal_ttl_seconds=10,
        cleanup_interval_seconds=1,
    )
    try:
        if not expired:
            assert batch_id in restored._sessions
            now[0] = 110
            eventually(lambda: batch_id not in restored._sessions)
        assert batch_id not in restored._sessions
        assert not workspace.path.exists()
        assert restored._repository.get(batch_id) is None
    finally:
        restored.shutdown()


def test_shutdown_joins_before_owner_release(tmp_path):
    runner = service(storage_directory=tmp_path)
    cleanup = runner._cleanup_thread
    assert cleanup.name == "docuforge-batch-cleanup" and cleanup.daemon
    entered, release = Event(), Event()
    original = cleanup.join

    def blocked_join():
        entered.set()
        assert release.wait(5)
        original()

    with patch.object(cleanup, "join", blocked_join):
        stopper = Thread(target=runner.shutdown)
        stopper.start()
        try:
            assert entered.wait(3)
            with pytest.raises(BatchStorageOwnershipError):
                service(storage_directory=tmp_path)
        finally:
            release.set()
            stopper.join(5)
    assert not stopper.is_alive() and not cleanup.is_alive()
    runner.shutdown()
    replacement = service(storage_directory=tmp_path)
    replacement.shutdown()


@pytest.mark.parametrize("failure", ["restore", "executor", "thread"])
def test_constructor_failure_releases_resources(tmp_path, failure):
    baseline = set(threads())
    executor = module.ThreadPoolExecutor(max_workers=1)
    target = {
        "restore": "BatchExecutionService._restore_sessions",
        "executor": "ThreadPoolExecutor",
        "thread": "Thread.start",
    }[failure]
    with (
        patch.object(executor, "shutdown", wraps=executor.shutdown) as stopped,
        patch("docuforge.api.batches." + target, side_effect=RuntimeError("safe")),
    ):
        if failure == "thread":
            with (
                patch.object(module, "ThreadPoolExecutor", return_value=executor),
                pytest.raises(RuntimeError),
            ):
                service(storage_directory=tmp_path)
            stopped.assert_called_once_with(wait=True)
        else:
            with pytest.raises(RuntimeError):
                service(storage_directory=tmp_path)
    executor.shutdown()
    assert not any(t not in baseline and t.name == "docuforge-batch-cleanup" for t in threads())
    replacement = service(storage_directory=tmp_path)
    replacement.shutdown()


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1"])
def test_interval_rejects_nonpositive_noninteger(value):
    with pytest.raises(ValueError):
        ApiSettings(batch_cleanup_interval_seconds=value)
    with pytest.raises(ValueError):
        service(cleanup_interval_seconds=value)


@pytest.mark.parametrize("value", ["", " ", "0", "-1", "1.5", "true", "sixty"])
def test_environment_rejects_invalid_interval(monkeypatch, value):
    monkeypatch.setenv("DOCUFORGE_BATCH_CLEANUP_INTERVAL_SECONDS", value)
    with pytest.raises(ValueError, match="must be a positive integer"):
        ApiSettings.from_environment()


def test_defaults_custom_interval_and_app_wiring(monkeypatch):
    assert ApiSettings().batch_cleanup_interval_seconds == 60
    assert ApiSettings().batch_terminal_ttl_seconds == 3600
    monkeypatch.setenv("DOCUFORGE_BATCH_CLEANUP_INTERVAL_SECONDS", "15")
    settings = ApiSettings.from_environment()
    assert settings.batch_cleanup_interval_seconds == 15
    runner = service(terminal_ttl_seconds=1, cleanup_interval_seconds=30)
    assert runner._cleanup_interval_seconds == 30
    runner.shutdown()
    with patch("docuforge.api.app.BatchExecutionService") as factory:
        create_app(settings)
    assert factory.call_args.kwargs["cleanup_interval_seconds"] == 15


def test_recovered_session_survives_terminal_retention():
    now = [100.0]
    runner = service(clock=lambda: now[0], terminal_ttl_seconds=10, cleanup_interval_seconds=1)
    entered, release = Event(), Event()
    original = module.batch_convert_images

    def block(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    try:
        workspace, batch_id, token = terminal(runner, error=True)
        now[0] = 109
        with patch.object(module, "batch_convert_images", block):
            runner.recover(batch_id, token)
            assert entered.wait(3)
            now[0] = 111
            sleep(1.1)
            assert batch_id in runner._sessions and workspace.path.exists()
            release.set()
            wait_for(runner, batch_id, token, Phase.READY)
        assert runner._sessions[batch_id].updated_at == 111
    finally:
        release.set()
        runner.shutdown()


def test_cleanup_starts_after_restoration_and_executor(tmp_path):
    restored = Event()
    original_restore = module.BatchExecutionService._restore_sessions
    original_start = Thread.start

    def restore(runner):
        original_restore(runner)
        assert runner._cleanup_thread is None
        restored.set()

    def start(thread):
        assert restored.is_set()
        assert thread._target.__self__._executor is not None
        original_start(thread)

    with (
        patch.object(module.BatchExecutionService, "_restore_sessions", restore),
        patch.object(Thread, "start", start),
    ):
        runner = service(storage_directory=tmp_path)
    runner.shutdown()

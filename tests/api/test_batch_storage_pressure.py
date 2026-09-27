"""Deterministic durable headroom, streaming reservations and recoverable refusal."""

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
from threading import Event, Thread
from unittest.mock import patch

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

import docuforge.api.batches as module
from docuforge.api import ApiSettings, create_app
from docuforge.api.batch_access import BATCH_TOKEN_HEADER
from docuforge.api.batch_persistence import BatchPersistenceError, BatchSessionWorkspace
from docuforge.api.batch_storage_lock import BatchStorageOwnershipError
from docuforge.api.batches import BatchExecutionPhase as Phase
from docuforge.api.errors import ApiError
from docuforge.api.uploads import UploadPolicy, store_batch_uploads
from tests.api.test_batch_service import create_request, service, wait_for

PRESSURE = (507, "batch_storage_pressure", "Batch storage is temporarily full. Try again later.")
UNAVAILABLE = (
    503,
    "batch_storage_unavailable",
    "Batch storage is temporarily unavailable. Try again later.",
)


class Capacity:
    def __init__(self, value=10000):
        self.value = value
        self.calls = 0

    def __call__(self, root):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


@pytest.fixture
def make_runner(tmp_path):
    runners = []

    def make(capacity, **kwargs):
        runner = service(
            storage_directory=tmp_path,
            min_free_storage_bytes=100,
            max_upload_request_bytes=200,
            free_storage_bytes=capacity,
            **kwargs,
        )
        runners.append(runner)
        return runner

    yield make
    for runner in runners:
        runner.shutdown()


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


def assert_error(error, expected):
    assert (error.status_code, error.code, error.message) == expected


@pytest.mark.parametrize("free,accepted", [(299, False), (300, True)])
def test_initial_admission_boundary(make_runner, free, accepted):
    capacity = Capacity(free)
    runner = make_runner(capacity)
    if accepted:
        workspace = runner.create_workspace()
        runner.abandon_workspace(workspace)
    else:
        with (
            patch.object(BatchSessionWorkspace, "durable_new") as create,
            pytest.raises(ApiError) as error,
        ):
            runner.create_workspace()
        assert_error(error.value, PRESSURE)
        create.assert_not_called()
    assert not runner._admitted_batch_ids
    assert not list(runner._sessions_root.iterdir())


@pytest.mark.parametrize(
    "value",
    [True, -1, 1.5, "10000", None, OSError("private drive path errno"), RuntimeError("private")],
)
def test_invalid_or_failed_measurement_is_unavailable(make_runner, value):
    runner = make_runner(Capacity(value))
    with pytest.raises(ApiError) as error:
        runner.create_workspace()
    assert_error(error.value, UNAVAILABLE)
    assert not runner._admitted_batch_ids


def test_actual_filesystem_provider(tmp_path):
    with patch.object(module, "disk_usage") as usage:
        usage.return_value.free = 123
        assert module._filesystem_free_storage_bytes(tmp_path) == 123
    usage.assert_called_once_with(tmp_path)


def test_concurrent_reservations_and_initial_admission_accounting(make_runner):
    capacity = Capacity(300)
    runner = make_runner(capacity)
    entered, release = Event(), Event()

    def hold():
        with runner.reserve_storage_write(150):
            entered.set()
            assert release.wait(5)

    holder = Thread(target=hold)
    holder.start()
    try:
        assert entered.wait(3)
        assert runner._pending_storage_write_bytes == 150
        with pytest.raises(ApiError) as error, runner.reserve_storage_write(100):
            pytest.fail("oversubscribed")
        assert_error(error.value, PRESSURE)
        with pytest.raises(ApiError) as error:
            runner.create_workspace()
        assert_error(error.value, PRESSURE)
        assert not runner._admitted_batch_ids
    finally:
        release.set()
        holder.join(5)
    assert not holder.is_alive()
    assert runner._pending_storage_write_bytes == 0
    with runner.reserve_storage_write(100):
        assert runner._pending_storage_write_bytes == 100
    assert runner._pending_storage_write_bytes == 0


def test_reservation_unwinds_on_failure(make_runner):
    runner = make_runner(Capacity())
    with pytest.raises(OSError), runner.reserve_storage_write(20):
        raise OSError("write failed")
    assert runner._pending_storage_write_bytes == 0


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1"])
def test_reservation_validates_byte_count(make_runner, value):
    runner = make_runner(Capacity())
    with pytest.raises(ValueError), runner.reserve_storage_write(value):
        pass
    assert runner._pending_storage_write_bytes == 0


def test_shutdown_drains_reservations_before_releasing_owner(make_runner, tmp_path):
    runner = make_runner(Capacity())
    stopping = Event()
    original_join = runner._cleanup_thread.join

    def joined():
        original_join()
        stopping.set()

    with runner.reserve_storage_write(10), patch.object(runner._cleanup_thread, "join", joined):
        stopper = Thread(target=runner.shutdown)
        stopper.start()
        assert stopping.wait(3)
        assert runner._pending_storage_write_bytes == 10
        with pytest.raises(BatchStorageOwnershipError):
            service(storage_directory=tmp_path)
    stopper.join(5)
    assert not stopper.is_alive()
    assert runner._pending_storage_write_bytes == 0
    replacement = service(storage_directory=tmp_path)
    replacement.shutdown()


@pytest.mark.parametrize("kind", ["ttl", "tombstone"])
def test_eligible_reclaim_precedes_measurement(make_runner, kind):
    now = [100.0]
    capacity = Capacity()
    runner = make_runner(capacity, terminal_ttl_seconds=10, clock=lambda: now[0])
    workspace, batch_id, token = terminal(runner)
    if kind == "tombstone":
        with (
            patch.object(
                BatchSessionWorkspace, "cleanup", side_effect=BatchPersistenceError("private")
            ),
            pytest.raises(ApiError),
        ):
            runner.delete_session(batch_id, token)
    else:
        now[0] = 110
    runner._free_storage_bytes = lambda _root: 0 if workspace.path.exists() else 300
    new = runner.create_workspace()
    assert batch_id not in runner._sessions
    assert runner._repository.get(batch_id) is None
    assert not workspace.path.exists()
    runner.abandon_workspace(new)


@pytest.mark.parametrize("free", [0, 10000])
def test_reclaim_failure_still_checks_capacity(make_runner, free):
    now = [100.0]
    capacity = Capacity()
    runner = make_runner(capacity, terminal_ttl_seconds=10, clock=lambda: now[0])
    workspace, batch_id, _ = terminal(runner)
    now[0] = 110
    capacity.value = free
    with patch.object(
        BatchSessionWorkspace, "cleanup", side_effect=BatchPersistenceError("private")
    ):
        if free:
            new = runner.create_workspace()
        else:
            with pytest.raises(ApiError) as error:
                runner.create_workspace()
            assert_error(error.value, PRESSURE)
    assert runner._sessions[batch_id].phase is Phase.DELETING
    assert workspace.path.exists()
    if free:
        runner.abandon_workspace(new)


@pytest.mark.parametrize("is_error", [False, True])
def test_unexpired_retained_data_and_read_delete_access_under_pressure(make_runner, is_error):
    capacity = Capacity()
    runner = make_runner(capacity)
    workspace, batch_id, token = terminal(runner, is_error)
    before = runner._repository.get(batch_id)
    capacity.value = 0
    with pytest.raises(ApiError) as error:
        runner.create_workspace()
    assert_error(error.value, PRESSURE)
    assert runner._repository.get(batch_id) == before
    assert workspace.path.exists()
    assert runner.get(batch_id, token).phase is (Phase.ERROR if is_error else Phase.READY)
    if not is_error:
        assert runner.download_path(batch_id, token).is_file()
    runner.delete_session(batch_id, token)
    assert not workspace.path.exists()


@pytest.mark.parametrize("value,expected", [(0, PRESSURE), (OSError("private"), UNAVAILABLE)])
def test_recovery_refusal_is_atomic_and_later_full_retry_succeeds(make_runner, value, expected):
    capacity = Capacity()
    runner = make_runner(capacity)
    _, batch_id, token = terminal(runner, True)
    original = replace(runner._sessions[batch_id])
    row = runner._repository.get(batch_id)
    admitted = runner._admitted_batch_ids.copy()
    capacity.value = value
    with pytest.raises(ApiError) as error:
        runner.recover(batch_id, token)
    assert_error(error.value, expected)
    assert runner._sessions[batch_id] == original
    assert runner._repository.get(batch_id) == row
    assert runner._admitted_batch_ids == admitted
    capacity.value = 10000
    runner.recover(batch_id, token)
    ready = wait_for(runner, batch_id, token, Phase.READY)
    assert ready.attempt == 2


@pytest.mark.parametrize("value,expected", [(0, PRESSURE), (OSError("private"), UNAVAILABLE)])
def test_execution_preflight_skips_converter_and_survives_restart(
    make_runner, tmp_path, value, expected
):
    capacity = Capacity()
    runner = make_runner(capacity)
    entered, release = Event(), Event()

    def block():
        entered.set()
        assert release.wait(5)

    blocker = runner._executor.submit(block)
    try:
        assert entered.wait(3)
        workspace, request = create_request(runner, ("one.png",))
        grant = runner.create_session(request, workspace)
        batch_id = str(request.batch_id)
        capacity.value = value
        with patch.object(module, "batch_convert_images") as converter:
            release.set()
            wait_for(runner, batch_id, grant.access_token, Phase.ERROR)
            converter.assert_not_called()
        session = runner._sessions[batch_id]
        assert (session.session_error.code, session.session_error.message) == expected[1:]
        assert session.result is None
        assert not runner._admitted_batch_ids
        assert runner._repository.get(batch_id).phase == "error"
        runner.shutdown()
        capacity.value = 10000
        restored = make_runner(capacity)
        assert restored.get(batch_id, grant.access_token).session_error.code == expected[1]
        restored.recover(batch_id, grant.access_token)
        wait_for(restored, batch_id, grant.access_token, Phase.READY)
    finally:
        release.set()
        blocker.result(5)


@pytest.mark.parametrize("value,expected", [(0, PRESSURE), (OSError("private"), UNAVAILABLE)])
def test_packaging_refusal_preserves_outputs_and_retries_without_conversion(
    make_runner, value, expected
):
    capacity = Capacity()
    runner = make_runner(capacity)
    original = module.batch_convert_images

    def convert(*args, **kwargs):
        result = original(*args, **kwargs)
        capacity.value = value
        return result

    workspace, request = create_request(runner, ("one.png",))
    with (
        patch.object(module, "batch_convert_images", convert),
        patch.object(module, "package_batch_outputs") as package,
    ):
        grant = runner.create_session(request, workspace)
        batch_id = str(request.batch_id)
        wait_for(runner, batch_id, grant.access_token, Phase.ERROR)
        package.assert_not_called()
    session = runner._sessions[batch_id]
    assert (session.session_error.code, session.session_error.message) == expected[1:]
    assert session.result is not None and session.result.outputs
    assert list(workspace.output_directory.iterdir())
    assert not workspace.archive_path.exists()
    assert not runner._admitted_batch_ids
    runner.shutdown()
    restored = make_runner(capacity)
    assert restored._sessions[batch_id].result is not None
    capacity.value = 10000
    with (
        patch.object(module, "batch_convert_images") as converter,
        patch.object(
            module, "package_batch_outputs", wraps=module.package_batch_outputs
        ) as package,
    ):
        restored.recover(batch_id, grant.access_token)
        ready = wait_for(restored, batch_id, grant.access_token, Phase.READY)
        converter.assert_not_called()
        package.assert_called_once()
    assert ready.attempt == 2
    assert restored.download_path(batch_id, grant.access_token).is_file()


def test_cancel_is_not_blocked_by_storage_pressure(make_runner):
    capacity = Capacity()
    runner = make_runner(capacity)
    entered, release = Event(), Event()
    original = module.batch_convert_images

    def block(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    try:
        with patch.object(module, "batch_convert_images", block):
            workspace, request = create_request(runner)
            grant = runner.create_session(request, workspace)
            assert entered.wait(3)
            capacity.value = 0
            runner.cancel(str(request.batch_id), grant.access_token)
            assert runner._sessions[str(request.batch_id)].cancellation.cancellation_requested
            release.set()
    finally:
        release.set()


def test_ephemeral_never_measures_capacity():
    capacity = Capacity(0)
    runner = service(free_storage_bytes=capacity)
    try:
        _workspace, batch_id, token = terminal(runner)
        with runner.reserve_storage_write(10):
            assert runner._pending_storage_write_bytes == 0
        assert runner.download_path(batch_id, token).is_file()
        assert capacity.calls == 0
        assert runner._storage_root is None
    finally:
        runner.shutdown()


@pytest.mark.parametrize(
    "path,name", [("images/convert", "one.png"), ("office/to-pdf", "one.docx")]
)
@pytest.mark.parametrize(
    "late,value,expected",
    [
        (False, 0, PRESSURE),
        (False, OSError("private root drive errno"), UNAVAILABLE),
        (True, 0, PRESSURE),
        (True, OSError("private root drive errno"), UNAVAILABLE),
    ],
)
def test_upload_routes_unwind_partial_files_and_return_private_error(
    tmp_path, path, name, late, value, expected
):
    calls = [0]

    def capacity(root):
        calls[0] += 1
        if late and calls[0] <= 2:
            return 10000
        if isinstance(value, Exception):
            raise value
        return value

    real_service = module.BatchExecutionService

    def factory(**kwargs):
        return real_service(**kwargs, free_storage_bytes=capacity)

    settings = ApiSettings(
        batch_storage_directory=tmp_path,
        batch_min_free_storage_bytes=100,
        max_upload_request_bytes=1024,
        max_upload_file_bytes=1024,
        upload_chunk_bytes=4,
    )
    with patch("docuforge.api.app.BatchExecutionService", factory):
        app = create_app(settings)
    runner = app.state.batch_service
    cleaned = []
    original_abandon = runner.abandon_workspace

    def abandon(workspace):
        cleaned.append(not list(workspace.inputs_directory.rglob(name)))
        original_abandon(workspace)

    with TestClient(app) as client, patch.object(runner, "abandon_workspace", abandon):
        response = client.post(
            "/api/v1/batches/" + path,
            files=[
                ("file", (name, b"abcdefgh", "application/octet-stream")),
                ("format", (None, "jpeg")),
            ],
        )
        assert response.status_code == expected[0]
        assert response.json() == {"code": expected[1], "message": expected[2]}
        assert "retry-after" not in response.headers
        assert BATCH_TOKEN_HEADER.lower() not in response.headers
        assert "location" not in response.headers
        assert not list(runner._sessions_root.iterdir())
        assert not runner._repository.list_all()
        assert not runner._admitted_batch_ids
        assert runner._pending_storage_write_bytes == 0
        assert cleaned == ([True] if late else [])


def test_openapi_documents_pressure_without_metrics():
    app = create_app()
    try:
        schema = app.openapi()
        for path in (
            "images/convert",
            "images/resize",
            "images/compress",
            "office/to-pdf",
            "{batch_id}/recover",
        ):
            responses = schema["paths"]["/api/v1/batches/" + path]["post"]["responses"]
            assert "503" in responses and "507" in responses
            assert (
                responses["507"]["description"]
                == "Durable batch storage does not currently have enough safe headroom."
            )
        assert "/api/v1/storage" not in schema["paths"]
    finally:
        app.state.batch_service.shutdown()


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1"])
def test_settings_and_constructor_validate_positive_bytes(value):
    with pytest.raises(ValueError):
        ApiSettings(batch_min_free_storage_bytes=value)
    for field in ("min_free_storage_bytes", "max_upload_request_bytes"):
        with pytest.raises(ValueError):
            service(**{field: value})


@pytest.mark.parametrize("value", ["", " ", "0", "-1", "1.5", "true", "200MB", "garbage"])
def test_environment_rejects_invalid_floor(monkeypatch, value):
    monkeypatch.setenv("DOCUFORGE_BATCH_MIN_FREE_STORAGE_BYTES", value)
    with pytest.raises(ValueError, match="must be a positive integer"):
        ApiSettings.from_environment()


def test_defaults_custom_floor_and_app_wiring(monkeypatch, tmp_path):
    assert ApiSettings().batch_min_free_storage_bytes == 209715200
    monkeypatch.setenv("DOCUFORGE_BATCH_MIN_FREE_STORAGE_BYTES", "104857600")
    assert ApiSettings.from_environment().batch_min_free_storage_bytes == 104857600
    settings = ApiSettings(
        batch_min_free_storage_bytes=1,
        max_upload_request_bytes=1024,
        max_upload_file_bytes=1024,
        batch_storage_directory=tmp_path,
    )
    with patch("docuforge.api.app.BatchExecutionService") as factory:
        create_app(settings)
    assert factory.call_args.kwargs["min_free_storage_bytes"] == 1
    assert factory.call_args.kwargs["max_upload_request_bytes"] == 1024


def test_upload_chunk_flushes_before_releasing_reservation(make_runner):
    runner = make_runner(Capacity())
    workspace = runner.create_workspace()
    counts = []

    @contextmanager
    def reserve(count):
        with runner.reserve_storage_write(count):
            yield
            stored = workspace.inputs_directory / "item-0001" / "one.png"
            counts.append(count)
            assert stored.read_bytes() == b"abcdefgh"[: sum(counts)]
            assert runner._pending_storage_write_bytes == count

    upload = UploadFile(BytesIO(b"abcdefgh"), filename="one.png")
    try:
        asyncio.run(
            store_batch_uploads(
                [upload],
                input_directory=workspace.inputs_directory,
                policy=UploadPolicy(1, 20, 20, 3),
                reserve_storage_write=reserve,
            )
        )
        assert counts == [3, 3, 2]
        assert runner._pending_storage_write_bytes == 0
        assert upload.file.closed
    finally:
        runner.abandon_workspace(workspace)


def test_upload_size_validation_precedes_storage_reservation(make_runner):
    runner = make_runner(Capacity())
    workspace = runner.create_workspace()
    upload = UploadFile(BytesIO(b"abcd"), filename="one.png")
    try:
        with (
            patch.object(runner, "reserve_storage_write") as reserve,
            pytest.raises(ApiError) as failure,
        ):
            asyncio.run(
                store_batch_uploads(
                    [upload],
                    input_directory=workspace.inputs_directory,
                    policy=UploadPolicy(1, 2, 2, 4),
                    reserve_storage_write=reserve,
                )
            )
        reserve.assert_not_called()
        assert failure.value.status_code == 413
        assert not list(workspace.inputs_directory.rglob("one.png"))
        assert runner._pending_storage_write_bytes == 0
    finally:
        runner.abandon_workspace(workspace)

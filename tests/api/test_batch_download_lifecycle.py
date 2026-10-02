"""Accepted archive stream protection across storage lifecycle mutations."""

import asyncio
from dataclasses import fields, replace
from threading import Event, Thread
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from docuforge.api.batch_access import BATCH_TOKEN_HEADER
from docuforge.api.batch_persistence import BatchPersistenceError, BatchSessionWorkspace
from docuforge.api.batch_storage_lock import BatchStorageOwnershipError
from docuforge.api.batches import BatchDownloadHandle, BatchExecutionPhase
from docuforge.api.errors import ApiError
from docuforge.api.routes import batches as routes
from tests.api.image_test_support import make_image
from tests.api.test_batch_deletion import _ready
from tests.api.test_batch_service import create_request, service, wait_for


@pytest.mark.parametrize("durable", [False, True])
def test_independent_idempotent_pins_defer_delete(tmp_path, durable):
    runner, workspace, batch_id, token = _ready(tmp_path if durable else None)
    handles = [runner.acquire_download(batch_id, token) for _ in range(2)]
    try:
        original = handles[0].path.read_bytes()
        assert {field.name for field in fields(BatchDownloadHandle)} == {"path", "_release"}
        assert len(runner._active_downloads[batch_id]) == 2
        runner.delete_session(batch_id, token)
        assert runner._sessions[batch_id].phase is BatchExecutionPhase.DELETING
        for action in (runner.get, runner.acquire_download, runner.recover, runner.cancel):
            with pytest.raises(ApiError, match="not found") as error:
                action(batch_id, token)
            assert error.value.code == "batch_not_found"
        with runner._lock:
            runner._sweep_locked()
        handles[0].release()
        handles[0].release()
        assert len(runner._active_downloads[batch_id]) == 1
        assert handles[1].path.read_bytes() == original
        handles[1].release()
        assert not runner._active_downloads
        assert not workspace.path.exists()
        assert batch_id not in runner._sessions
        if runner._repository:
            assert runner._repository.get(batch_id) is None
    finally:
        for handle in handles:
            handle.release()
        runner.shutdown()


@pytest.mark.parametrize("token", [None, "", "malformed token", "wrong-token"])
def test_unauthorized_acquisition_creates_no_pin(token):
    runner, _, batch_id, _ = _ready()
    try:
        with pytest.raises(ApiError) as error:
            runner.acquire_download(batch_id, token)
        assert (error.value.status_code, error.value.code) == (404, "batch_not_found")
        assert not runner._active_downloads
    finally:
        runner.shutdown()


@pytest.mark.parametrize(
    "kind", ["no_outputs", "missing", "active", "handle_failure", "cross_token"]
)
def test_failed_acquisition_leaves_bookkeeping_unchanged(kind):
    runner = service(max_published_output_bytes=1) if kind == "no_outputs" else service()
    workspace, request = create_request(runner, ("one.png",))
    grant = runner.create_session(request, workspace)
    batch_id, token = str(request.batch_id), grant.access_token
    wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
    expected = "batch_has_no_outputs"
    try:
        if kind == "missing":
            workspace.archive_path.unlink()
            expected = "batch_packaging_failed"
        elif kind == "active":
            runner._sessions[batch_id].phase = BatchExecutionPhase.PACKAGING
            expected = "batch_not_ready"
        elif kind == "cross_token":
            other_workspace, other_request = create_request(runner, ("other.png",))
            token = runner.create_session(other_request, other_workspace).access_token
            expected = "batch_not_found"
        if kind == "handle_failure":
            with (
                patch(
                    "docuforge.api.batches.BatchDownloadHandle", side_effect=RuntimeError("fail")
                ),
                pytest.raises(RuntimeError),
            ):
                runner.acquire_download(batch_id, token)
        else:
            with pytest.raises(ApiError) as error:
                runner.acquire_download(batch_id, token)
            assert error.value.code == expected
        assert not runner._active_downloads
    finally:
        runner.shutdown()


def test_download_is_read_only_and_ttl_still_tombstones(tmp_path):
    runner, workspace, batch_id, token = _ready(tmp_path)
    session = runner._sessions[batch_id]
    before = runner._repository.get(batch_id)
    updated_at = session.updated_at
    with patch.object(runner._repository, "save", wraps=runner._repository.save) as save:
        handle = runner.acquire_download(batch_id, token)
        handle.release()
        assert not save.called
    assert session.updated_at == updated_at
    assert runner._repository.get(batch_id) == before
    assert not runner._admitted_batch_ids
    assert runner._pending_storage_write_bytes == 0
    handle = runner.acquire_download(batch_id, token)
    try:
        runner._clock = lambda: updated_at + runner._terminal_ttl_seconds
        with runner._lock:
            runner._sweep_locked()
            runner._sweep_locked()
        assert session.phase is BatchExecutionPhase.DELETING
        assert runner._repository.get(batch_id).phase == "deleting"
        assert handle.path.read_bytes()
        with pytest.raises(ApiError):
            runner.get(batch_id, token)
    finally:
        handle.release()
        runner.shutdown()
    assert not workspace.path.exists()


def test_deferred_cleanup_failure_is_safe_and_retryable(tmp_path, caplog):
    runner, workspace, batch_id, token = _ready(tmp_path)
    handle = runner.acquire_download(batch_id, token)
    runner.delete_session(batch_id, token)
    with patch.object(
        BatchSessionWorkspace, "cleanup", side_effect=BatchPersistenceError("private path")
    ):
        handle.release()
    assert caplog.messages == ["Deferred batch deletion cleanup failed; it will be retried."]
    assert runner._repository.get(batch_id).phase == "deleting"
    assert not runner._active_downloads
    with runner._lock:
        runner._sweep_locked()
    assert not workspace.path.exists()
    runner.shutdown()


def test_recovery_refusal_is_atomic_and_release_allows_recovery(tmp_path):
    runner = service(storage_directory=tmp_path)
    workspace, request = create_request(runner)
    request.items[1].input_path.write_bytes(b"invalid")
    grant = runner.create_session(request, workspace)
    batch_id, token = str(request.batch_id), grant.access_token
    wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
    handle = runner.acquire_download(batch_id, token)
    try:
        session = runner._sessions[batch_id]
        before = replace(session)
        row = runner._repository.get(batch_id)
        with (
            patch.object(
                runner, "_require_storage_locked", side_effect=AssertionError("too early")
            ),
            pytest.raises(ApiError) as error,
        ):
            runner.recover(batch_id, token)
        assert (error.value.status_code, error.value.code, error.value.message) == (
            409,
            "batch_download_active",
            "The batch cannot be recovered while a download is active.",
        )
        assert session == before
        assert runner._repository.get(batch_id) == row
        assert not runner._admitted_batch_ids
        handle.release()
        assert runner.recover(batch_id, token).attempt == 2
        wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
    finally:
        handle.release()
        runner.shutdown()


@pytest.mark.parametrize("mode", ["normal", "range", "send_failure", "cancel"])
def test_actual_file_response_releases_on_every_exit(mode):
    runner, _, batch_id, token = _ready()
    handle = runner.acquire_download(batch_id, token)
    original = handle.path.read_bytes()
    response = routes._PinnedFileResponse(
        handle, media_type="application/zip", filename="archive.zip"
    )
    messages = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        assert runner._active_downloads
        messages.append(message)
        if message["type"] == "http.response.body":
            if mode == "send_failure":
                raise OSError("send failed")
            if mode == "cancel":
                raise asyncio.CancelledError()

    scope = {"type": "http", "method": "GET", "headers": [], "extensions": {}}
    if mode == "range":
        scope["headers"] = [(b"range", b"bytes=0-9")]
    try:
        if mode in {"send_failure", "cancel"}:
            with pytest.raises(OSError if mode == "send_failure" else asyncio.CancelledError):
                asyncio.run(response(scope, receive, send))
        else:
            asyncio.run(response(scope, receive, send))
            assert messages[0]["status"] == (206 if mode == "range" else 200)
            body = b"".join(message.get("body", b"") for message in messages)
            assert body == (original[:10] if mode == "range" else original)
        assert not runner._active_downloads
    finally:
        handle.release()
        runner.shutdown()


@pytest.mark.parametrize("durable", [False, True])
def test_shutdown_drains_all_downloads_before_cleanup_and_owner_release(tmp_path, durable):
    runner, workspace, batch_id, token = _ready(tmp_path if durable else None)
    handles = [runner.acquire_download(batch_id, token) for _ in range(2)]
    waiting = Event()
    original_wait = runner._downloads_drained.wait_for

    def wait(predicate):
        waiting.set()
        return original_wait(predicate)

    with patch.object(runner._downloads_drained, "wait_for", side_effect=wait):
        thread = Thread(target=runner.shutdown)
        thread.start()
        try:
            assert waiting.wait(5)
            with pytest.raises(RuntimeError, match="shut down"):
                runner.acquire_download(batch_id, token)
            assert workspace.archive_path.read_bytes()
            if durable:
                with pytest.raises(BatchStorageOwnershipError):
                    service(storage_directory=tmp_path)
            handles[0].release()
            assert thread.is_alive()
            assert workspace.path.exists()
            handles[1].release()
            thread.join(5)
            assert not thread.is_alive()
        finally:
            for handle in handles:
                handle.release()
            thread.join(5)
    assert not runner._active_downloads
    if durable:
        replacement = service(storage_directory=tmp_path)
        replacement.shutdown()
    else:
        assert not workspace.path.exists()


def test_http_constructor_failure_releases_pin(tmp_path):
    app = create_app(ApiSettings(api_prefix="/api", batch_storage_directory=tmp_path))
    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post(
            "/api/batches/images/convert",
            files=[("file", ("one.png", make_image(), "image/png"))],
            data={"format": "jpg"},
        )
        batch_id = created.json()["id"]
        token = created.headers[BATCH_TOKEN_HEADER]
        runner = app.state.batch_service
        wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
        with patch.object(routes, "_PinnedFileResponse", side_effect=RuntimeError("constructor")):
            response = client.get(
                f"/api/batches/{batch_id}/download", headers={BATCH_TOKEN_HEADER: token}
            )
        assert response.status_code == 500
        assert not runner._active_downloads
        handle = runner.acquire_download(batch_id, token)
        try:
            assert (
                client.delete(
                    f"/api/batches/{batch_id}", headers={BATCH_TOKEN_HEADER: token}
                ).status_code
                == 204
            )
            assert handle.path.read_bytes()
        finally:
            handle.release()


def test_error_session_preserved_archive_remains_downloadable():
    runner, workspace, batch_id, token = _ready()
    runner._sessions[batch_id].phase = BatchExecutionPhase.ERROR
    handle = runner.acquire_download(batch_id, token)
    assert handle.path == workspace.archive_path
    handle.release()
    runner.shutdown()


def test_restart_finishes_failed_deferred_tombstone_without_pins(tmp_path):
    runner, workspace, batch_id, token = _ready(tmp_path)
    handle = runner.acquire_download(batch_id, token)
    runner.delete_session(batch_id, token)
    with patch.object(
        BatchSessionWorkspace, "cleanup", side_effect=BatchPersistenceError("private")
    ):
        handle.release()
    assert runner._repository.get(batch_id).phase == "deleting"
    runner.shutdown()
    replacement = service(storage_directory=tmp_path)
    try:
        assert not replacement._active_downloads
        assert batch_id not in replacement._sessions
        assert replacement._repository.get(batch_id) is None
        assert not workspace.path.exists()
    finally:
        replacement.shutdown()


def test_delete_during_actual_response_protects_archive_until_finally():
    runner, workspace, batch_id, token = _ready()
    handle = runner.acquire_download(batch_id, token)
    expected = handle.path.read_bytes()
    response = routes._PinnedFileResponse(handle)
    messages = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            runner.delete_session(batch_id, token)
        assert handle.path.read_bytes() == expected
        messages.append(message)

    try:
        asyncio.run(
            response(
                {"type": "http", "method": "GET", "headers": [], "extensions": {}}, receive, send
            )
        )
        assert b"".join(message.get("body", b"") for message in messages) == expected
        assert not workspace.path.exists()
        assert not runner._active_downloads
    finally:
        handle.release()
        runner.shutdown()

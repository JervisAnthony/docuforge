"""Capability-protected and crash-consistent batch deletion."""

import sqlite3
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import docuforge.api.batches as batches_module
from docuforge.api import ApiSettings, create_app
from docuforge.api.batch_access import BATCH_TOKEN_HEADER
from docuforge.api.batch_persistence import (
    DATABASE_NAME,
    BatchPersistenceError,
    BatchSessionWorkspace,
)
from docuforge.api.batches import BatchExecutionPhase
from docuforge.api.errors import ApiError
from tests.api.image_test_support import make_image
from tests.api.test_batch_service import create_request, service, wait_for


def _ready(storage: Path | None = None):
    runner = service(**({"storage_directory": storage} if storage else {}))
    workspace, request = create_request(runner, ("one.png",))
    grant = runner.create_session(request, workspace)
    batch_id = str(request.batch_id)
    wait_for(runner, batch_id, grant.access_token, BatchExecutionPhase.READY)
    return runner, workspace, batch_id, grant.access_token


@pytest.mark.parametrize("durable", [False, True])
def test_ready_deletion_removes_files_and_metadata(tmp_path: Path, durable: bool) -> None:
    runner, workspace, batch_id, token = _ready(tmp_path if durable else None)
    assert any(workspace.inputs_directory.rglob("*.png"))
    assert any(workspace.output_directory.rglob("*.jpg"))
    assert workspace.archive_path.is_file()
    repository = runner._repository
    if repository:
        assert repository.get(batch_id) is not None
    runner.delete_session(batch_id, token)
    assert batch_id not in runner._sessions
    assert not workspace.path.exists()
    if repository:
        assert repository.get(batch_id) is None
    for action in (
        runner.get, runner.cancel, runner.recover, runner.download_path, runner.delete_session
    ):
        with pytest.raises(ApiError) as error:
            action(batch_id, token)
        assert error.value.code == "batch_not_found"
    runner.shutdown()


def test_deletion_rejects_missing_wrong_and_cross_session_tokens(tmp_path: Path) -> None:
    runner, workspace, batch_id, token = _ready(tmp_path)
    other_workspace, other_request = create_request(runner, ("other.png",))
    other = runner.create_session(other_request, other_workspace)
    for denied in (None, "", "malformed token", "wrong-token", other.access_token):
        with pytest.raises(ApiError) as error:
            runner.delete_session(batch_id, denied)
        assert (error.value.status_code, error.value.code) == (404, "batch_not_found")
    assert runner.get(batch_id, token).phase is BatchExecutionPhase.READY
    assert workspace.path.exists()
    runner.shutdown()


def test_error_session_can_be_deleted(tmp_path: Path) -> None:
    runner = service(storage_directory=tmp_path)
    workspace, request = create_request(runner, ("one.png",))
    with patch.object(batches_module, "batch_convert_images", side_effect=RuntimeError("private")):
        grant = runner.create_session(request, workspace)
        wait_for(runner, str(request.batch_id), grant.access_token, BatchExecutionPhase.ERROR)
    runner.delete_session(str(request.batch_id), grant.access_token)
    assert not workspace.path.exists()
    assert runner._repository.get(str(request.batch_id)) is None
    runner.shutdown()


def test_active_and_cancelling_sessions_cannot_be_deleted(tmp_path: Path) -> None:
    runner = service(storage_directory=tmp_path)
    workspace, request = create_request(runner, ("one.png", "two.png"))
    entered, release = Event(), Event()
    real_runner = batches_module.batch_convert_images

    def block(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return real_runner(*args, **kwargs)

    with patch.object(batches_module, "batch_convert_images", side_effect=block):
        grant = runner.create_session(request, workspace)
        assert entered.wait(5)
        batch_id = str(request.batch_id)
        for phase in (BatchExecutionPhase.PROCESSING, BatchExecutionPhase.CANCELLING):
            assert runner.get(batch_id, grant.access_token).phase is phase
            with pytest.raises(ApiError) as error:
                runner.delete_session(batch_id, grant.access_token)
            assert (error.value.status_code, error.value.code) == (409, "batch_not_deletable")
            assert workspace.path.exists()
            if phase is BatchExecutionPhase.PROCESSING:
                runner.cancel(batch_id, grant.access_token)
        release.set()
        wait_for(runner, batch_id, grant.access_token, BatchExecutionPhase.READY)
    runner.shutdown()


def test_tombstone_is_persisted_before_cleanup(tmp_path: Path) -> None:
    runner, workspace, batch_id, token = _ready(tmp_path)
    repository = runner._repository
    assert repository is not None
    original_cleanup = BatchSessionWorkspace.cleanup

    def check_cleanup(value):
        assert repository.get(batch_id).phase == "deleting"
        assert runner._sessions[batch_id].phase is BatchExecutionPhase.DELETING
        original_cleanup(value)

    with patch.object(BatchSessionWorkspace, "cleanup", check_cleanup):
        runner.delete_session(batch_id, token)
    assert not workspace.path.exists()
    runner.shutdown()


def test_tombstone_save_failure_preserves_usable_session(tmp_path: Path) -> None:
    runner, workspace, batch_id, token = _ready(tmp_path)
    repository = runner._repository
    assert repository is not None
    with (
        patch.object(repository, "save", side_effect=BatchPersistenceError("private SQL")),
        pytest.raises(ApiError) as error,
    ):
        runner.delete_session(batch_id, token)
    assert (error.value.status_code, error.value.code) == (503, "batch_persistence_failed")
    assert runner.get(batch_id, token).phase is BatchExecutionPhase.READY
    assert runner.download_path(batch_id, token).is_file()
    assert workspace.path.exists()
    assert repository.get(batch_id).phase == "ready"
    runner.delete_session(batch_id, token)
    runner.shutdown()


@pytest.mark.parametrize("failure", ["workspace", "metadata"])
def test_partial_deletion_is_hidden_and_retryable(tmp_path: Path, failure: str) -> None:
    runner, workspace, batch_id, token = _ready(tmp_path)
    repository = runner._repository
    assert repository is not None
    target = BatchSessionWorkspace if failure == "workspace" else repository
    method = "cleanup" if failure == "workspace" else "delete"
    with (
        patch.object(target, method, side_effect=BatchPersistenceError("private path")),
        pytest.raises(ApiError) as error,
    ):
        runner.delete_session(batch_id, token)
    assert (error.value.status_code, error.value.code) == (503, "batch_deletion_failed")
    assert "private" not in error.value.message
    assert repository.get(batch_id).phase == "deleting"
    assert runner._sessions[batch_id].phase is BatchExecutionPhase.DELETING
    assert workspace.path.exists() is (failure == "workspace")
    for action in (runner.get, runner.cancel, runner.recover, runner.download_path):
        with pytest.raises(ApiError) as denied:
            action(batch_id, token)
        assert denied.value.code == "batch_not_found"
    runner.delete_session(batch_id, token)
    assert repository.get(batch_id) is None
    assert not workspace.path.exists()
    runner.shutdown()


@pytest.mark.parametrize("workspace_missing", [False, True])
def test_restart_finishes_tombstone_without_restoring_session(
    tmp_path: Path, workspace_missing: bool
) -> None:
    runner, workspace, batch_id, token = _ready(tmp_path)
    repository = runner._repository
    assert repository is not None
    repository.save(replace(repository.get(batch_id), phase="deleting"))
    runner.shutdown()
    if workspace_missing:
        workspace.cleanup()
    restored = service(storage_directory=tmp_path)
    assert repository.get(batch_id) is None
    assert not workspace.path.exists()
    assert batch_id not in restored._sessions
    with pytest.raises(ApiError) as error:
        restored.get(batch_id, token)
    assert error.value.code == "batch_not_found"
    restored.shutdown()


def test_startup_cleanup_failure_fails_closed_and_retries(tmp_path: Path) -> None:
    runner, workspace, batch_id, _ = _ready(tmp_path)
    repository = runner._repository
    assert repository is not None
    repository.save(replace(repository.get(batch_id), phase="deleting"))
    runner.shutdown()
    with patch.object(
        batches_module, "cleanup_durable_workspace",
        side_effect=BatchPersistenceError("private path"),
    ), pytest.raises(BatchPersistenceError):
        service(storage_directory=tmp_path)
    assert repository.get(batch_id).phase == "deleting"
    assert workspace.path.exists()
    restored = service(storage_directory=tmp_path)
    assert repository.get(batch_id) is None
    restored.shutdown()


def test_startup_does_not_decode_committed_tombstone(tmp_path: Path) -> None:
    runner, workspace, batch_id, _ = _ready(tmp_path)
    repository = runner._repository
    assert repository is not None
    repository.save(replace(repository.get(batch_id), phase="deleting"))
    runner.shutdown()
    with sqlite3.connect(tmp_path / DATABASE_NAME) as connection:
        connection.execute(
            "UPDATE batch_sessions SET request_json=? WHERE batch_id=?",
            ("not-json", batch_id),
        )
    restored = service(storage_directory=tmp_path)
    assert not workspace.path.exists()
    assert batch_id not in restored._sessions
    assert repository.get(batch_id) is None
    restored.shutdown()


def test_http_delete_contract_and_custom_prefix(tmp_path: Path) -> None:
    settings = ApiSettings(api_prefix="/custom", batch_storage_directory=tmp_path)
    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/custom/batches/images/convert",
            files=[("file", ("one.png", make_image(), "image/png")), ("format", (None, "jpeg"))],
        )
        location = accepted.headers["location"]
        token = accepted.headers[BATCH_TOKEN_HEADER]
        other = client.post(
            "/custom/batches/images/convert",
            files=[("file", ("other.png", make_image(), "image/png")), ("format", (None, "jpeg"))],
        )
        for denied in (
            {},
            {BATCH_TOKEN_HEADER: ""},
            {BATCH_TOKEN_HEADER: "malformed token"},
            {BATCH_TOKEN_HEADER: "wrong"},
            {BATCH_TOKEN_HEADER: other.headers[BATCH_TOKEN_HEADER]},
        ):
            response = client.delete(location, headers=denied)
            assert (response.status_code, response.json()["code"]) == (404, "batch_not_found")
            assert response.headers["cache-control"] == "no-store"
        deadline = monotonic() + 5
        while True:
            status = client.get(location, headers={BATCH_TOKEN_HEADER: token})
            if status.json()["phase"] == "ready":
                break
            assert monotonic() < deadline
            sleep(0.01)
        deleted = client.delete(location, headers={BATCH_TOKEN_HEADER: token})
        assert deleted.status_code == 204
        assert deleted.content == b""
        assert deleted.headers["cache-control"] == "no-store"
        for method, suffix in (
            (client.get, ""), (client.delete, ""), (client.post, "/cancel"),
            (client.post, "/recover"), (client.get, "/download"),
        ):
            response = method(location + suffix, headers={BATCH_TOKEN_HEADER: token})
            assert (response.status_code, response.json()["code"]) == (404, "batch_not_found")
            assert response.headers["cache-control"] == "no-store"


def test_http_active_delete_is_rejected_without_cancelling() -> None:
    entered, release = Event(), Event()
    real_runner = batches_module.batch_convert_images

    def block(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return real_runner(*args, **kwargs)

    with (
        patch.object(batches_module, "batch_convert_images", side_effect=block),
        TestClient(create_app()) as client,
    ):
        accepted = client.post(
            "/api/v1/batches/images/convert",
            files=[("file", ("one.png", make_image(), "image/png")), ("format", (None, "jpeg"))],
        )
        assert entered.wait(5)
        location = accepted.headers["location"]
        headers = {BATCH_TOKEN_HEADER: accepted.headers[BATCH_TOKEN_HEADER]}
        deleted = client.delete(location, headers=headers)
        assert (deleted.status_code, deleted.json()["code"]) == (409, "batch_not_deletable")
        assert deleted.headers["cache-control"] == "no-store"
        status = client.get(location, headers=headers)
        assert status.json()["phase"] == "processing"
        assert status.json()["cancellation_requested"] is False
        release.set()


def test_http_error_session_deletes_and_deletion_failure_is_no_store() -> None:
    with (
        patch.object(batches_module, "batch_convert_images", side_effect=RuntimeError("private")),
        TestClient(create_app()) as client,
    ):
        accepted = client.post(
            "/api/v1/batches/images/convert",
            files=[("file", ("one.png", make_image(), "image/png")), ("format", (None, "jpeg"))],
        )
        location = accepted.headers["location"]
        headers = {BATCH_TOKEN_HEADER: accepted.headers[BATCH_TOKEN_HEADER]}
        deadline = monotonic() + 5
        while client.get(location, headers=headers).json()["phase"] != "error":
            assert monotonic() < deadline
            sleep(0.01)
        with patch.object(
            client.app.state.batch_service,
            "delete_session",
            side_effect=ApiError(
                status_code=503,
                code="batch_deletion_failed",
                message="Retry the deletion.",
            ),
        ):
            failed = client.delete(location, headers=headers)
        assert (failed.status_code, failed.json()["code"]) == (503, "batch_deletion_failed")
        assert failed.headers["cache-control"] == "no-store"
        deleted = client.delete(location, headers=headers)
        assert deleted.status_code == 204
        assert deleted.headers["cache-control"] == "no-store"

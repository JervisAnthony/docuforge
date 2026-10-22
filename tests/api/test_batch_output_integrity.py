"""Retained conversion trust, journal ordering, and clean recovery workspaces."""

import json
import os
from dataclasses import replace
from unittest.mock import patch

import pytest
from PIL import Image

from docuforge.api.batch_artifacts import retained_outputs_are_valid
from docuforge.api.batch_persistence import (
    BatchPersistenceError,
    BatchSessionWorkspace,
)
from docuforge.api.batches import BatchExecutionPhase, BatchSessionError
from docuforge.api.errors import ApiError
from docuforge.batch import BatchDocumentConvertRequest, BatchDocumentInput
from tests.api.test_batch_deletion import _ready
from tests.api.test_batch_service import create_request, service, wait_for
from tests.batch.test_document import write_office


def document_ready(storage=None):
    runner = service(**({"storage_directory": storage} if storage else {}))
    workspace = runner.create_workspace()
    source = workspace.inputs_directory / "proposal.docx"
    write_office(source)
    request = BatchDocumentConvertRequest(
        (BatchDocumentInput(source),), workspace.output_directory, workspace.batch_id
    )
    grant = runner.create_session(request, workspace)
    batch_id = str(request.batch_id)
    wait_for(runner, batch_id, grant.access_token, BatchExecutionPhase.READY)
    return runner, workspace, batch_id, grant.access_token


def packaging(session):
    session.phase = BatchExecutionPhase.ERROR
    session.session_error = BatchSessionError(
        "batch_packaging_failed", "The batch outputs could not be packaged."
    )


def symlink(path, target, directory=False):
    try:
        path.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("symlink creation unavailable")


@pytest.mark.parametrize("kind", ["valid", "missing", "bytes", "format", "symlink", "outside"])
def test_image_validator(tmp_path, kind):
    runner, _workspace, batch_id, _ = _ready()
    try:
        session = runner._sessions[batch_id]
        output = session.result.outputs[0]
        if kind == "missing":
            output.output_path.unlink()
        elif kind == "bytes":
            output.output_path.write_bytes(b"broken")
        elif kind == "format":
            Image.new("RGB", (8, 8)).save(output.output_path, format="PNG")
        elif kind in {"symlink", "outside"}:
            other = tmp_path / output.output_path.name
            other.write_bytes(output.output_path.read_bytes())
            if kind == "symlink":
                output.output_path.unlink()
                symlink(output.output_path, other)
            else:
                result = replace(session.result, outputs=(replace(output, output_path=other),))
                assert not retained_outputs_are_valid(session.request, result)
                return
        assert retained_outputs_are_valid(session.request, session.result) == (kind == "valid")
        assert not retained_outputs_are_valid(object(), session.result)
        assert not retained_outputs_are_valid(session.request, object())
    finally:
        runner.shutdown()


@pytest.mark.parametrize(
    "kind", ["valid", "missing", "empty", "signature", "symlink", "directory", "fifo"]
)
def test_pdf_validator(tmp_path, kind):
    runner, _workspace, batch_id, _ = document_ready()
    try:
        session = runner._sessions[batch_id]
        path = session.result.outputs[0].output_path
        if kind == "missing":
            path.unlink()
        elif kind == "empty":
            path.write_bytes(b"")
        elif kind == "signature":
            path.write_bytes(b"wrong PDF signature")
        elif kind == "symlink":
            other = tmp_path / "external.pdf"
            other.write_bytes(path.read_bytes())
            path.unlink()
            symlink(path, other)
        elif kind == "directory":
            path.unlink()
            path.mkdir()
        elif kind == "fifo":
            if not hasattr(os, "mkfifo"):
                pytest.skip("FIFO creation unavailable")
            path.unlink()
            os.mkfifo(path)
        assert retained_outputs_are_valid(session.request, session.result) == (kind == "valid")
    finally:
        runner.shutdown()


@pytest.mark.parametrize("corrupt", [False, True])
def test_selective_recovery_only_reuses_trusted_outputs(corrupt):
    runner = service()
    try:
        workspace, request = create_request(runner)
        request.items[1].input_path.write_bytes(b"bad image")
        grant = runner.create_session(request, workspace)
        batch_id, token = str(request.batch_id), grant.access_token
        wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
        session = runner._sessions[batch_id]
        old_output = session.result.outputs[0].output_path
        original_bytes = old_output.read_bytes()
        Image.new("RGB", (8, 8)).save(request.items[1].input_path)
        if corrupt:
            old_output.write_bytes(b"bad output")
        import docuforge.batch.image as image_module

        with patch.object(
            image_module, "convert_image_path", wraps=image_module.convert_image_path
        ) as convert:
            runner.recover(batch_id, token)
            wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
        assert convert.call_count == (2 if corrupt else 1)
        assert session.attempt == 2
        if not corrupt:
            assert old_output.read_bytes() == original_bytes
    finally:
        runner.shutdown()


@pytest.mark.parametrize("durable", [False, True])
def test_corrupt_packaging_forces_clean_full_retry(tmp_path, durable):
    runner, workspace, batch_id, token = _ready(tmp_path if durable else None)
    try:
        session = runner._sessions[batch_id]
        packaging(session)
        old = session.result
        old.outputs[0].output_path.write_bytes(b"bad")
        (workspace.output_directory / "stale").write_bytes(b"stale")
        inputs = {p: p.read_bytes() for p in workspace.inputs_directory.rglob("*") if p.is_file()}
        original_reset = BatchSessionWorkspace.reset_generated_artifacts

        def reset(ws):
            assert session.result is None and session.archive_path is None
            assert session.session_error.code == "batch_output_integrity_failed"
            if durable:
                row = runner._repository.get(batch_id)
                assert row.result_json is None and not row.archive_available
                assert row.updated_at == session.updated_at
            original_reset(ws)
            assert not list(ws.output_directory.iterdir())

        with patch.object(BatchSessionWorkspace, "reset_generated_artifacts", reset):
            accepted = runner.recover(batch_id, token)
        assert accepted.attempt == 2
        wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
        assert session.result is not old
        assert str(session.batch.id) == batch_id
        assert retained_outputs_are_valid(session.request, session.result)
        assert not (workspace.output_directory / "stale").exists()
        assert all(p.read_bytes() == data for p, data in inputs.items())
        assert runner.download_path(batch_id, token).is_file()
    finally:
        runner.shutdown()


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_trusted_packaging_repairs_archive_node(tmp_path, kind):
    runner, workspace, batch_id, token = _ready()
    try:
        session = runner._sessions[batch_id]
        packaging(session)
        result = session.result
        workspace.archive_path.unlink()
        sentinel = tmp_path / "sentinel"
        sentinel.write_bytes(b"safe")
        if kind == "directory":
            workspace.archive_path.mkdir()
        else:
            symlink(workspace.archive_path, sentinel)
        runner.recover(batch_id, token)
        wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
        assert session.result is result
        assert sentinel.read_bytes() == b"safe"
        assert not workspace.archive_path.is_symlink()
    finally:
        runner.shutdown()


@pytest.mark.parametrize("kind", ["directory", "file", "missing", "symlink", "fifo"])
def test_reset_preserves_inputs_and_external_nodes(tmp_path, kind):
    workspace = BatchSessionWorkspace.ephemeral()
    try:
        source = workspace.inputs_directory / "input"
        source.write_bytes(b"original")
        outside = tmp_path / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_bytes(b"safe")
        workspace.output_directory.rmdir()
        if kind == "directory":
            workspace.output_directory.mkdir()
            (workspace.output_directory / "stale").write_bytes(b"stale")
        elif kind == "file":
            workspace.output_directory.write_bytes(b"bad node")
        elif kind == "symlink":
            symlink(workspace.output_directory, outside, True)
        elif kind == "fifo":
            if not hasattr(os, "mkfifo"):
                pytest.skip("FIFO creation unavailable")
            os.mkfifo(workspace.output_directory)
        symlink(workspace.archive_path, sentinel)
        for _ in range(2):
            workspace.reset_generated_artifacts()
            assert workspace.output_directory.is_dir()
            assert not workspace.output_directory.is_symlink()
            assert not list(workspace.output_directory.iterdir())
            assert not workspace.archive_path.exists()
            assert source.read_bytes() == b"original"
            assert sentinel.read_bytes() == b"safe"
    finally:
        workspace.cleanup()


@pytest.mark.parametrize("failure", ["persist", "reset", "submit", "queued"])
def test_integrity_failure_ordering_and_retry(tmp_path, failure):
    runner, _workspace, batch_id, token = _ready(tmp_path)
    try:
        session = runner._sessions[batch_id]
        packaging(session)
        runner._persist_locked(session)
        session.result.outputs[0].output_path.write_bytes(b"bad")
        before = replace(session)
        save = runner._repository.save
        real_reset = BatchSessionWorkspace.reset_generated_artifacts
        real_submit = runner._executor.submit

        def reset_workspace(ws):
            if failure == "reset":
                raise BatchPersistenceError("private")
            real_reset(ws)

        def submit_worker(*args):
            if failure == "submit":
                raise RuntimeError("private")
            return real_submit(*args)

        def persist(row):
            if failure == "persist" or (failure == "queued" and row.phase == "queued"):
                raise BatchPersistenceError("private")
            save(row)

        with (
            patch.object(runner._repository, "save", side_effect=persist),
            patch.object(
                BatchSessionWorkspace,
                "reset_generated_artifacts",
                side_effect=reset_workspace,
                autospec=True,
            ) as reset,
            patch.object(runner._executor, "submit", side_effect=submit_worker) as submit,
            pytest.raises(ApiError) as caught,
        ):
            runner.recover(batch_id, token)
        assert caught.value.status_code == 503
        assert session.attempt == before.attempt and session.updated_at == before.updated_at
        assert not runner._admitted_batch_ids
        if failure == "persist":
            assert session == before
            reset.assert_not_called()
            submit.assert_not_called()
        else:
            assert session.result is None and session.archive_path is None
            assert session.session_error == BatchSessionError(
                "batch_output_integrity_failed",
                "The retained batch outputs could not be verified. Retry the batch.",
            )
        if failure == "reset":
            assert caught.value.code == "batch_recovery_failed"
            assert caught.value.message == (
                "The batch could not be prepared for recovery. Try again later."
            )
            submit.assert_not_called()
        runner.recover(batch_id, token)
        wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
        assert session.attempt == 2
    finally:
        runner.shutdown()


@pytest.mark.parametrize("gate", ["auth", "download", "storage", "capacity"])
def test_gates_precede_mutation(tmp_path, gate):
    runner, _workspace, batch_id, token = _ready(tmp_path)
    try:
        session = runner._sessions[batch_id]
        handle = runner.acquire_download(batch_id, token) if gate == "download" else None
        packaging(session)
        session.result.outputs[0].output_path.write_bytes(b"bad")
        before = replace(session)
        code = {
            "auth": "batch_not_found",
            "download": "batch_download_active",
            "storage": "batch_storage_pressure",
            "capacity": "batch_capacity_exceeded",
        }[gate]
        with (
            patch("docuforge.api.batches.retained_outputs_are_valid", return_value=False) as scan,
            patch.object(
                runner,
                "_require_storage_locked",
                side_effect=(
                    ApiError(status_code=507, code=code, message="safe")
                    if gate == "storage"
                    else None
                ),
            ),
            patch.object(
                runner,
                "_reserve_admission_locked",
                side_effect=(
                    ApiError(status_code=503, code=code, message="safe")
                    if gate == "capacity"
                    else None
                ),
            ),
            patch.object(runner._repository, "save") as save,
            patch.object(BatchSessionWorkspace, "reset_generated_artifacts") as reset,
            pytest.raises(ApiError) as caught,
        ):
            runner.recover(batch_id, "wrong" if gate == "auth" else token)
        assert caught.value.code == code
        if gate in {"auth", "download"}:
            scan.assert_not_called()
        save.assert_not_called()
        reset.assert_not_called()
        assert session == before
        if handle:
            handle.release()
    finally:
        runner.shutdown()


@pytest.mark.parametrize("kind", ["bytes", "missing", "format", "metadata"])
def test_restart_distinguishes_metadata_and_artifact_corruption(tmp_path, kind):
    runner, _workspace, batch_id, token = _ready(tmp_path)
    row = runner._repository.get(batch_id)
    output = runner._sessions[batch_id].result.outputs[0].output_path
    if kind == "metadata":
        payload = json.loads(row.result_json)
        payload["outputs"][0]["output"] = "../escape.jpg"
        runner._repository.save(replace(row, result_json=json.dumps(payload)))
    elif kind == "missing":
        output.unlink()
    elif kind == "format":
        Image.new("RGB", (8, 8)).save(output, format="PNG")
    else:
        output.write_bytes(b"bad")
    runner.shutdown()
    if kind == "metadata":
        with pytest.raises(BatchPersistenceError):
            service(storage_directory=tmp_path)
        return
    restored = service(storage_directory=tmp_path)
    try:
        session = restored._sessions[batch_id]
        assert restored.get(batch_id, token).can_recover
        assert session.phase is BatchExecutionPhase.ERROR
        assert session.result is None and session.archive_path is None
        assert session.session_error.code == "batch_output_integrity_failed"
        assert session.updated_at == row.updated_at and session.attempt == row.attempt
        assert restored._repository.get(batch_id).result_json is None
        restored.recover(batch_id, token)
        wait_for(restored, batch_id, token, BatchExecutionPhase.READY)
    finally:
        restored.shutdown()


def test_pdf_corruption_restart_keeps_healthy_sibling(tmp_path):
    runner, _workspace, batch_id, token = document_ready(tmp_path)
    other_ws, other_request = create_request(runner, ("sibling.png",))
    other_grant = runner.create_session(other_request, other_ws)
    wait_for(
        runner, str(other_request.batch_id), other_grant.access_token, BatchExecutionPhase.READY
    )
    runner._sessions[batch_id].result.outputs[0].output_path.write_bytes(b"bad PDF")
    runner.shutdown()
    restored = service(storage_directory=tmp_path)
    try:
        assert restored.get(batch_id, token).session_error.code == "batch_output_integrity_failed"
        assert (
            restored.get(str(other_request.batch_id), other_grant.access_token).phase
            is BatchExecutionPhase.READY
        )
        restored.recover(batch_id, token)
        wait_for(restored, batch_id, token, BatchExecutionPhase.READY)
        assert retained_outputs_are_valid(
            restored._sessions[batch_id].request, restored._sessions[batch_id].result
        )
    finally:
        restored.shutdown()


def test_interrupted_full_retry_clears_unpublished_stale_files(tmp_path):
    runner, workspace, batch_id, token = _ready(tmp_path)
    session = runner._sessions[batch_id]
    session.result = None
    session.archive_path = None
    session.phase = BatchExecutionPhase.PROCESSING
    runner._persist_locked(session)
    (workspace.output_directory / "stray").write_bytes(b"stale")
    runner.shutdown()
    restored = service(storage_directory=tmp_path)
    try:
        assert restored.get(batch_id, token).session_error.code == "batch_execution_interrupted"
        restored.recover(batch_id, token)
        wait_for(restored, batch_id, token, BatchExecutionPhase.READY)
        assert not (workspace.output_directory / "stray").exists()
    finally:
        restored.shutdown()


def test_failed_queued_publication_cannot_execute_against_later_retry(tmp_path):
    runner, _workspace, batch_id, token = _ready(tmp_path)
    try:
        session = runner._sessions[batch_id]
        packaging(session)
        session.result.outputs[0].output_path.write_bytes(b"bad")
        submitted = []
        save = runner._repository.save

        def fail_queued(row):
            if row.phase == "queued":
                raise BatchPersistenceError("private")
            save(row)

        with patch.object(
            runner._executor, "submit", side_effect=lambda *args: submitted.append(args)
        ):
            with (
                patch.object(runner._repository, "save", side_effect=fail_queued),
                pytest.raises(ApiError),
            ):
                runner.recover(batch_id, token)
            runner.recover(batch_id, token)
        assert session.attempt == 2
        stale, current = submitted
        stale[0](*stale[1:])
        assert session.phase is BatchExecutionPhase.QUEUED and session.result is None
        current[0](*current[1:])
        assert session.phase is BatchExecutionPhase.READY
    finally:
        runner.shutdown()


@pytest.mark.parametrize("has_result", [False, True])
def test_reset_failure_keeps_existing_nonintegrity_terminal_state(has_result):
    runner, _workspace, batch_id, token = _ready()
    try:
        session = runner._sessions[batch_id]
        packaging(session)
        if not has_result:
            session.result = None
            session.archive_path = None
        before = replace(session)
        with (
            patch.object(
                BatchSessionWorkspace,
                "reset_archive_artifact" if has_result else "reset_generated_artifacts",
                side_effect=BatchPersistenceError("private"),
            ),
            patch.object(runner._executor, "submit") as submit,
            pytest.raises(ApiError) as caught,
        ):
            runner.recover(batch_id, token)
        assert caught.value.code == "batch_recovery_failed"
        assert session == before
        submit.assert_not_called()
        assert not runner._admitted_batch_ids
    finally:
        runner.shutdown()


@pytest.mark.parametrize("has_result", [False, True])
def test_restart_tolerates_interrupted_generated_reset(tmp_path, has_result):
    runner, workspace, batch_id, token = _ready(tmp_path)
    session = runner._sessions[batch_id]
    if not has_result:
        session.result = None
        session.archive_path = None
        packaging(session)
        runner._persist_locked(session)
    runner.shutdown()
    for path in workspace.output_directory.iterdir():
        path.unlink()
    workspace.output_directory.rmdir()
    restored = service(storage_directory=tmp_path)
    try:
        assert restored.get(batch_id, token).can_recover
        restored.recover(batch_id, token)
        wait_for(restored, batch_id, token, BatchExecutionPhase.READY)
    finally:
        restored.shutdown()


def test_expired_corrupt_output_is_deleted_before_decode(tmp_path):
    runner, workspace, batch_id, _token = _ready(tmp_path)
    session = runner._sessions[batch_id]
    session.result.outputs[0].output_path.unlink()
    row = runner._repository.get(batch_id)
    runner.shutdown()
    with patch("docuforge.api.batches.decode_record") as decode:
        restored = service(storage_directory=tmp_path, clock=lambda: row.updated_at + 4000)
    try:
        decode.assert_not_called()
        assert batch_id not in restored._sessions
        assert not workspace.path.exists()
    finally:
        restored.shutdown()

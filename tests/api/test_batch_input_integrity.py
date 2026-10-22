"""Original accepted bytes remain authoritative across queueing, retry and restart."""

import hashlib
import json
import os
import sqlite3
from dataclasses import FrozenInstanceError, replace
from io import BytesIO
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from docuforge.api.batch_inputs import (
    INPUT_HASH_CHUNK_BYTES,
    BatchInputFingerprint,
    BatchInputIntegrityError,
    _stream_digest,
    inputs_are_valid,
)
from docuforge.api.batch_persistence import (
    DATABASE_NAME,
    BatchPersistenceError,
    BatchSessionWorkspace,
)
from docuforge.api.batches import BatchExecutionPhase as Phase
from docuforge.api.batches import BatchSessionError
from docuforge.api.errors import ApiError
from docuforge.batch import (
    BatchDocumentConvertRequest,
    BatchDocumentInput,
    BatchImageCompressRequest,
    BatchImageResizeRequest,
)
from tests.api.test_batch_deletion import _ready
from tests.api.test_batch_service import create_request, service, wait_for
from tests.api.test_batch_worker_publication import execute
from tests.batch.test_document import write_office


def accept_queued(runner, kind="convert", names=("one.png", "two.png")):
    if kind == "document":
        workspace = runner.create_workspace()
        source = workspace.inputs_directory / "résumé one.docx"
        write_office(source)
        request = BatchDocumentConvertRequest(
            (BatchDocumentInput(source),), workspace.output_directory, workspace.batch_id
        )
    else:
        workspace, request = create_request(runner, names)
        if kind == "resize":
            request = BatchImageResizeRequest(
                request.items,
                request.output_directory,
                "jpg",
                max_width=4,
                batch_id=request.batch_id,
            )
        elif kind == "compress":
            request = BatchImageCompressRequest(
                request.items,
                request.output_directory,
                "jpg",
                quality=70,
                batch_id=request.batch_id,
            )
        elif kind == "empty":
            request.items[0].input_path.write_bytes(b"")
    with patch.object(runner._executor, "submit"):
        grant = runner.create_session(request, workspace)
    return workspace, request, grant


@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("kind", ["convert", "resize", "compress", "document", "empty"])
def test_acceptance_records_exact_ordered_bytes(tmp_path, durable, kind):
    runner = service(**({"storage_directory": tmp_path} if durable else {}))
    try:
        _workspace, request, grant = accept_queued(runner, kind, ("résumé one.png", "two.png"))
        session = runner._sessions[str(request.batch_id)]
        manifest = session.input_manifest
        assert len(manifest) == len(request.items)
        for item, fingerprint in zip(request.items, manifest, strict=True):
            data = item.input_path.read_bytes()
            assert fingerprint == BatchInputFingerprint(
                item.id, len(data), hashlib.sha256(data).hexdigest()
            )
            with pytest.raises(FrozenInstanceError):
                fingerprint.size_bytes = 5
        assert grant.access_token not in repr(manifest)
        if durable:
            payload = json.loads(runner._repository.get(str(request.batch_id)).input_manifest_json)
            assert payload["algorithm"] == "sha256" and payload["version"] == 1
            assert [v["item_id"] for v in payload["items"]] == [str(i.id) for i in request.items]
        else:
            assert runner._repository is None
    finally:
        runner.shutdown()


def test_hashing_uses_bounded_reads_and_counts_actual_bytes():
    class BoundedStream(BytesIO):
        def read(self, size=-1):
            assert 0 < size <= INPUT_HASH_CHUNK_BYTES
            return super().read(size)

    data = b"a" * (2 * INPUT_HASH_CHUNK_BYTES + 17)
    assert _stream_digest(BoundedStream(data)) == (len(data), hashlib.sha256(data).hexdigest())


@pytest.mark.parametrize(
    "kind",
    ["same_size", "truncated", "appended", "missing", "directory", "symlink", "fifo", "denied"],
)
def test_input_verifier_rejects_changed_or_unsafe_files(tmp_path, kind):
    runner = service()
    try:
        workspace, request, _grant = accept_queued(runner)
        manifest = runner._sessions[str(request.batch_id)].input_manifest
        source = request.items[0].input_path
        original = source.read_bytes()
        sentinel = tmp_path / "external"
        sentinel.write_bytes(original)
        if kind == "same_size":
            source.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        elif kind == "truncated":
            source.write_bytes(original[:-1])
        elif kind == "appended":
            source.write_bytes(original + b"x")
        elif kind in {"missing", "directory", "symlink", "fifo"}:
            source.unlink()
            if kind == "directory":
                source.mkdir()
            elif kind == "symlink":
                try:
                    source.symlink_to(sentinel)
                except OSError:
                    pytest.skip("symlink creation unavailable")
            elif kind == "fifo":
                if not hasattr(os, "mkfifo"):
                    pytest.skip("FIFO creation unavailable")
                os.mkfifo(source)
        if kind == "denied":
            with patch("docuforge.api.batch_inputs.os.open", side_effect=PermissionError):
                assert not inputs_are_valid(request, manifest, workspace.inputs_directory)
        else:
            assert not inputs_are_valid(request, manifest, workspace.inputs_directory)
        assert sentinel.read_bytes() == original
        assert manifest == runner._sessions[str(request.batch_id)].input_manifest
    finally:
        runner.shutdown()


@pytest.mark.parametrize("kind", ["convert", "resize", "compress", "document"])
@pytest.mark.parametrize("recovery", [False, True])
def test_queued_worker_rechecks_before_any_converter(tmp_path, kind, recovery):
    runner = service(storage_directory=tmp_path)
    try:
        _workspace, request, grant = accept_queued(runner, kind)
        batch_id, token = str(request.batch_id), grant.access_token
        session = runner._sessions[batch_id]
        if recovery:
            execute(runner, batch_id)
            # Force full retry from the existing original manifest.
            with runner._lock:
                candidate = replace(
                    session,
                    phase=Phase.ERROR,
                    result=None,
                    archive_path=None,
                    session_error=BatchSessionError("batch_execution_failed", "Safe error."),
                )
                runner._publish_worker_state_locked(session, candidate=candidate)
            with patch.object(runner._executor, "submit"):
                runner.recover(batch_id, token)
        old_manifest = session.input_manifest
        source = request.items[0].input_path
        data = source.read_bytes()
        source.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        with patch.object(runner, "_run_request") as convert:
            execute(runner, batch_id)
        convert.assert_not_called()
        assert session.phase is Phase.ERROR
        assert session.session_error.code == "batch_input_integrity_failed"
        assert session.session_error.message == "The original batch inputs could not be verified."
        assert not runner._admitted_batch_ids and session.archive_path is None
        assert session.input_manifest is old_manifest
        assert (
            json.loads(runner._repository.get(batch_id).session_error_json)["code"]
            == "batch_input_integrity_failed"
        )
    finally:
        runner.shutdown()


@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("mode", ["full", "selective", "bad_outputs"])
def test_recovery_refusal_precedes_reset_admission_and_publication(tmp_path, durable, mode):
    runner = service(
        **(
            {"storage_directory": tmp_path, "max_published_output_bytes": 800}
            if durable
            else {"max_published_output_bytes": 800}
        )
    )
    try:
        workspace, request = create_request(runner)
        if mode == "full":
            with patch(
                "docuforge.api.batches.batch_convert_images", side_effect=RuntimeError("private")
            ):
                grant = runner.create_session(request, workspace)
                wait_for(runner, str(request.batch_id), grant.access_token, Phase.ERROR)
        else:
            grant = runner.create_session(request, workspace)
            wait_for(runner, str(request.batch_id), grant.access_token, Phase.READY)
        batch_id, token = str(request.batch_id), grant.access_token
        session = runner._sessions[batch_id]
        if mode != "full":
            assert (
                session.result.batch.completed_count == 1 and session.result.batch.failed_count == 1
            )
        if mode == "bad_outputs":
            session.result.outputs[0].output_path.write_bytes(b"bad")
        source = request.items[0].input_path
        original = source.read_bytes()
        source.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        before = replace(session)
        row = runner._repository.get(batch_id) if durable else None
        files = {p: p.read_bytes() for p in workspace.output_directory.rglob("*") if p.is_file()}
        archive = workspace.archive_path.read_bytes() if workspace.archive_path.exists() else None
        with (
            patch.object(BatchSessionWorkspace, "reset_generated_artifacts") as reset,
            patch.object(runner, "_reserve_admission_locked") as admission,
            patch.object(runner._executor, "submit") as submit,
            pytest.raises(ApiError) as error,
        ):
            runner.recover(batch_id, token)
        assert (error.value.status_code, error.value.code, error.value.message) == (
            409,
            "batch_input_integrity_failed",
            "The original batch inputs could not be verified.",
        )
        reset.assert_not_called()
        admission.assert_not_called()
        submit.assert_not_called()
        assert session == before and not runner._admitted_batch_ids
        assert all(p.read_bytes() == data for p, data in files.items())
        assert (
            workspace.archive_path.read_bytes() if workspace.archive_path.exists() else None
        ) == archive
        if durable:
            assert runner._repository.get(batch_id) == row
        source.write_bytes(original)
        runner._max_published_output_bytes = 10000
        runner.recover(batch_id, token)
        wait_for(runner, batch_id, token, Phase.READY)
        assert session.attempt == 2 and session.batch.completed_count == 2
        assert session.input_manifest is before.input_manifest
    finally:
        runner.shutdown()


@pytest.mark.parametrize("kind", ["missing", "changed"])
def test_ready_restart_and_packaging_repair_do_not_require_original_uploads(tmp_path, kind):
    runner, workspace, batch_id, token = _ready(tmp_path)
    session = runner._sessions[batch_id]
    source = session.request.items[0].input_path
    manifest = session.input_manifest
    archive = workspace.archive_path.read_bytes()
    other_workspace, other_request = create_request(runner, ("healthy.png",))
    other_grant = runner.create_session(other_request, other_workspace)
    wait_for(runner, str(other_request.batch_id), other_grant.access_token, Phase.READY)
    runner.shutdown()
    if kind == "missing":
        source.unlink()
    else:
        source.write_bytes(b"changed input")
    restored = service(storage_directory=tmp_path)
    try:
        session = restored._sessions[batch_id]
        retained = session.result
        with patch(
            "docuforge.api.batches.inputs_are_valid", side_effect=AssertionError("unexpected scan")
        ):
            assert restored.get(batch_id, token).phase is Phase.READY
            handle = restored.acquire_download(batch_id, token)
            assert handle.path.read_bytes() == archive
            handle.release()
            workspace.archive_path.write_bytes(b"bad zip")
            with pytest.raises(ApiError):
                restored.acquire_download(batch_id, token)
            with patch.object(restored, "_run_request") as convert:
                restored.recover(batch_id, token)
                wait_for(restored, batch_id, token, Phase.READY)
            convert.assert_not_called()
        assert session.result is retained and session.input_manifest == manifest
        assert (
            restored.get(str(other_request.batch_id), other_grant.access_token).phase is Phase.READY
        )
        # Corrupt outputs too: packaging now requires a full retry, so sources gate reset.
        workspace.archive_path.write_bytes(b"bad zip")
        with pytest.raises(ApiError):
            restored.acquire_download(batch_id, token)
        session.result.outputs[0].output_path.write_bytes(b"bad output")
        before = replace(session)
        with pytest.raises(ApiError) as error:
            restored.recover(batch_id, token)
        assert error.value.code == "batch_input_integrity_failed" and session == before
    finally:
        restored.shutdown()


def test_acceptance_failure_uses_route_abandonment_without_publishing_capability(tmp_path):
    app = create_app(ApiSettings(batch_storage_directory=tmp_path))
    with TestClient(app) as client:
        runner = app.state.batch_service
        with (
            patch(
                "docuforge.api.batches.capture_input_manifest",
                side_effect=BatchInputIntegrityError("private"),
            ),
            patch.object(runner._executor, "submit") as submit,
        ):
            from tests.api.image_test_support import make_image

            response = client.post(
                "/api/v1/batches/images/convert",
                data={"format": "jpg"},
                files=[("file", ("one.png", make_image(), "image/png"))],
            )
        assert response.status_code == 503
        assert response.json() == {
            "code": "batch_input_unavailable",
            "message": "The uploaded batch inputs could not be verified. Try again later.",
        }
        assert "Retry-After" not in response.headers
        submit.assert_not_called()
        assert not runner._sessions and not runner._admitted_batch_ids
        assert runner._repository.list_all() == () and not list(runner._sessions_root.iterdir())


@pytest.mark.parametrize("gate", ["auth", "download"])
def test_authorization_and_download_pin_precede_input_scan(gate):
    runner, _workspace, batch_id, token = _ready()
    try:
        session = runner._sessions[batch_id]
        # A partial domain is unnecessary: ERROR makes a full recovery eligible.
        session.phase = Phase.ERROR
        handle = runner.acquire_download(batch_id, token) if gate == "download" else None
        with (
            patch("docuforge.api.batches.inputs_are_valid") as scan,
            pytest.raises(ApiError) as error,
        ):
            runner.recover(batch_id, "wrong" if gate == "auth" else token)
        assert error.value.code == (
            "batch_not_found" if gate == "auth" else "batch_download_active"
        )
        scan.assert_not_called()
        if handle:
            handle.release()
    finally:
        runner.shutdown()


@pytest.mark.parametrize(
    "kind",
    [
        "algorithm",
        "version",
        "json",
        "count",
        "duplicate",
        "order",
        "missing",
        "extra",
        "negative",
        "boolean",
        "float",
        "digest",
        "uppercase",
        "identity",
    ],
)
def test_malformed_manifest_metadata_remains_startup_fatal(tmp_path, kind):
    runner = service(storage_directory=tmp_path)
    _workspace, request, _grant = accept_queued(runner)
    row = runner._repository.get(str(request.batch_id))
    payload = json.loads(row.input_manifest_json)
    if kind == "algorithm":
        payload["algorithm"] = "md5"
    elif kind == "version":
        payload["version"] = True
    elif kind == "count":
        payload["items"].pop()
    elif kind == "duplicate":
        payload["items"][1] = payload["items"][0]
    elif kind == "order":
        payload["items"].reverse()
    elif kind == "missing":
        del payload["items"][0]["sha256"]
    elif kind == "extra":
        payload["items"][0]["extra"] = 1
    elif kind in {"negative", "boolean", "float"}:
        payload["items"][0]["size_bytes"] = {"negative": -1, "boolean": True, "float": 1.0}[kind]
    elif kind == "digest":
        payload["items"][0]["sha256"] = "0" * 63
    elif kind == "uppercase":
        payload["items"][0]["sha256"] = "A" * 64
    elif kind == "identity":
        payload["items"][0]["item_id"] = "invalid"
    runner.shutdown()
    with sqlite3.connect(tmp_path / DATABASE_NAME) as connection:
        connection.execute(
            "UPDATE batch_sessions SET input_manifest_json=?",
            ("{" if kind == "json" else json.dumps(payload),),
        )
    with pytest.raises(BatchPersistenceError):
        service(storage_directory=tmp_path)


def test_legacy_manifest_absence_uses_structural_validation_without_rebasing(tmp_path):
    runner = service(storage_directory=tmp_path, max_published_output_bytes=1)
    workspace, request, grant = accept_queued(runner)
    batch_id, token = str(request.batch_id), grant.access_token
    execute(runner, batch_id)
    row = runner._repository.get(batch_id)
    runner._repository.save(replace(row, input_manifest_json=None))
    runner.shutdown()
    restored = service(storage_directory=tmp_path)
    try:
        assert restored._sessions[batch_id].input_manifest is None
        original = request.items[0].input_path.read_bytes()
        request.items[0].input_path.unlink()
        with pytest.raises(ApiError):
            restored.recover(batch_id, token)
        request.items[0].input_path.write_bytes(original)
        with patch(
            "docuforge.api.batch_inputs._stream_digest",
            side_effect=AssertionError("legacy must not enroll hashes"),
        ):
            restored.recover(batch_id, token)
            wait_for(restored, batch_id, token, Phase.READY)
        assert restored._repository.get(batch_id).input_manifest_json is None
        assert workspace.archive_path.is_file()
    finally:
        restored.shutdown()


@pytest.mark.parametrize("kind", ["outside", "traversal", "parent_symlink"])
def test_capture_rejects_unsafe_input_relationships(tmp_path, kind):
    from docuforge.api.batch_inputs import capture_input_manifest

    runner = service()
    workspace, request = create_request(runner)
    try:
        external = tmp_path / "external"
        external.mkdir()
        source = external / "one.png"
        source.write_bytes(b"sentinel")
        if kind == "outside":
            item = replace(request.items[0], input_path=source)
        elif kind == "traversal":
            item = replace(request.items[0], input_path=workspace.inputs_directory / ".." / "one.png")
        else:
            link = workspace.inputs_directory / "external"
            try:
                link.symlink_to(external, target_is_directory=True)
            except OSError:
                pytest.skip("symlink creation unavailable")
            item = replace(request.items[0], input_path=link / "one.png")
        changed = replace(request, items=(item, *request.items[1:]))
        with pytest.raises(BatchInputIntegrityError):
            capture_input_manifest(changed, workspace.inputs_directory)
        assert source.read_bytes() == b"sentinel"
    finally:
        runner.abandon_workspace(workspace)
        runner.shutdown()


def test_input_change_during_hash_read_is_rejected():
    from docuforge.api import batch_inputs

    runner = service()
    workspace, request = create_request(runner)
    original_hash = batch_inputs._stream_digest

    def mutate_during_read(stream):
        value = original_hash(stream)
        with request.items[0].input_path.open("ab") as source:
            source.write(b"changed")
        return value

    try:
        with (
            patch.object(batch_inputs, "_stream_digest", side_effect=mutate_during_read),
            pytest.raises(BatchInputIntegrityError),
        ):
            batch_inputs.capture_input_manifest(request, workspace.inputs_directory)
    finally:
        runner.abandon_workspace(workspace)
        runner.shutdown()

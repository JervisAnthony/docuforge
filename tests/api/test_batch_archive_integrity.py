"""Live acquisition shares restart archive trust and preserves recoverable outputs."""

import os
import struct
from dataclasses import replace
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, LargeZipFile, ZipFile

import pytest

from docuforge.api.batch_persistence import BatchPersistenceError, archive_is_valid
from docuforge.api.batches import BatchExecutionPhase, BatchSessionError
from docuforge.api.errors import ApiError
from tests.api.test_batch_deletion import _ready
from tests.api.test_batch_service import wait_for


def mutate(workspace, session, kind, tmp_path):
    path = workspace.archive_path
    names = [o.output_path.name for o in session.result.outputs]
    if kind == "missing":
        path.unlink()
    elif kind == "malformed":
        path.write_bytes(b"not a zip")
    elif kind == "directory":
        path.unlink()
        path.mkdir()
    elif kind == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO creation unavailable")
        path.unlink()
        os.mkfifo(path)
    elif kind in {"outside", "symlink"}:
        other = tmp_path / "other.zip"
        other.write_bytes(path.read_bytes())
        if kind == "outside":
            session.archive_path = other
        else:
            path.unlink()
            try:
                path.symlink_to(other)
            except OSError:
                pytest.skip("symlink creation unavailable")
    elif kind in {"crc", "encrypted"}:
        data = bytearray(path.read_bytes())
        central = data.index(b"PK\x01\x02")
        if kind == "crc":
            struct.pack_into("<I", data, central + 16, 0)
            struct.pack_into("<I", data, 14, 0)
        else:
            for offset in (6, central + 8):
                struct.pack_into("<H", data, offset, struct.unpack_from("<H", data, offset)[0] | 1)
        path.write_bytes(data)
    else:
        entries = names
        if kind == "wrong":
            entries = ["unexpected.txt"]
        elif kind == "extra":
            entries = names + ["extra.txt"]
        elif kind == "duplicate":
            entries = names + names
        with ZipFile(
            path, "w", compression=ZIP_STORED if kind == "stored" else ZIP_DEFLATED
        ) as archive:
            for name in entries:
                archive.writestr(name, b"replacement")


@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("method", ["acquire_download", "download_path"])
@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "malformed",
        "directory",
        "fifo",
        "outside",
        "symlink",
        "crc",
        "encrypted",
        "wrong",
        "extra",
        "duplicate",
        "stored",
    ],
)
def test_invalid_archive_fails_closed(tmp_path, durable, method, kind):
    runner, workspace, batch_id, token = _ready(tmp_path / "storage" if durable else None)
    try:
        session = runner._sessions[batch_id]
        result, batch, updated_at, attempt = (
            session.result,
            session.batch,
            session.updated_at,
            session.attempt,
        )
        mutate(workspace, session, kind, tmp_path)
        with pytest.raises(ApiError) as caught:
            getattr(runner, method)(batch_id, token)
        assert (caught.value.status_code, caught.value.code, caught.value.message) == (
            409,
            "batch_packaging_failed",
            "The batch archive is unavailable.",
        )
        assert not runner._active_downloads
        assert session.phase is BatchExecutionPhase.ERROR
        assert session.session_error == BatchSessionError(
            "batch_packaging_failed", "The batch outputs could not be packaged."
        )
        assert session.archive_path is None
        assert session.result is result and session.batch is batch
        assert session.updated_at == updated_at and session.attempt == attempt
        assert all(o.output_path.is_file() for o in result.outputs)
        if durable:
            row = runner._repository.get(batch_id)
            assert row.phase == "error" and not row.archive_available
            assert row.updated_at == updated_at
    finally:
        runner.shutdown()


@pytest.mark.parametrize(
    "exception",
    [OSError, ValueError, BadZipFile, LargeZipFile, RuntimeError, EOFError, NotImplementedError],
)
def test_zip_exceptions_are_normalized(exception):
    runner, workspace, batch_id, _ = _ready()
    try:
        with patch("docuforge.api.batch_persistence.ZipFile", side_effect=exception):
            assert not archive_is_valid(
                workspace.archive_path, runner._sessions[batch_id].result, workspace
            )
    finally:
        runner.shutdown()


@pytest.mark.parametrize("token", [None, "", "malformed token", "wrong-token"])
def test_authorization_precedes_scan_and_mutation(tmp_path, token):
    runner, workspace, batch_id, _ = _ready(tmp_path)
    try:
        before = replace(runner._sessions[batch_id])
        workspace.archive_path.write_bytes(b"not a zip")
        with (
            patch("docuforge.api.batches.archive_is_valid") as scan,
            patch.object(runner._repository, "save") as save,
        ):
            with pytest.raises(ApiError) as caught:
                runner.acquire_download(batch_id, token)
            assert caught.value.code == "batch_not_found"
            scan.assert_not_called()
            save.assert_not_called()
        assert runner._sessions[batch_id] == before
        assert not runner._active_downloads
    finally:
        runner.shutdown()


def test_durable_failure_is_atomic(tmp_path):
    runner, workspace, batch_id, token = _ready(tmp_path)
    try:
        before = replace(runner._sessions[batch_id])
        workspace.archive_path.write_bytes(b"not a zip")

        def fail(candidate):
            assert runner._sessions[batch_id] == before
            assert candidate.phase == "error" and not candidate.archive_available
            raise BatchPersistenceError("fail")

        with (
            patch.object(runner._repository, "save", side_effect=fail),
            pytest.raises(ApiError) as caught,
        ):
            runner.acquire_download(batch_id, token)
        assert (caught.value.status_code, caught.value.code) == (503, "batch_persistence_failed")
        assert runner._sessions[batch_id] == before
        assert not runner._active_downloads
    finally:
        runner.shutdown()


@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_repair_does_not_repeat_converter(tmp_path, durable, missing):
    runner, workspace, batch_id, token = _ready(tmp_path if durable else None)
    try:
        first = runner.acquire_download(batch_id, token)
        updated_at = runner._sessions[batch_id].updated_at
        if missing:
            workspace.archive_path.unlink()
        else:
            workspace.archive_path.write_bytes(b"not a zip")
        with pytest.raises(ApiError):
            runner.acquire_download(batch_id, token)
        assert len(runner._active_downloads[batch_id]) == 1
        first.release()
        assert runner._sessions[batch_id].updated_at == updated_at
        from docuforge.api import batches

        with (
            patch.object(
                batches, "batch_convert_images", side_effect=AssertionError("converter repeated")
            ) as converter,
            patch.object(
                batches, "package_batch_outputs", wraps=batches.package_batch_outputs
            ) as package,
        ):
            runner.recover(batch_id, token)
            wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
            converter.assert_not_called()
            package.assert_called_once()
        handle = runner.acquire_download(batch_id, token)
        assert archive_is_valid(handle.path, runner._sessions[batch_id].result, workspace)
        handle.release()
    finally:
        runner.shutdown()


@pytest.mark.parametrize("valid", [False, True])
def test_error_archive_preserves_original_error(tmp_path, valid):
    runner, workspace, batch_id, token = _ready(tmp_path)
    try:
        session = runner._sessions[batch_id]
        session.phase = BatchExecutionPhase.ERROR
        session.session_error = BatchSessionError("original", "original")
        before = session.updated_at
        if valid:
            runner.acquire_download(batch_id, token).release()
        else:
            workspace.archive_path.write_bytes(b"bad")
            with pytest.raises(ApiError):
                runner.acquire_download(batch_id, token)
            assert session.archive_path is None
            assert not runner._repository.get(batch_id).archive_available
        assert session.session_error.code == "original"
        assert session.updated_at == before
    finally:
        runner.shutdown()


def test_partial_repair_then_selective_recovery():
    from docuforge.api import batches
    from docuforge.batch import BatchStatus
    from tests.api.test_batch_service import create_request, service
    from tests.batch.test_image_processing import write_image

    runner = service()
    workspace, request = create_request(runner)
    missing = request.items[0].input_path
    missing.unlink()
    grant = runner.create_session(request, workspace)
    batch_id, token = str(request.batch_id), grant.access_token
    try:
        partial = wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
        assert partial.batch.status is BatchStatus.PARTIAL
        preserved = request.output_directory / "0002-two.jpg"
        before = preserved.read_bytes()
        workspace.archive_path.write_bytes(b"bad")
        with pytest.raises(ApiError):
            runner.acquire_download(batch_id, token)
        write_image(missing)
        with patch.object(
            batches, "batch_convert_images", side_effect=AssertionError("reconverted")
        ):
            runner.recover(batch_id, token)
            repaired = wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
        assert repaired.batch.status is BatchStatus.PARTIAL and repaired.can_recover
        with ZipFile(runner.download_path(batch_id, token)) as archive:
            assert archive.namelist() == ["0002-two.jpg"]
        runner.recover(batch_id, token)
        final = wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
        assert final.batch.status is BatchStatus.COMPLETED
        assert preserved.read_bytes() == before
    finally:
        runner.shutdown()


@pytest.mark.parametrize("phase", list(BatchExecutionPhase))
def test_ineligible_phases_do_not_scan(phase):
    if phase in {BatchExecutionPhase.READY, BatchExecutionPhase.ERROR}:
        return
    runner, _, batch_id, token = _ready()
    try:
        runner._sessions[batch_id].phase = phase
        with (
            patch("docuforge.api.batches.archive_is_valid") as scan,
            pytest.raises(ApiError) as caught,
        ):
            runner.acquire_download(batch_id, token)
        assert caught.value.code == (
            "batch_not_found" if phase is BatchExecutionPhase.DELETING else "batch_not_ready"
        )
        scan.assert_not_called()
        assert not runner._active_downloads
    finally:
        runner.shutdown()


def test_validation_precedes_pin_and_no_output_skips_scan():
    from docuforge.api import batches

    runner, _, batch_id, token = _ready()
    try:
        validator = batches.archive_is_valid

        def validate(*args):
            assert not runner._active_downloads
            return validator(*args)

        with patch.object(batches, "archive_is_valid", side_effect=validate) as scan:
            runner.acquire_download(batch_id, token).release()
            scan.assert_called_once()
        runner.shutdown()
        from tests.api.test_batch_service import create_request, service

        runner = service(max_published_output_bytes=1)
        workspace, request = create_request(runner, ("one.png",))
        grant = runner.create_session(request, workspace)
        batch_id, token = str(request.batch_id), grant.access_token
        wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
        session = runner._sessions[batch_id]
        with patch.object(batches, "archive_is_valid") as scan, pytest.raises(ApiError) as caught:
            runner.acquire_download(batch_id, token)
        assert caught.value.code == "batch_has_no_outputs"
        scan.assert_not_called()
        assert session.phase is BatchExecutionPhase.READY
    finally:
        runner.shutdown()


@pytest.mark.parametrize("kind", ["order", "directory_member"])
def test_order_and_directory_member_rejected(kind):
    from tests.api.test_batch_service import create_request, service

    runner = service()
    workspace, request = create_request(runner)
    grant = runner.create_session(request, workspace)
    batch_id, token = str(request.batch_id), grant.access_token
    try:
        wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
        names = [output.output_path.name for output in runner._sessions[batch_id].result.outputs]
        with ZipFile(workspace.archive_path, "w", compression=ZIP_DEFLATED) as archive:
            for name in reversed(names) if kind == "order" else names + ["directory/"]:
                archive.writestr(name, b"data")
        with pytest.raises(ApiError):
            runner.acquire_download(batch_id, token)
        assert not runner._active_downloads
    finally:
        runner.shutdown()


def test_status_remains_cheap_and_cross_session_is_private():
    from tests.api.test_batch_service import create_request

    runner, _, batch_id, token = _ready()
    try:
        workspace, request = create_request(runner, ("other.png",))
        other = runner.create_session(request, workspace)
        wait_for(runner, str(request.batch_id), other.access_token, BatchExecutionPhase.READY)
        with patch("docuforge.api.batches.archive_is_valid") as scan:
            assert runner.get(batch_id, token).can_download
            with pytest.raises(ApiError) as caught:
                runner.acquire_download(batch_id, other.access_token)
        assert caught.value.code == "batch_not_found"
        scan.assert_not_called()
        assert not runner._active_downloads
    finally:
        runner.shutdown()

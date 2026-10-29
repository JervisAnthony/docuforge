"""Same-descriptor ZIP trust and actual bounded ASGI download regressions."""

import asyncio
import io
import os
import shutil
import stat
from dataclasses import replace
from email import policy
from email.parser import BytesParser
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from anyio import open_file  # Resolve lazy file-I/O imports before forbidden-open instrumentation.

from docuforge.api import batch_persistence as persistence
from docuforge.api import batches
from docuforge.api.batch_persistence import BatchPersistenceError
from docuforge.api.batches import BatchDownloadHandle, BatchExecutionPhase
from docuforge.api.errors import ApiError
from docuforge.api.routes.batches import _PinnedFileResponse
from tests.api.test_batch_deletion import _ready
from tests.api.test_batch_service import wait_for


@pytest.fixture(params=[False, True], ids=["ephemeral", "durable"])
def ready(request, tmp_path):
    runner, workspace, batch_id, token = _ready(tmp_path / "storage" if request.param else None)
    handles = []

    def acquire():
        handle = runner.acquire_download(batch_id, token)
        handles.append(handle)
        return handle

    yield SimpleNamespace(runner=runner, workspace=workspace, batch_id=batch_id, token=token,
                          acquire=acquire, handles=handles, durable=request.param)
    for handle in handles:
        handle.release()
    runner.shutdown()


def scope(headers=(), method="GET", version="2.4"):
    return {"type": "http", "method": method, "headers": list(headers),
            "asgi": {"spec_version": version}, "extensions": {"http.response.pathsend": {}}}


def response(handle, batch_id="synthetic"):
    return _PinnedFileResponse(handle, media_type="application/zip",
                               filename=f"docuforge-batch-{batch_id}.zip",
                               headers={"Cache-Control": "no-store"})


async def disconnected():
    return {"type": "http.disconnect"}


def transmit(handle, *, headers=(), method="GET", batch_id="synthetic"):
    messages = []

    async def send(message):
        assert not handle.reader.closed
        assert message["type"] != "http.response.pathsend"
        messages.append(message)

    asyncio.run(response(handle, batch_id)(scope(headers, method), disconnected, send))
    assert handle.reader.closed
    start = messages[0]
    return start["status"], dict(start["headers"]), b"".join(m.get("body", b"") for m in messages)


@pytest.mark.parametrize("case", [
    "full", "single", "open", "suffix", "large-suffix", "multi", "overlap",
    "unsatisfiable", "malformed", "head", "head-range", "head-multi",
    "if-range-etag", "if-range-date", "if-range-mismatch", "too-many-ranges",
])
def test_asgi_http_matrix(ready, case):
    handle = ready.acquire()
    original = handle.reader.read()
    size = len(original)
    headers, method, expected, status = [], "GET", original, 200
    if case == "single":
        headers, expected, status = [(b"range", b"bytes=0-9")], original[:10], 206
    elif case == "open":
        headers, expected, status = [(b"range", b"bytes=10-")], original[10:], 206
    elif case == "suffix":
        headers, expected, status = [(b"range", b"bytes=-10")], original[-10:], 206
    elif case == "large-suffix":
        headers, status = [(b"range", b"bytes=-999999")], 206
    elif case in {"multi", "head-multi"}:
        headers, status = [(b"range", b"bytes=0-2,10-14")], 206
    elif case == "overlap":
        headers, expected, status = [(b"range", b"bytes=0-5,3-9")], original[:10], 206
    elif case == "unsatisfiable":
        headers, expected, status = [(b"range", b"bytes=999999-")], b"", 416
    elif case == "malformed":
        headers, status = [(b"range", b"not-a-range")], 400
    elif case == "head-range":
        headers, status = [(b"range", b"bytes=0-9")], 206
    elif case.startswith("if-range"):
        prepared = response(handle)
        validator = (prepared.headers["etag"] if case == "if-range-etag" else
                     prepared.headers["last-modified"] if case == "if-range-date" else "mismatch")
        headers = [(b"range", b"bytes=0-9"), (b"if-range", validator.encode())]
        if case != "if-range-mismatch":
            status, expected = 206, original[:10]
    elif case == "too-many-ranges":
        headers = [(b"range", b"bytes=" + b",".join([b"0-0"] * 101))]
    if case.startswith("head"):
        method, expected = "HEAD", b""
    actual, returned, body = transmit(handle, headers=headers, method=method, batch_id=ready.batch_id)
    assert actual == status
    if status in {200, 206}:
        assert returned[b"cache-control"] == b"no-store"
        assert returned[b"accept-ranges"] == b"bytes"
        assert returned[b"content-disposition"] == (
            f'attachment; filename="docuforge-batch-{ready.batch_id}.zip"'.encode()
        )
        if method != "HEAD":
            assert int(returned[b"content-length"]) == len(body)
    if case == "multi":
        parsed = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + returned[b"content-type"] + b"\r\n\r\n" + body,
        )
        parts = list(parsed.iter_parts())
        assert [p["Content-Range"] for p in parts] == [f"bytes 0-2/{size}", f"bytes 10-14/{size}"]
        assert [p.get_payload(decode=True) for p in parts] == [original[:3], original[10:15]]
    elif case == "malformed":
        assert body == b"Malformed range header."
    else:
        assert body == expected
    if case in {"single", "head-range", "overlap", "if-range-etag", "if-range-date"}:
        assert returned[b"content-range"] == f"bytes 0-9/{size}".encode()
        assert returned[b"content-length"] == b"10"
    if status == 416:
        assert returned[b"content-range"] == f"bytes */{size}".encode()
    assert not ready.runner._active_downloads


def zip_bytes(name, content):
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return stream.getvalue()


def test_crc_and_response_consume_the_identical_descriptor_once(ready, monkeypatch):
    validator = persistence._archive_reader_is_valid
    validated, streamed = [], []

    def validate(reader, result):
        assert not ready.runner._active_downloads
        assert validator(reader, result)  # Real structure and CRC scan, no truth-only mock.
        validated.append((reader, reader.fileno()))
        return True

    monkeypatch.setattr(persistence, "_archive_reader_is_valid", validate)
    handle = ready.acquire()
    assert validated == [(handle.reader, handle.reader.fileno())]
    assert handle.reader.tell() == 0
    read = BatchDownloadHandle.read_chunk

    def reading(self, offset, size):
        assert 0 < size <= 1024 * 1024
        assert self.reader is validated[0][0]
        streamed.append(self.reader.fileno())
        return read(self, offset, size)

    monkeypatch.setattr(BatchDownloadHandle, "read_chunk", reading)
    # Prove no FileResponse stat/open or pathsend path can be used after acquisition.
    def forbidden(*args, **kwargs):
        pytest.fail("response reopened or inspected an untrusted pathname")

    assert callable(open_file)
    with (patch("anyio.open_file", forbidden), patch("builtins.open", forbidden),
          patch.object(os, "open", forbidden), patch.object(os, "stat", forbidden),
          patch.object(Path, "open", forbidden)):
        status, _, body = transmit(handle)
    assert status == 200 and streamed == [validated[0][1]]
    with ZipFile(io.BytesIO(body)) as archive:
        assert archive.testzip() is None
    assert len(validated) == 1
    assert handle.reader.closed and not ready.runner._active_downloads


@pytest.mark.parametrize("kind", ["regular", "symlink"])
def test_replacement_after_acquisition_streams_original(ready, tmp_path, kind):
    handle = ready.acquire()
    original = handle.reader.read()
    replacement = tmp_path / "external.zip"
    name = ready.runner._sessions[ready.batch_id].result.outputs[0].output_path.name
    replacement.write_bytes(zip_bytes(name, b"EXTERNAL SYNTHETIC SENTINEL"))
    try:
        handle.path.rename(handle.path.with_suffix(".original"))
    except PermissionError:
        # An injected informational path swap exercises the same no-reopen seam
        # on platforms that prohibit renaming an archive with an open reader.
        handle.path = replacement
    else:
        if kind == "regular":
            handle.path.write_bytes(replacement.read_bytes())
        else:
            try:
                handle.path.symlink_to(replacement)
            except OSError:
                pytest.skip("symlink creation unavailable")
    _, _, body = transmit(handle)
    assert body == original
    assert body != replacement.read_bytes()


@pytest.mark.parametrize("boundary", ["before-open", "during-validation", "in-place"])
def test_observable_replacement_before_acceptance_rejects(ready, monkeypatch, boundary):
    path = ready.workspace.archive_path
    result = ready.runner._sessions[ready.batch_id].result
    name = result.outputs[0].output_path.name
    original, replacement = zip_bytes(name, b"AAAAAAA"), zip_bytes(name, b"BBBBBBB")
    assert len(original) == len(replacement)
    path.write_bytes(original)
    validator, opening = persistence._archive_reader_is_valid, os.open
    readers = []
    fdopen = os.fdopen

    def tracking(*args, **kwargs):
        reader = fdopen(*args, **kwargs)
        readers.append(reader)
        return reader

    def swap():
        if boundary == "in-place":
            path.write_bytes(replacement)
            node = path.stat()
            os.utime(path, ns=(node.st_atime_ns, node.st_mtime_ns + 2_000_000_000))
        else:
            try:
                path.rename(path.with_suffix(".original"))
            except PermissionError:
                # Windows can prohibit replacing open entries. Observable metadata
                # mutation still exercises rejection while descriptor validation runs.
                path.write_bytes(replacement)
                node = path.stat()
                os.utime(path, ns=(node.st_atime_ns, node.st_mtime_ns + 2_000_000_000))
            else:
                path.write_bytes(replacement)

    if boundary == "before-open":
        def open_replaced(value, flags, *args, **kwargs):
            if Path(value).name == "result.zip":
                swap()
            return opening(value, flags, *args, **kwargs)
        monkeypatch.setattr(persistence.os, "open", open_replaced)
    else:
        def changed(reader, value):
            valid = validator(reader, value)
            swap()
            return valid
        monkeypatch.setattr(persistence, "_archive_reader_is_valid", changed)
    monkeypatch.setattr(persistence.os, "fdopen", tracking)
    before = replace(ready.runner._sessions[ready.batch_id])
    with pytest.raises(ApiError) as caught:
        ready.acquire()
    assert (caught.value.status_code, caught.value.code, caught.value.message) == (
        409, "batch_packaging_failed", "The batch archive is unavailable.",
    )
    assert readers and all(reader.closed for reader in readers)
    assert not ready.runner._active_downloads
    session = ready.runner._sessions[ready.batch_id]
    assert session.phase is BatchExecutionPhase.ERROR and session.archive_path is None
    assert session.result is before.result and session.batch is before.batch
    assert (session.attempt, session.updated_at) == (before.attempt, before.updated_at)


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink", "fifo", "crc", "external"])
def test_invalid_archive_never_leaks_a_descriptor_or_pin(ready, monkeypatch, tmp_path, kind):
    path = ready.workspace.archive_path
    readers, fdopen = [], os.fdopen

    def track(*args, **kwargs):
        reader = fdopen(*args, **kwargs)
        readers.append(reader)
        return reader

    monkeypatch.setattr(persistence.os, "fdopen", track)
    if kind in {"missing", "directory", "symlink", "fifo"}:
        path.unlink()
        if kind == "directory":
            path.mkdir()
        elif kind == "fifo":
            if not hasattr(os, "mkfifo"):
                pytest.skip("FIFO unavailable")
            os.mkfifo(path)
        elif kind == "symlink":
            target = tmp_path / "sentinel"
            target.write_bytes(b"EXTERNAL SENTINEL")
            try:
                path.symlink_to(target)
            except OSError:
                pytest.skip("symlink creation unavailable")
    elif kind == "external":
        external = tmp_path / "external.zip"
        external.write_bytes(path.read_bytes())
        ready.runner._sessions[ready.batch_id].archive_path = external
    else:
        data = bytearray(path.read_bytes())
        central = data.index(b"PK\x01\x02")
        data[central + 16:central + 20] = b"\x00" * 4
        path.write_bytes(data)
    with pytest.raises(ApiError) as caught:
        ready.acquire()
    assert caught.value.code == "batch_packaging_failed"
    assert not ready.runner._active_downloads
    assert all(reader.closed for reader in readers)
    if kind in {"missing", "directory", "symlink", "fifo", "external"}:
        assert not readers


@pytest.mark.parametrize("ready", [True], indirect=True, ids=["durable"])
def test_persistence_failure_closes_reader_without_live_mutation(ready, monkeypatch):
    session = ready.runner._sessions[ready.batch_id]
    before = replace(session)
    readers, fdopen = [], os.fdopen

    def tracking(*args, **kwargs):
        reader = fdopen(*args, **kwargs)
        readers.append(reader)
        return reader

    monkeypatch.setattr(persistence.os, "fdopen", tracking)
    ready.workspace.archive_path.write_bytes(b"invalid ZIP")
    with (patch.object(ready.runner._repository, "save", side_effect=BatchPersistenceError("private")),
          pytest.raises(ApiError) as caught):
        ready.acquire()
    assert caught.value.code == "batch_persistence_failed" and caught.value.status_code == 503
    assert session == before
    assert readers and all(reader.closed for reader in readers)
    assert not ready.runner._active_downloads


@pytest.mark.parametrize("failure", ["send", "cancel", "read-before-headers", "short-read"])
def test_asgi_failure_cleanup(ready, monkeypatch, failure):
    handle = ready.acquire()
    messages = []
    if failure in {"read-before-headers", "short-read"}:
        if failure == "short-read":
            with handle.path.open("r+b") as writer:
                writer.truncate(0)
            handle.reader.seek(0, os.SEEK_END)  # Discard any small-file read-ahead buffer.
        else:
            reader = handle.reader

            class FailingReader:
                def seek(self, *args):
                    raise OSError("private path and capability diagnostics")

                def close(self):
                    reader.close()

                @property
                def closed(self):
                    return reader.closed

            handle.reader = FailingReader()

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body":
            if failure == "cancel":
                raise asyncio.CancelledError()
            raise OSError("transport disconnected")

    exception = asyncio.CancelledError if failure == "cancel" else OSError
    with pytest.raises(exception) as caught:
        asyncio.run(response(handle)(scope(), disconnected, send))
    assert handle.reader.closed and not ready.runner._active_downloads
    if failure in {"read-before-headers", "short-read"}:
        assert messages == []
        assert str(caught.value) == "Unable to read the batch archive."


def test_receive_disconnect_stops_pre_24_stream_and_releases(ready):
    handle = ready.acquire()

    async def run():
        started = asyncio.Event()

        async def send(message):
            if message["type"] == "http.response.body":
                started.set()
                await asyncio.Event().wait()

        async def receive():
            await started.wait()
            return {"type": "http.disconnect"}

        await asyncio.wait_for(response(handle)(scope(version="2.3"), receive, send), timeout=5)

    asyncio.run(run())
    assert handle.reader.closed and not ready.runner._active_downloads


def test_independent_cursors_delete_waits_for_both(ready):
    first, second = ready.acquire(), ready.acquire()
    assert first.reader.fileno() != second.reader.fileno()
    expected = first.read_chunk(0, first.size_bytes)
    first.reader.seek(17)
    assert second.reader.tell() == 0
    assert second.read_chunk(3, 11) == expected[3:14]
    assert first.reader.tell() == 17
    ready.runner.delete_session(ready.batch_id, ready.token)
    first.release()
    assert not second.reader.closed and ready.workspace.path.exists()
    _, _, body = transmit(second)
    assert body == expected
    assert not ready.workspace.path.exists() and not ready.runner._active_downloads


@pytest.mark.parametrize("action", ["delete", "ttl"])
def test_lifecycle_during_actual_body_stream(ready, action):
    handle = ready.acquire()
    original = handle.reader.read()
    session = ready.runner._sessions[ready.batch_id]
    updated = session.updated_at
    messages = []

    async def send(message):
        if message["type"] == "http.response.body":
            if action == "delete":
                ready.runner.delete_session(ready.batch_id, ready.token)
            else:
                assert session.updated_at == updated  # Download did not refresh terminal retention.
                ready.runner._clock = lambda: updated + ready.runner._terminal_ttl_seconds
                with ready.runner._lock:
                    ready.runner._sweep_locked()
            assert ready.workspace.path.exists() and not handle.reader.closed
            with pytest.raises(ApiError) as caught:
                ready.runner.get(ready.batch_id, ready.token)
            assert caught.value.code == "batch_not_found"
        messages.append(message)

    asyncio.run(response(handle)(scope(), disconnected, send))
    assert b"".join(m.get("body", b"") for m in messages) == original
    assert handle.reader.closed and not ready.workspace.path.exists()


def test_close_failure_still_unpins_once(ready, monkeypatch, caplog):
    handle = ready.acquire()
    reader = handle.reader
    calls = []

    class FailingClose:
        def close(self):
            reader.close()
            calls.append("closed")
            raise OSError("private cleanup diagnostic")

    handle.reader = FailingClose()
    release = handle._release

    def unpin():
        assert reader.closed
        calls.append("unpinned")
        release()

    handle._release = unpin
    handle.release()
    handle.release()
    assert calls == ["closed", "unpinned"]
    assert not ready.runner._active_downloads
    assert caplog.messages == ["Batch download reader cleanup failed."]


@pytest.mark.parametrize("token", [None, "", "wrong-token", "malformed token"])
def test_private_authorization_precedes_open_or_scan(ready, monkeypatch, token):
    ready.workspace.archive_path.unlink()
    before = replace(ready.runner._sessions[ready.batch_id])
    row = ready.runner._repository.get(ready.batch_id) if ready.durable else None
    ready.runner._clock = lambda: before.updated_at + ready.runner._terminal_ttl_seconds
    with (patch.object(batches, "_open_validated_download_archive") as opening,
          patch.object(persistence, "_archive_reader_is_valid") as crc,
          patch.object(ready.runner, "_expire_locked", wraps=ready.runner._expire_locked) as expiry,
          pytest.raises(ApiError) as caught):
        ready.runner.acquire_download(ready.batch_id, token)
    assert caught.value.code == "batch_not_found" and caught.value.status_code == 404
    opening.assert_not_called()
    crc.assert_not_called()
    expiry.assert_not_called()
    assert ready.runner._sessions[ready.batch_id] == before
    assert ready.workspace.path.exists()
    if ready.durable:
        assert ready.runner._repository.get(ready.batch_id) == row
    assert not ready.runner._active_downloads


def test_packaging_only_recovery_does_not_repeat_conversion(ready):
    ready.workspace.archive_path.write_bytes(b"invalid")
    with pytest.raises(ApiError):
        ready.acquire()
    session = ready.runner._sessions[ready.batch_id]
    result = session.result
    for item in session.request.items:
        item.input_path.unlink()
    with patch.object(batches, "batch_convert_images", side_effect=AssertionError("converter rerun")):
        ready.runner.recover(ready.batch_id, ready.token)
        wait_for(ready.runner, ready.batch_id, ready.token, BatchExecutionPhase.READY)
    assert session.result is result
    transmit(ready.acquire())


def test_symlink_swap_between_inspection_and_open_reads_no_external_bytes(ready, tmp_path, monkeypatch):
    path = ready.workspace.archive_path
    target = tmp_path / "sentinel.zip"
    target.write_bytes(b"EXTERNAL SYNTHETIC SENTINEL")
    opening = os.open

    def swapped(name, flags, *args, **kwargs):
        if Path(name).name == "result.zip":
            path.rename(path.with_suffix(".original"))
            try:
                path.symlink_to(target)
            except OSError:
                pytest.skip("symlink creation unavailable")
        return opening(name, flags, *args, **kwargs)

    with (patch.object(persistence.os, "open", side_effect=swapped),
          patch.object(persistence, "_archive_reader_is_valid") as scan,
          pytest.raises(ApiError) as caught):
        ready.acquire()
    scan.assert_not_called()
    assert caught.value.code == "batch_packaging_failed"
    assert target.read_bytes() == b"EXTERNAL SYNTHETIC SENTINEL"
    assert not ready.runner._active_downloads


@pytest.mark.parametrize("kind", ["directory", "fifo", "socket", "device"])
def test_open_descriptor_must_be_regular_and_closes_on_rejection(ready, monkeypatch, kind):
    fstat, fdopen = os.fstat, os.fdopen
    readers = []
    modes = {"directory": stat.S_IFDIR, "fifo": stat.S_IFIFO,
             "socket": stat.S_IFSOCK, "device": stat.S_IFCHR}

    def wrong_type(fd):
        node = fstat(fd)
        # os is shared with pytest capture and the module loader. Only inject
        # metadata for the archive reader opened by this acquisition.
        if any(not reader.closed and reader.fileno() == fd for reader in readers):
            return os.stat_result(
                (modes[kind] | stat.S_IMODE(node.st_mode), *node[1:]),
                {name: getattr(node, name) for name in dir(node)
                 if name.startswith("st_") and name not in (
                     "st_mode", "st_ino", "st_dev", "st_nlink", "st_uid", "st_gid", "st_size",
                 )},
            )
        return node

    def tracking(*args, **kwargs):
        reader = fdopen(*args, **kwargs)
        readers.append(reader)
        return reader

    monkeypatch.setattr(persistence.os, "fstat", wrong_type)
    monkeypatch.setattr(persistence.os, "fdopen", tracking)
    with (patch.object(persistence, "_archive_reader_is_valid") as scan,
          pytest.raises(ApiError) as caught):
        ready.acquire()
    scan.assert_not_called()
    assert (caught.value.status_code, caught.value.code, caught.value.message) == (
        409, "batch_packaging_failed", "The batch archive is unavailable.",
    )
    assert not ready.handles
    assert readers and all(reader.closed for reader in readers)
    assert not ready.runner._active_downloads


def test_handle_constructor_failure_closes_validated_reader(ready, monkeypatch):
    validated = []
    opening = batches._open_validated_download_archive

    def track(*args):
        reader, node = opening(*args)
        validated.append(reader)
        return reader, node

    monkeypatch.setattr(batches, "_open_validated_download_archive", track)
    with (patch.object(batches, "BatchDownloadHandle", side_effect=RuntimeError("constructor")),
          pytest.raises(RuntimeError, match="constructor")):
        ready.acquire()
    assert validated and all(reader.closed for reader in validated)
    assert not ready.runner._active_downloads


def test_partial_pin_registration_failure_closes_reader_and_unpins(ready, monkeypatch):
    existing = ready.acquire()
    readers = []
    opening = batches._open_validated_download_archive

    def track(*args):
        reader, node = opening(*args)
        readers.append(reader)
        return reader, node

    class FailingPins(set):
        def add(self, pin):
            super().add(pin)
            raise RuntimeError("registration failed")

    original_pins = set(ready.runner._active_downloads[ready.batch_id])
    ready.runner._active_downloads[ready.batch_id] = FailingPins(original_pins)
    monkeypatch.setattr(batches, "_open_validated_download_archive", track)
    with pytest.raises(RuntimeError, match="registration failed"):
        ready.acquire()
    assert readers and all(reader.closed for reader in readers)
    assert ready.runner._active_downloads[ready.batch_id] == original_pins
    assert not existing.reader.closed
    ready.runner._active_downloads[ready.batch_id] = original_pins
    replacement = ready.acquire()
    assert len(ready.runner._active_downloads[ready.batch_id]) == 2
    replacement.release()
    existing.release()
    assert not ready.runner._active_downloads


def test_replaced_workspace_ancestry_fails_closed(ready, tmp_path, monkeypatch):
    path = ready.workspace.archive_path
    original = path.read_bytes()
    opening = os.open

    def swap_root(name, flags, *args, **kwargs):
        if Path(name).name == "result.zip":
            backup = tmp_path / "original-workspace"
            ready.workspace.path.rename(backup)
            shutil.copytree(backup, ready.workspace.path)
            path.write_bytes(original)
        return opening(name, flags, *args, **kwargs)

    with (patch.object(persistence.os, "open", side_effect=swap_root),
          pytest.raises(ApiError) as caught):
        ready.acquire()
    assert caught.value.code == "batch_packaging_failed"
    assert not ready.runner._active_downloads


def test_large_response_uses_bounded_chunks(ready):
    path = ready.workspace.archive_path
    name = ready.runner._sessions[ready.batch_id].result.outputs[0].output_path.name
    path.write_bytes(zip_bytes(name, os.urandom(2 * 1024 * 1024 + 19)))
    original = path.read_bytes()
    handle = ready.acquire()
    chunks = []

    async def send(message):
        if message["type"] == "http.response.body":
            chunks.append(message["body"])
            assert len(message["body"]) <= 1024 * 1024

    asyncio.run(response(handle)(scope(), disconnected, send))
    assert len(chunks) >= 3
    assert b"".join(chunks) == original
    assert handle.reader.closed and not ready.runner._active_downloads


def test_concurrent_asgi_readers_delete_after_final_body(ready):
    first, second = ready.acquire(), ready.acquire()
    original = first.read_chunk(0, first.size_bytes)
    bodies = [[], []]

    async def run():
        first_body, second_done = asyncio.Event(), asyncio.Event()

        async def send_first(message):
            if message["type"] == "http.response.body":
                ready.runner.delete_session(ready.batch_id, ready.token)
                first_body.set()
                await second_done.wait()
                assert second.reader.closed and not first.reader.closed
                assert len(ready.runner._active_downloads[ready.batch_id]) == 1
                assert ready.workspace.path.exists()
                bodies[0].append(message["body"])

        async def send_second(message):
            await first_body.wait()
            if message["type"] == "http.response.body":
                bodies[1].append(message["body"])

        async def second_response():
            await response(second)(scope(), disconnected, send_second)
            second_done.set()

        await asyncio.wait_for(asyncio.gather(
            response(first)(scope(), disconnected, send_first), second_response(),
        ), timeout=5)

    asyncio.run(run())
    assert [b"".join(body) for body in bodies] == [original, original]
    assert not ready.runner._active_downloads and not ready.workspace.path.exists()


def test_shutdown_waits_until_disconnected_response_closes_reader(ready):
    handle = ready.acquire()
    waiting = Event()
    original_wait = ready.runner._downloads_drained.wait_for

    def wait(predicate):
        waiting.set()
        return original_wait(predicate)

    async def send(message):
        if message["type"] == "http.response.body":
            raise OSError("disconnected")

    with patch.object(ready.runner._downloads_drained, "wait_for", side_effect=wait):
        thread = Thread(target=ready.runner.shutdown)
        thread.start()
        try:
            assert waiting.wait(5) and not handle.reader.closed
            with pytest.raises(OSError):
                asyncio.run(response(handle)(scope(), disconnected, send))
            thread.join(5)
            assert not thread.is_alive() and handle.reader.closed
        finally:
            handle.release()
            thread.join(5)
    assert not ready.runner._active_downloads


def test_reparse_points_and_fallback_opening(ready, monkeypatch):
    node = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
    with patch.object(persistence.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400, create=True):
        assert persistence._archive_node_is_link(node)
    monkeypatch.setattr(persistence, "_DOWNLOAD_DIRECTORY_OPEN", False)
    opening, seen = os.open, []

    def flags(path, value, *args, **kwargs):
        if Path(path).name == "result.zip":
            seen.append(value)
        return opening(path, value, *args, **kwargs)

    monkeypatch.setattr(persistence.os, "open", flags)
    handle = ready.acquire()
    assert len(seen) == 1
    for flag in ("O_BINARY", "O_NONBLOCK", "O_NOFOLLOW", "O_CLOEXEC"):
        value = getattr(os, flag, 0)
        assert seen[0] & value == value
    transmit(handle)

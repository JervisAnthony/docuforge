"""Process-local archive-reader admission, privacy, races and capacity recovery."""

import asyncio
import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from threading import Barrier, Event, Thread
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, batches, create_app
from docuforge.api import batch_persistence as persistence
from docuforge.api.batch_access import BATCH_TOKEN_HEADER
from docuforge.api.batch_persistence import BatchPersistenceError
from docuforge.api.batch_storage_lock import BatchStorageOwnershipError
from docuforge.api.batches import BatchExecutionPhase
from docuforge.api.errors import ApiError
from tests.api.image_test_support import make_image
from tests.api.test_batch_download_descriptor import disconnected, response, scope, transmit
from tests.api.test_batch_service import create_request, service, wait_for

CAPACITY = (
    503, "batch_download_capacity_exceeded",
    "The batch download service is temporarily at capacity. Try again later.",
)


def assert_capacity(action):
    with pytest.raises(ApiError) as caught:
        action()
    assert (caught.value.status_code, caught.value.code, caught.value.message) == CAPACITY


@pytest.fixture(params=[False, True], ids=["ephemeral", "durable"])
def pool(request, tmp_path):
    resources = []

    def make(*, global_limit=2, batch_limit=2, **kwargs):
        storage = tmp_path / str(len(resources)) if request.param else None
        runner = service(
            storage_directory=storage, max_active_downloads=global_limit,
            max_downloads_per_batch=batch_limit, **kwargs,
        )
        handles = []
        resources.append((runner, handles))

        def ready(*, invalid=False):
            workspace, value = create_request(runner, ("one.png",))
            if invalid:
                value.items[0].input_path.write_bytes(b"invalid")
            grant = runner.create_session(value, workspace)
            batch_id, token = str(value.batch_id), grant.access_token
            wait_for(runner, batch_id, token, BatchExecutionPhase.READY, BatchExecutionPhase.ERROR)
            return SimpleNamespace(id=batch_id, token=token, workspace=workspace)

        def acquire(batch):
            handle = runner.acquire_download(batch.id, batch.token)
            handles.append(handle)
            return handle

        return SimpleNamespace(runner=runner, ready=ready, acquire=acquire, handles=handles,
                               storage=storage)

    yield make
    for runner, handles in resources:
        for handle in handles:
            handle.release()
        runner.shutdown()


@pytest.mark.parametrize("parameter", ["max_active_downloads", "max_downloads_per_batch"])
@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "2", None])
def test_constructor_rejects_non_positive_exact_integers(parameter, value):
    with pytest.raises(ValueError, match=f"{parameter} must be a positive integer"):
        service(**{parameter: value})


@pytest.mark.parametrize("field", ["batch_max_active_downloads", "batch_max_downloads_per_batch"])
@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "2", None])
def test_settings_reject_non_positive_exact_integers(field, value):
    with pytest.raises(ValueError, match=f"{field} must be a positive integer"):
        ApiSettings(**{field: value})


@pytest.mark.parametrize("field", ["batch_max_active_downloads", "batch_max_downloads_per_batch"])
@pytest.mark.parametrize("value", ["", " ", "0", "-1", "1.5", "true", "2MB", "0x10", "1e3",
                                 "١٢", "１２", "+2", "1_000"])
def test_environment_rejects_non_ascii_or_non_decimal_integers(monkeypatch, field, value):
    monkeypatch.setenv("DOCUFORGE_" + field.upper(), value)
    with pytest.raises(ValueError, match="must be a positive integer"):
        ApiSettings.from_environment()


def test_defaults_and_valid_configuration(monkeypatch):
    settings = ApiSettings()
    assert (settings.batch_max_active_downloads, settings.batch_max_downloads_per_batch) == (8, 4)
    with pytest.raises(FrozenInstanceError):
        settings.batch_max_active_downloads = 2
    runner = service()
    try:
        assert (runner._max_active_downloads, runner._max_downloads_per_batch) == (8, 4)
    finally:
        runner.shutdown()
    for total, per_batch in [(1, 1), (7, 12), (10**20, 10**21)]:
        monkeypatch.setenv("DOCUFORGE_BATCH_MAX_ACTIVE_DOWNLOADS", f" {total} ")
        monkeypatch.setenv("DOCUFORGE_BATCH_MAX_DOWNLOADS_PER_BATCH", str(per_batch))
        configured = ApiSettings.from_environment()
        assert (configured.batch_max_active_downloads,
                configured.batch_max_downloads_per_batch) == (total, per_batch)
        runner = service(max_active_downloads=total, max_downloads_per_batch=per_batch)
        try:
            assert runner._max_active_downloads == total
            assert runner._max_downloads_per_batch == per_batch
        finally:
            runner.shutdown()


@pytest.mark.parametrize("limits", [(2, 2), (2, 5)])
def test_exact_global_boundary_release_and_duplicate_release(pool, limits):
    h = pool(global_limit=limits[0], batch_limit=limits[1])
    a, b = h.ready(), h.ready()
    first, second = h.acquire(a), h.acquire(b)
    assert first.reader is not second.reader
    assert first.reader.fileno() != second.reader.fileno()
    original = first.read_chunk(0, first.size_bytes)
    first.reader.seek(7)
    assert second.reader.tell() == 0
    assert second.read_chunk(0, 2) == b"PK"
    assert first.reader.tell() == 7
    assert_capacity(lambda: h.acquire(a))
    assert_capacity(lambda: h.acquire(b))
    first.release()
    replacement = h.acquire(a)
    first.release()
    assert not second.reader.closed and not replacement.reader.closed
    assert_capacity(lambda: h.acquire(b))
    assert replacement.read_chunk(0, replacement.size_bytes) == original
    second.release()
    replacement.release()
    assert h.runner._active_downloads == {}


def test_per_batch_limit_and_three_session_fairness(pool):
    h = pool(global_limit=4, batch_limit=2)
    a, b, c = h.ready(), h.ready(), h.ready()
    h.acquire(a)
    h.acquire(a)
    assert_capacity(lambda: h.acquire(a))  # Global slots still available.
    h.acquire(b)
    h.acquire(c)
    assert_capacity(lambda: h.acquire(b))  # Per-batch slot available, global full.
    h.handles[0].release()
    h.acquire(c)
    assert_capacity(lambda: h.acquire(c))
    assert all(not handle.reader.closed for handle in h.handles[1:])


def test_reentrant_service_release_closes_before_reusing_slot(pool):
    h = pool(global_limit=1, batch_limit=1)
    a = h.ready()
    first = h.acquire(a)
    release = first._release
    replacements = []
    def unpin():
        assert first.reader.closed
        release()
        replacements.append(h.acquire(a))
        release()  # The old pin cannot remove the newly accepted reader's pin.
    first._release = unpin
    first.release()
    first.release()
    assert len(replacements) == 1 and not replacements[0].reader.closed
    assert_capacity(lambda: h.acquire(a))


def test_default_fairness_preserves_slots_for_other_batches(pool):
    h = pool(global_limit=8, batch_limit=4)
    a, b, c = h.ready(), h.ready(), h.ready()
    for _ in range(4):
        h.acquire(a)
    assert_capacity(lambda: h.acquire(a))
    for _ in range(4):
        h.acquire(b)
    assert_capacity(lambda: h.acquire(c))


def test_rejection_is_atomic_and_precedes_archive_work(pool):
    h = pool(global_limit=1, batch_limit=1)
    a = h.ready()
    handle = h.acquire(a)
    runner = h.runner
    session = runner._sessions[a.id]
    before = replace(session)
    row = runner._repository.get(a.id) if runner._repository else None
    pins = {key: set(value) for key, value in runner._active_downloads.items()}
    admitted = set(runner._admitted_batch_ids)
    with (patch.object(batches, "_open_validated_download_archive") as opening,
          patch.object(persistence, "_archive_reader_is_valid") as crc,
          patch.object(runner, "_persist_or_api_error") as persist,
          patch.object(runner, "_require_capacity_locked") as worker_admission,
          patch.object(runner, "create_workspace") as workspace,
          patch.object(runner, "_require_storage_locked") as storage):
        assert_capacity(lambda: h.acquire(a))
    for operation in (opening, crc, persist, worker_admission, workspace, storage):
        operation.assert_not_called()
    assert session == before
    assert session.batch is before.batch and session.result is before.result
    assert runner._active_downloads == pins and runner._admitted_batch_ids == admitted
    assert a.workspace.archive_path.exists() and not handle.reader.closed
    if runner._repository:
        assert runner._repository.get(a.id) == row
    handle.release()
    assert session.updated_at == before.updated_at


def known_unavailable_error(h, target, absent):
    session = h.runner._sessions[target.id]
    with h.runner._lock:
        session.phase = BatchExecutionPhase.ERROR
        session.session_error = batches.BatchSessionError(
            "batch_execution_interrupted", "The batch was interrupted by a server restart.",
        )
        session.attempt = 3
        session.archive_path = None
        if absent == "result":
            session.result = None
        h.runner._persist_locked(session)
    return session


@pytest.mark.parametrize("absent", ["result", "path"])
def test_known_unavailable_archive_precedes_exhausted_global_capacity(pool, absent):
    h = pool(global_limit=1, batch_limit=1)
    held_batch, target = h.ready(), h.ready()
    held = h.acquire(held_batch)
    session = known_unavailable_error(h, target, absent)
    before = replace(session)
    row = h.runner._repository.get(target.id) if h.runner._repository else None
    pins = {key: set(value) for key, value in h.runner._active_downloads.items()}
    with (patch.object(batches, "_open_validated_download_archive") as opening,
          patch.object(persistence, "_archive_reader_is_valid") as crc,
          patch.object(h.runner, "_persist_or_api_error",
                       wraps=h.runner._persist_or_api_error) as persist,
          pytest.raises(ApiError) as caught):
        h.acquire(target)
    assert (caught.value.status_code, caught.value.code, caught.value.message) == (
        409, "batch_packaging_failed", "The batch archive is unavailable.",
    )
    opening.assert_not_called()
    crc.assert_not_called()
    persist.assert_called_once()
    assert session == before
    assert session.result is before.result and session.batch is before.batch
    assert session.session_error is before.session_error
    assert h.runner._active_downloads == pins and not held.reader.closed
    assert not h.runner._admitted_batch_ids and len(h.handles) == 1
    if h.runner._repository:
        assert h.runner._repository.get(target.id) == row


@pytest.mark.parametrize("pool", [True], indirect=True, ids=["durable"])
@pytest.mark.parametrize("absent", ["result", "path"])
def test_known_unavailable_persistence_failure_precedes_capacity(pool, absent):
    h = pool(global_limit=1, batch_limit=1)
    held_batch, target = h.ready(), h.ready()
    held = h.acquire(held_batch)
    session = known_unavailable_error(h, target, absent)
    before = replace(session)
    row = h.runner._repository.get(target.id)
    pins = {key: set(value) for key, value in h.runner._active_downloads.items()}
    with (patch.object(batches, "_open_validated_download_archive") as opening,
          patch.object(persistence, "_archive_reader_is_valid") as crc,
          patch.object(h.runner._repository, "save",
                       side_effect=BatchPersistenceError("private diagnostic")) as save,
          pytest.raises(ApiError) as caught):
        h.acquire(target)
    assert (caught.value.status_code, caught.value.code, caught.value.message) == (
        503, "batch_persistence_failed", "The batch session could not be persisted.",
    )
    opening.assert_not_called()
    crc.assert_not_called()
    save.assert_called_once()
    assert session == before and session.result is before.result
    assert session.session_error is before.session_error
    assert h.runner._repository.get(target.id) == row
    assert h.runner._active_downloads == pins and not held.reader.closed
    assert not h.runner._admitted_batch_ids and len(h.handles) == 1


@pytest.mark.parametrize("node", ["present", "missing", "corrupt"])
def test_known_path_still_checks_capacity_before_filesystem_validation(pool, node):
    h = pool(global_limit=1, batch_limit=1)
    held_batch, target = h.ready(), h.ready()
    held = h.acquire(held_batch)
    session = h.runner._sessions[target.id]
    if node == "missing":
        target.workspace.archive_path.unlink()
    elif node == "corrupt":
        target.workspace.archive_path.write_bytes(b"invalid ZIP")
    before = replace(session)
    row = h.runner._repository.get(target.id) if h.runner._repository else None
    pins = {key: set(value) for key, value in h.runner._active_downloads.items()}
    with (patch.object(batches, "_open_validated_download_archive") as opening,
          patch.object(persistence, "_archive_reader_is_valid") as crc):
        assert_capacity(lambda: h.acquire(target))
    opening.assert_not_called()
    crc.assert_not_called()
    assert session == before and session.result is before.result
    assert h.runner._active_downloads == pins and not held.reader.closed
    if h.runner._repository:
        assert h.runner._repository.get(target.id) == row


@pytest.mark.parametrize("denied", [None, "", "wrong-token", "malformed token", "other-batch"])
def test_private_capability_precedes_full_capacity(pool, denied):
    h = pool(global_limit=1, batch_limit=1)
    a, b = h.ready(), h.ready()
    h.acquire(a)
    token = b.token if denied == "other-batch" else denied
    with (patch.object(batches, "_open_validated_download_archive") as opening,
          patch.object(persistence, "_archive_reader_is_valid") as crc,
          pytest.raises(ApiError) as caught):
        h.runner.acquire_download(a.id, token)
    assert (caught.value.status_code, caught.value.code) == (404, "batch_not_found")
    opening.assert_not_called()
    crc.assert_not_called()


@pytest.mark.parametrize("phase", ["queued", "processing", "cancelling", "packaging",
                                   "deleting", "no-outputs"])
def test_eligibility_precedes_capacity(pool, phase):
    h = pool(global_limit=1, batch_limit=1)
    a, b = h.ready(), h.ready(invalid=phase == "no-outputs")
    h.acquire(a)
    target = h.runner._sessions[b.id]
    previous = target.phase
    if phase != "no-outputs":
        target.phase = BatchExecutionPhase(phase)
    try:
        with (patch.object(batches, "_open_validated_download_archive") as opening,
              patch.object(persistence, "_archive_reader_is_valid") as crc,
              pytest.raises(ApiError) as caught):
            h.acquire(b)
        expected = ("batch_has_no_outputs" if phase == "no-outputs" else
                    "batch_not_found" if phase == "deleting" else "batch_not_ready")
        assert (caught.value.status_code, caught.value.code) == (
            404 if phase == "deleting" else 409, expected,
        )
        opening.assert_not_called()
        crc.assert_not_called()
    finally:
        target.phase = previous


@pytest.mark.parametrize("constraint", ["global", "per-batch"])
def test_simultaneous_acquisition_and_release_are_bounded(pool, constraint):
    h = pool(global_limit=2 if constraint == "global" else 8, batch_limit=2)
    a, b = h.ready(), h.ready()
    barrier = Barrier(8)
    def acquire(index):
        barrier.wait(timeout=10)
        target = (a, b)[index % 2] if constraint == "global" else a
        try:
            return h.acquire(target)
        except ApiError as error:
            assert (error.status_code, error.code, error.message) == CAPACITY
            return None
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(acquire, range(8)))
    accepted = [handle for handle in results if handle is not None]
    assert len(accepted) == 2
    assert sum(map(len, h.runner._active_downloads.values())) == 2
    assert len({handle.reader.fileno() for handle in accepted}) == 2
    release_barrier = Barrier(4)
    def release(handle):
        release_barrier.wait(timeout=10)
        handle.release()
    # Duplicate concurrent releases must not free somebody else's slot.
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(release, accepted * 2))
    assert all(handle.reader.closed for handle in accepted)
    assert not h.runner._active_downloads
    h.acquire(a)
    h.acquire(a)
    assert_capacity(lambda: h.acquire(a))


@pytest.mark.parametrize("failure", ["constructor", "close"])
def test_failure_cleanup_recovers_capacity_and_preserves_existing_reader(pool, failure, caplog):
    h = pool()
    a = h.ready()
    existing = h.acquire(a)
    if failure == "constructor":
        readers = []
        opening = batches._open_validated_download_archive
        def track(*args):
            reader, node = opening(*args)
            readers.append(reader)
            return reader, node
        with (patch.object(batches, "_open_validated_download_archive", side_effect=track),
              patch.object(batches, "BatchDownloadHandle", side_effect=RuntimeError("constructor")),
              pytest.raises(RuntimeError)):
            h.acquire(a)
        assert readers and all(reader.closed for reader in readers)
    else:
        failed = h.acquire(a)
        reader = failed.reader
        class FailingClose:
            def close(self):
                reader.close()
                raise OSError("private close diagnostic")
        failed.reader = FailingClose()
        failed.release()
        failed.release()
        assert reader.closed
        assert caplog.messages == ["Batch download reader cleanup failed."]
    assert not existing.reader.closed and len(h.runner._active_downloads[a.id]) == 1
    h.acquire(a)
    assert_capacity(lambda: h.acquire(a))


@pytest.mark.parametrize("failure", ["normal", "range", "multipart", "head", "send", "cancel",
                                     "disconnect", "short-read"])
def test_response_exit_immediately_restores_capacity(pool, failure):
    h = pool(global_limit=1, batch_limit=1)
    a = h.ready()
    handle = h.acquire(a)
    original = handle.read_chunk(0, handle.size_bytes)
    headers = ([(b"range", b"bytes=0-9")] if failure == "range" else
               [(b"range", b"bytes=0-2,10-14")] if failure == "multipart" else [])
    messages = []
    if failure == "short-read":
        with handle.path.open("r+b") as writer:
            writer.truncate(0)
        handle.reader.seek(0, 2)
    async def run():
        started = asyncio.Event()
        async def send(message):
            messages.append(message)
            assert_capacity(lambda: h.acquire(a))
            assert not handle.reader.closed
            if message["type"] == "http.response.body":
                if failure == "send":
                    raise OSError("transport")
                if failure == "cancel":
                    raise asyncio.CancelledError()
                if failure == "disconnect":
                    started.set()
                    await asyncio.Event().wait()
        async def receive():
            await started.wait()
            return {"type": "http.disconnect"}
        await asyncio.wait_for(response(handle)(
            scope(headers, "HEAD" if failure == "head" else "GET",
                  "2.3" if failure == "disconnect" else "2.4"), receive, send,
        ), timeout=10)
    if failure in {"send", "short-read", "cancel"}:
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else OSError):
            asyncio.run(run())
    else:
        asyncio.run(run())
    assert handle.reader.closed and not h.runner._active_downloads
    if failure == "normal":
        assert b"".join(m.get("body", b"") for m in messages) == original
    if failure == "range":
        assert b"".join(m.get("body", b"") for m in messages) == original[:10]
    if failure == "short-read":
        assert messages == []
        a.workspace.archive_path.write_bytes(original)
    replacement = h.acquire(a)
    assert replacement.read_chunk(0, replacement.size_bytes) == original


def test_slow_independent_ranged_responses_hold_one_slot_each(pool):
    h = pool()
    a = h.ready()
    first, second = h.acquire(a), h.acquire(a)
    expected = first.read_chunk(0, first.size_bytes)
    bodies = [[], []]
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        async def slow_send(message):
            if message["type"] == "http.response.body":
                bodies[0].append(message["body"])
                started.set()
                await finish.wait()
        async def second_send(message):
            if message["type"] == "http.response.body":
                bodies[1].append(message["body"])
        pending = asyncio.create_task(response(first)(
            scope([(b"range", b"bytes=0-2,10-14")]), disconnected, slow_send,
        ))
        try:
            await asyncio.wait_for(started.wait(), 10)
            assert not first.reader.closed
            assert len(h.runner._active_downloads[a.id]) == 2
            assert_capacity(lambda: h.acquire(a))
            await response(second)(scope([(b"range", b"bytes=3-7")]), disconnected, second_send)
            assert second.reader.closed and not first.reader.closed
            replacement = h.acquire(a)
            replacement.release()
        finally:
            finish.set()
            await asyncio.wait_for(pending, 10)
    asyncio.run(run())
    assert b"".join(bodies[1]) == expected[3:8]
    assert expected[:3] in b"".join(bodies[0]) and expected[10:15] in b"".join(bodies[0])
    assert not h.runner._active_downloads
    h.acquire(a)


def test_corruption_is_examined_only_after_capacity_frees_and_packaging_recovers(pool):
    h = pool(global_limit=1, batch_limit=1)
    a, b = h.ready(), h.ready()
    held = h.acquire(a)
    b.workspace.archive_path.write_bytes(b"invalid ZIP")
    session = h.runner._sessions[b.id]
    before = replace(session)
    assert_capacity(lambda: h.acquire(b))
    assert session == before
    held.release()
    with pytest.raises(ApiError) as caught:
        h.acquire(b)
    assert (caught.value.status_code, caught.value.code) == (409, "batch_packaging_failed")
    assert session.phase is BatchExecutionPhase.ERROR
    assert not h.runner._active_downloads
    for item in session.request.items:
        item.input_path.unlink()
    with patch.object(batches, "batch_convert_images", side_effect=AssertionError("converter rerun")):
        h.runner.recover(b.id, b.token)
        wait_for(h.runner, b.id, b.token, BatchExecutionPhase.READY)
    transmit(h.acquire(b))


@pytest.mark.parametrize("pool", [True], indirect=True, ids=["durable"])
def test_persistence_failure_during_archive_degradation_consumes_no_capacity(pool):
    h = pool()
    a = h.ready()
    before = replace(h.runner._sessions[a.id])
    a.workspace.archive_path.write_bytes(b"invalid ZIP")
    with (patch.object(h.runner._repository, "save", side_effect=BatchPersistenceError("private")),
          pytest.raises(ApiError) as caught):
        h.acquire(a)
    assert (caught.value.status_code, caught.value.code) == (503, "batch_persistence_failed")
    assert h.runner._sessions[a.id] == before
    assert not h.runner._active_downloads


@pytest.mark.parametrize("action", ["delete", "ttl"])
def test_full_capacity_never_blocks_deletion_or_unrelated_retention(pool, action):
    h = pool(global_limit=1, batch_limit=1)
    a, b = h.ready(), h.ready()
    held = h.acquire(a)
    original = held.read_chunk(0, held.size_bytes)
    if action == "delete":
        h.runner.delete_session(b.id, b.token)
        h.runner.delete_session(a.id, a.token)
    else:
        session = h.runner._sessions[a.id]
        now = max(value.updated_at for value in h.runner._sessions.values())
        h.runner._clock = lambda: now + h.runner._terminal_ttl_seconds
        with h.runner._lock:
            h.runner._expire_locked()
        assert session.updated_at == now + h.runner._terminal_ttl_seconds
    assert not b.workspace.path.exists() and a.workspace.path.exists()
    with pytest.raises(ApiError) as caught:
        h.acquire(a)
    assert caught.value.code == "batch_not_found"
    assert held.read_chunk(0, held.size_bytes) == original
    held.release()
    assert not a.workspace.path.exists() and not h.runner._active_downloads


def test_worker_upload_status_and_cancellation_remain_independent(pool):
    h = pool(global_limit=1, batch_limit=1, max_inflight_sessions=1)
    a = h.ready()
    h.acquire(a)
    entered, finish = Event(), Event()
    convert = batches.batch_convert_images
    def blocked(*args, **kwargs):
        entered.set()
        assert finish.wait(10)
        return convert(*args, **kwargs)
    with patch.object(batches, "batch_convert_images", side_effect=blocked):
        workspace, value = create_request(h.runner, ("new-upload.png",))
        grant = h.runner.create_session(value, workspace)
        try:
            assert entered.wait(10)
            assert h.runner.get(a.id, a.token).phase is BatchExecutionPhase.READY
            assert str(value.batch_id) in h.runner._admitted_batch_ids
            assert a.id not in h.runner._admitted_batch_ids
            assert_capacity(lambda: h.acquire(a))
            # Full worker admission does not prevent an available download slot.
            h.handles[0].release()
            h.acquire(a)
            h.runner.cancel(str(value.batch_id), grant.access_token)
        finally:
            finish.set()
        wait_for(h.runner, str(value.batch_id), grant.access_token, BatchExecutionPhase.READY,
                 BatchExecutionPhase.ERROR)


def test_new_conversion_and_packaging_finish_at_full_download_capacity(pool):
    h = pool(global_limit=1, batch_limit=1, max_inflight_sessions=1)
    a = h.ready()
    held = h.acquire(a)
    b = h.ready()
    assert h.runner.get(b.id, b.token).phase is BatchExecutionPhase.READY
    assert b.workspace.archive_path.exists() and not h.runner._admitted_batch_ids
    assert not held.reader.closed
    assert_capacity(lambda: h.acquire(b))
    held.release()
    transmit(h.acquire(b))


def test_shutdown_at_capacity_drains_before_storage_owner_release(pool):
    h = pool(global_limit=1, batch_limit=1)
    a = h.ready()
    handle = h.acquire(a)
    waiting = Event()
    original = h.runner._downloads_drained.wait_for
    def wait(predicate):
        waiting.set()
        return original(predicate)
    with patch.object(h.runner._downloads_drained, "wait_for", side_effect=wait):
        thread = Thread(target=h.runner.shutdown)
        thread.start()
        try:
            assert waiting.wait(10)
            with pytest.raises(RuntimeError, match="shut down"):
                h.acquire(a)
            assert not handle.reader.closed and thread.is_alive()
            if h.storage:
                with pytest.raises(BatchStorageOwnershipError):
                    service(storage_directory=h.storage)
            handle.release()
            thread.join(10)
            assert not thread.is_alive()
        finally:
            handle.release()
            thread.join(10)


def test_active_reader_recovery_refusal_and_restart_capacity(pool):
    h = pool(global_limit=1, batch_limit=1)
    a = h.ready()
    target = h.runner._sessions[a.id]
    target.phase = BatchExecutionPhase.ERROR
    held = h.acquire(a)
    with pytest.raises(ApiError) as caught:
        h.runner.recover(a.id, a.token)
    assert (caught.value.status_code, caught.value.code) == (409, "batch_download_active")
    held.release()
    h.runner.recover(a.id, a.token)
    wait_for(h.runner, a.id, a.token, BatchExecutionPhase.READY)
    if h.storage:
        h.runner.shutdown()
        restarted = service(storage_directory=h.storage, max_active_downloads=1,
                            max_downloads_per_batch=1)
        try:
            assert not restarted._active_downloads
            handle = restarted.acquire_download(a.id, a.token)
            handle.release()
        finally:
            restarted.shutdown()


def test_app_settings_http_backpressure_and_app_isolation():
    settings = ApiSettings(batch_max_active_downloads=1, batch_max_downloads_per_batch=1)
    apps = [create_app(settings), create_app(settings)]
    held = []
    with TestClient(apps[0], raise_server_exceptions=False) as first, TestClient(apps[1]) as second:
        try:
            for app, client in zip(apps, (first, second)):
                created = client.post(
                    "/api/v1/batches/images/convert",
                    files=[("file", ("one.png", make_image(), "image/png"))],
                    data={"format": "jpg"},
                )
                assert created.status_code == 202
                batch_id, token = created.json()["id"], created.headers[BATCH_TOKEN_HEADER]
                runner = app.state.batch_service
                assert (runner._max_active_downloads, runner._max_downloads_per_batch) == (1, 1)
                wait_for(runner, batch_id, token, BatchExecutionPhase.READY)
                held.append(runner.acquire_download(batch_id, token))
                rejected = client.get(f"/api/v1/batches/{batch_id}/download",
                                      headers={BATCH_TOKEN_HEADER: token})
                assert rejected.status_code == 503
                assert rejected.json() == {"code": CAPACITY[1], "message": CAPACITY[2]}
                assert "retry-after" not in rejected.headers
                assert token not in rejected.text and batch_id not in rejected.text
                assert str(held[-1].path) not in rejected.text
                held[-1].release()
                downloaded = client.get(f"/api/v1/batches/{batch_id}/download",
                                        headers={BATCH_TOKEN_HEADER: token})
                assert downloaded.status_code == 200
                assert downloaded.headers["cache-control"] == "no-store"
                with ZipFile(io.BytesIO(downloaded.content)) as archive:
                    assert archive.testzip() is None
                if app is apps[0]:
                    with patch("docuforge.api.routes.batches._PinnedFileResponse",
                               side_effect=RuntimeError("constructor")):
                        failed = client.get(f"/api/v1/batches/{batch_id}/download",
                                            headers={BATCH_TOKEN_HEADER: token})
                    assert failed.status_code == 500 and not runner._active_downloads
                    # Keep the first app full while the second app accepts its reader.
                    held.append(runner.acquire_download(batch_id, token))
            schema = first.get("/openapi.json").json()
            assert "503" in schema["paths"]["/api/v1/batches/{batch_id}/download"]["get"]["responses"]
        finally:
            for handle in held:
                handle.release()

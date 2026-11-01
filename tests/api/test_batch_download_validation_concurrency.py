"""Event-controlled validation races: real CRC work, bounded pins and promotion."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import copy
from dataclasses import replace
from threading import Barrier, Event
from unittest.mock import patch

import pytest

from docuforge.api import batch_persistence as persistence
from docuforge.api import batches
from docuforge.api.batch_persistence import BatchPersistenceError
from docuforge.api.batch_storage_lock import BatchStorageOwnershipError
from docuforge.api.batches import BatchExecutionPhase
from docuforge.api.errors import ApiError
from tests.api import test_batch_download_admission as admission
from tests.api.test_batch_download_admission import assert_capacity
from tests.api.test_batch_service import create_request, service, wait_for

pool = admission.pool


@contextmanager
def stalled(h, target, *, fail=False):
    """Block one real descriptor scan, always unblock before joining the worker."""
    entered, finish = Event(), Event()
    readers = []
    result = h.runner._sessions[target.id].result
    original = persistence._archive_reader_is_valid

    def validate(reader, candidate):
        if candidate is result:
            readers.append(reader)
            entered.set()
            assert finish.wait(10), "validation was not resumed"
        return original(reader, candidate)

    if fail:
        target.workspace.archive_path.write_bytes(b"corrupt synthetic ZIP")
    with (
        patch.object(persistence, "_archive_reader_is_valid", side_effect=validate),
        ThreadPoolExecutor(max_workers=4) as executor,
    ):
        future = executor.submit(h.acquire, target)
        try:
            assert entered.wait(10), "validation did not start"
            yield executor, future, finish, readers
        finally:
            finish.set()
        # Fixture cleanup owns any promoted handle, even if an assertion failed.


def refused(future, code="batch_not_found", status=404):
    with pytest.raises(ApiError) as caught:
        future.result(timeout=10)
    assert (caught.value.status_code, caught.value.code) == (status, code)


def test_status_upload_and_cancellation_proceed_during_crc(pool):
    h = pool()
    a = h.ready()
    converting, finish_conversion = Event(), Event()
    original = batches.batch_convert_images

    def convert(*args, **kwargs):
        converting.set()
        assert finish_conversion.wait(10)
        return original(*args, **kwargs)

    with stalled(h, a) as (executor, pending, finish, readers):
        before = h.runner._sessions[a.id].updated_at
        assert executor.submit(h.runner.get, a.id, a.token).result(5).can_download
        with patch.object(batches, "batch_convert_images", side_effect=convert):
            try:
                workspace, request = executor.submit(create_request, h.runner, ("new.png",)).result(5)
                grant = executor.submit(h.runner.create_session, request, workspace).result(5)
                assert converting.wait(5)
                cancelled = executor.submit(
                    h.runner.cancel, str(request.batch_id), grant.access_token,
                ).result(5)
                assert cancelled.cancellation_requested
            finally:
                finish_conversion.set()
        pins = set(h.runner._active_downloads[a.id])
        finish.set()
        handle = pending.result(5)
        assert handle.reader is readers[0]
        assert h.runner._active_downloads[a.id] == pins
        assert h.runner._sessions[a.id].updated_at == before
        handle.release()
    assert not h.runner._active_downloads


@pytest.mark.parametrize("limit", ["global", "per-batch"])
@pytest.mark.parametrize("fail", [False, True])
def test_pending_capacity_is_atomic_and_transferred_without_gap(pool, limit, fail):
    h = pool(global_limit=1 if limit == "global" else 8, batch_limit=1)
    a, b = h.ready(), h.ready()
    target = b if limit == "global" else a
    with stalled(h, a, fail=fail) as (executor, pending, finish, readers):
        pins = set(h.runner._active_downloads[a.id])
        assert len(pins) == 1
        with patch.object(batches, "_open_validated_download_archive") as opening:
            executor.submit(assert_capacity, lambda: h.acquire(target)).result(5)
            opening.assert_not_called()
        finish.set()
        if fail:
            refused(pending, "batch_packaging_failed", 409)
            assert not h.runner._active_downloads and readers[0].closed
        else:
            handle = pending.result(5)
            assert handle.reader is readers[0]
            assert h.runner._active_downloads[a.id] == pins
            assert_capacity(lambda: h.acquire(target))
            handle.release()
            assert readers[0].closed and not h.runner._active_downloads


@pytest.mark.parametrize("action", ["delete", "ttl"])
@pytest.mark.parametrize("fail", [False, True])
def test_tombstone_wins_over_validation_and_defers_physical_cleanup(pool, action, fail):
    h = pool()
    a = h.ready()
    session = h.runner._sessions[a.id]
    with stalled(h, a, fail=fail) as (executor, pending, finish, readers):
        if action == "delete":
            executor.submit(h.runner.delete_session, a.id, a.token).result(5)
        else:
            now = session.updated_at + h.runner._terminal_ttl_seconds
            h.runner._clock = lambda: now
            refused(executor.submit(h.runner.get, a.id, a.token))
        assert session.phase is BatchExecutionPhase.DELETING
        assert a.workspace.path.exists() and not readers[0].closed
        if h.runner._repository:
            assert h.runner._repository.get(a.id).phase == "deleting"
        refused(executor.submit(h.acquire, a))
        finish.set()
        refused(pending)
        assert readers[0].closed
        assert not a.workspace.path.exists() and not h.runner._active_downloads
        assert a.id not in h.runner._sessions
    if h.storage:
        h.runner.shutdown()
        restored = service(storage_directory=h.storage)
        try:
            with pytest.raises(ApiError) as caught:
                restored.get(a.id, a.token)
            assert caught.value.code == "batch_not_found"
        finally:
            restored.shutdown()


def test_recovery_cannot_reset_archive_during_pending_validation(pool):
    h = pool()
    a = h.ready()
    session = h.runner._sessions[a.id]
    session.phase = BatchExecutionPhase.ERROR
    with stalled(h, a, fail=True) as (executor, pending, finish, readers):
        before = replace(session)
        refused(executor.submit(h.runner.recover, a.id, a.token), "batch_download_active", 409)
        assert session == before
        finish.set()
        refused(pending, "batch_packaging_failed", 409)
        assert readers[0].closed and not h.runner._active_downloads
    h.runner.recover(a.id, a.token)
    wait_for(h.runner, a.id, a.token, BatchExecutionPhase.READY)
    h.acquire(a).release()


def test_shutdown_enters_promptly_but_drains_pending_reader(pool):
    h = pool()
    a = h.ready()
    waiting = Event()
    original = h.runner._downloads_drained.wait_for

    def wait(predicate):
        waiting.set()
        return original(predicate)

    with (
        stalled(h, a) as (executor, pending, finish, readers),
        patch.object(h.runner._downloads_drained, "wait_for", side_effect=wait),
    ):
        shutdown = executor.submit(h.runner.shutdown)
        try:
            assert waiting.wait(5)
            assert h.runner._shutdown and not shutdown.done()
            assert not readers[0].closed
            if h.storage:
                with pytest.raises(BatchStorageOwnershipError):
                    service(storage_directory=h.storage)
            finish.set()
            with pytest.raises(RuntimeError, match="shut down"):
                pending.result(5)
            shutdown.result(5)
            assert readers[0].closed and not h.runner._active_downloads
        finally:
            finish.set()
            shutdown.result(10)


@pytest.mark.parametrize("fail", [False, True])
def test_another_validation_and_accepted_stream_are_independent(pool, fail):
    h = pool(global_limit=3, batch_limit=2)
    a, b = h.ready(), h.ready()
    existing = h.acquire(b)
    expected = existing.read_chunk(0, existing.size_bytes)
    with stalled(h, a, fail=fail) as (executor, pending, finish, readers):
        other = executor.submit(h.acquire, b).result(5)
        assert other.reader is not readers[0] and other.reader is not existing.reader
        assert executor.submit(existing.read_chunk, 0, existing.size_bytes).result(5) == expected
        assert other.read_chunk(0, other.size_bytes) == expected
        other.release()
        finish.set()
        if fail:
            refused(pending, "batch_packaging_failed", 409)
        else:
            pending.result(5).release()
        assert not existing.reader.closed and len(h.runner._active_downloads[b.id]) == 1
        existing.release()
        assert not h.runner._active_downloads


@pytest.mark.parametrize("change", ["session", "attempt", "result", "path", "phase",
                                   "cancellation", "cancel-request", "error", "workspace"])
def test_promotion_rechecks_expected_identity_without_false_corruption(pool, change):
    h = pool()
    a = h.ready()
    session = h.runner._sessions[a.id]
    before = replace(session)
    with stalled(h, a) as (_, pending, finish, readers):
        assert readers and not readers[0].closed
        with h.runner._lock:
            if change == "session":
                h.runner._sessions[a.id] = replace(session)
            elif change == "attempt":
                session.attempt += 1
            elif change == "result":
                session.result = replace(session.result)
            elif change == "path":
                session.archive_path = session.workspace.path / "different.zip"
            elif change == "phase":
                session.phase = BatchExecutionPhase.ERROR
            elif change == "cancellation":
                session.cancellation = batches.BatchCancellationToken()
            elif change == "cancel-request":
                session.cancellation.request_cancellation()
            elif change == "error":
                session.session_error = batches.BatchSessionError("changed", "changed")
            else:
                session.workspace = copy(session.workspace)
        finish.set()
        refused(pending)
        assert readers[0].closed and not h.runner._active_downloads
        # Refusal must not clear or degrade the replacement's authoritative state.
        assert session.archive_path is not None
        assert session.session_error is before.session_error or change == "error"
        h.runner._sessions[a.id] = before


@pytest.mark.parametrize("pool", [True], indirect=True, ids=["durable"])
def test_durable_failure_records_no_uncommitted_degradation(pool):
    h = pool()
    a = h.ready()
    before = replace(h.runner._sessions[a.id])
    row = h.runner._repository.get(a.id)
    with (
        stalled(h, a, fail=True) as (_, pending, finish, readers),
        patch.object(h.runner._repository, "save", side_effect=BatchPersistenceError("private")),
    ):
        finish.set()
        refused(pending, "batch_persistence_failed", 503)
        assert readers[0].closed and not h.runner._active_downloads
        assert h.runner._sessions[a.id] == before
        assert h.runner._repository.get(a.id) == row


@pytest.mark.parametrize("failure", ["constructor", "close", "unexpected", "remove"])
def test_failure_cleanup_closes_before_unpinning_and_preserves_other_pin(pool, failure, caplog):
    h = pool(global_limit=3)
    a, b = h.ready(), h.ready()
    existing = h.acquire(b)
    release = h.runner._release_download
    seen = []
    with stalled(h, a) as (_, pending, finish, readers):
        def unpin(batch_id, pin_id):
            assert readers[0].closed
            seen.append(pin_id)
            release(batch_id, pin_id)

        class BrokenRemove(set):
            def remove(self, value):
                raise RuntimeError("remove override")

            def discard(self, value):
                raise RuntimeError("remove override")

        def close():
            original_close()
            raise OSError("private close failure")

        with patch.object(h.runner, "_release_download", side_effect=unpin):
            if failure == "remove":
                h.runner._active_downloads[a.id] = BrokenRemove(h.runner._active_downloads[a.id])
            if failure == "close":
                original_close = readers[0].close
                readers[0].close = close
            error = RuntimeError("constructor") if failure != "unexpected" else ValueError("unexpected")
            with patch.object(batches, "BatchDownloadHandle", side_effect=error):
                finish.set()
                with pytest.raises(type(error)):
                    pending.result(5)
        assert seen and readers[0].closed
        assert set(h.runner._active_downloads) == {b.id} and not existing.reader.closed
        if failure == "close":
            assert caplog.messages == ["Batch download reader cleanup failed."]
    existing.release()
    assert not h.runner._active_downloads


@pytest.mark.parametrize("mutate", [False, True])
def test_pin_insertion_failure_never_opens_and_removes_empty_entries(pool, mutate):
    h = pool()
    a = h.ready()

    class BrokenInsert(set):
        def add(self, pin):
            if mutate:
                super().add(pin)
            raise RuntimeError("insertion failed")

    h.runner._active_downloads[a.id] = BrokenInsert()
    with (
        patch.object(batches, "_open_validated_download_archive") as opening,
        pytest.raises(RuntimeError, match="insertion failed"),
    ):
        h.acquire(a)
    opening.assert_not_called()
    assert not h.runner._active_downloads
    h.acquire(a).release()


def test_concurrent_failed_validations_close_and_free_only_their_own_pins(pool):
    h = pool(global_limit=3, batch_limit=2)
    a, b, c = h.ready(), h.ready(), h.ready()
    existing = h.acquire(c)
    a.workspace.archive_path.write_bytes(b"bad ZIP a")
    b.workspace.archive_path.write_bytes(b"bad ZIP b")
    barrier, finish = Barrier(3), Event()
    readers = []
    validator = persistence._archive_reader_is_valid

    def validate(reader, result):
        readers.append(reader)
        barrier.wait(10)
        assert finish.wait(10)
        return validator(reader, result)

    with (
        patch.object(persistence, "_archive_reader_is_valid", side_effect=validate),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        pending = [executor.submit(h.acquire, target) for target in (a, b)]
        try:
            barrier.wait(10)
            assert sum(map(len, h.runner._active_downloads.values())) == 3
            assert len({reader.fileno() for reader in readers}) == 2
            finish.set()
            for future in pending:
                refused(future, "batch_packaging_failed", 409)
            assert all(reader.closed for reader in readers)
            assert set(h.runner._active_downloads) == {c.id}
            assert not existing.reader.closed
        finally:
            finish.set()
            barrier.abort()
    existing.release()
    assert not h.runner._active_downloads


@pytest.mark.parametrize("where", ["opening", "scan", "promotion"])
def test_unexpected_exception_propagates_with_no_reader_or_capacity_leak(pool, where):
    h = pool()
    a = h.ready()
    before = replace(h.runner._sessions[a.id])
    readers = []
    fdopen = persistence.os.fdopen

    def track(*args, **kwargs):
        reader = fdopen(*args, **kwargs)
        readers.append(reader)
        return reader

    target, name = {
        "opening": (batches, "_open_validated_download_archive"),
        "scan": (persistence, "_archive_reader_is_valid"),
        "promotion": (h.runner, "_require_download_promotion_locked"),
    }[where]
    with (
        patch.object(persistence.os, "fdopen", side_effect=track),
        patch.object(target, name, side_effect=RuntimeError("unexpected failure")),
        pytest.raises(RuntimeError, match="unexpected failure"),
    ):
        h.acquire(a)
    assert not readers if where == "opening" else readers and all(r.closed for r in readers)
    assert not h.runner._active_downloads
    assert h.runner._sessions[a.id] == before
    h.acquire(a).release()

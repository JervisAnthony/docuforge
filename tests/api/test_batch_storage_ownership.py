"""Exclusive process-lifetime durable batch-storage ownership coverage."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import docuforge.api.batches as batches_module
from docuforge.api.batch_persistence import BatchPersistenceError
from docuforge.api.batch_storage_lock import (
    LOCK_FILE_NAME,
    BatchStorageOwnerLock,
    BatchStorageOwnershipError,
)
from docuforge.api.batches import BatchExecutionService
from tests.batch.test_document import RecordingEngine


def service(storage: Path | None = None) -> BatchExecutionService:
    return BatchExecutionService(
        office_engine_factory=RecordingEngine,
        max_workers=1,
        storage_directory=storage,
    )


def test_lock_contention_release_reacquire_and_stable_file(tmp_path: Path) -> None:
    first = BatchStorageOwnerLock.acquire(tmp_path)
    lock_path = tmp_path / LOCK_FILE_NAME
    identity = lock_path.stat().st_dev, lock_path.stat().st_ino
    assert lock_path.is_file()
    assert os.get_inheritable(first.descriptor) is False

    with pytest.raises(BatchStorageOwnershipError, match="already in use"):
        BatchStorageOwnerLock.acquire(tmp_path)

    first.release()
    first.release()
    assert lock_path.is_file()
    assert (lock_path.stat().st_dev, lock_path.stat().st_ino) == identity
    second = BatchStorageOwnerLock.acquire(tmp_path)
    second.release()
    assert (lock_path.stat().st_dev, lock_path.stat().st_ino) == identity


def test_preexisting_unlocked_file_and_different_roots_are_supported(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    first_root.mkdir()
    lock_path = first_root / LOCK_FILE_NAME
    lock_path.write_bytes(b"0")
    identity = lock_path.stat().st_dev, lock_path.stat().st_ino
    first = BatchStorageOwnerLock.acquire(first_root)
    second = BatchStorageOwnerLock.acquire(tmp_path / "second")
    first.release()
    second.release()
    assert lock_path.exists()
    assert (lock_path.stat().st_dev, lock_path.stat().st_ino) == identity


@pytest.mark.skipif(os.name == "nt", reason="POSIX creation modes apply on Linux")
def test_new_lock_file_has_private_permissions(tmp_path: Path) -> None:
    owner = BatchStorageOwnerLock.acquire(tmp_path)
    try:
        assert stat.S_IMODE((tmp_path / LOCK_FILE_NAME).stat().st_mode) == 0o600
    finally:
        owner.release()


def test_storage_root_and_lock_node_must_be_safe(tmp_path: Path) -> None:
    root_file = tmp_path / "root-file"
    root_file.write_bytes(b"x")
    with pytest.raises(BatchStorageOwnershipError):
        BatchStorageOwnerLock.acquire(root_file)

    directory_root = tmp_path / "directory-lock"
    directory_root.mkdir()
    (directory_root / LOCK_FILE_NAME).mkdir()
    with pytest.raises(BatchStorageOwnershipError):
        BatchStorageOwnerLock.acquire(directory_root)


def test_symlink_storage_root_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target-root"
    target.mkdir()
    root = tmp_path / "root-link"
    try:
        root.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable")
    with pytest.raises(BatchStorageOwnershipError) as captured:
        BatchStorageOwnerLock.acquire(root)
    assert str(root) not in str(captured.value)
    assert not (target / LOCK_FILE_NAME).exists()


def test_symlink_lock_file_is_rejected_without_touching_target(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "target"
    target.write_bytes(b"unchanged")
    try:
        (root / LOCK_FILE_NAME).symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(BatchStorageOwnershipError):
        BatchStorageOwnerLock.acquire(root)
    assert target.read_bytes() == b"unchanged"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_fifo_lock_node_is_rejected(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / LOCK_FILE_NAME)
    with pytest.raises(BatchStorageOwnershipError):
        BatchStorageOwnerLock.acquire(tmp_path)


def test_ephemeral_services_and_different_durable_roots_coexist(tmp_path: Path) -> None:
    ephemeral_a = service()
    ephemeral_b = service()
    durable_a = service(tmp_path / "a")
    durable_b = service(tmp_path / "b")
    try:
        assert ephemeral_a._storage_owner_lock is None
        assert ephemeral_b._storage_owner_lock is None
        assert durable_a._storage_owner_lock is not None
        assert durable_b._storage_owner_lock is not None
    finally:
        ephemeral_a.shutdown()
        ephemeral_b.shutdown()
        durable_a.shutdown()
        durable_b.shutdown()


def test_losing_service_does_not_initialize_repository(tmp_path: Path) -> None:
    first = service(tmp_path)
    try:
        with (
            patch.object(batches_module, "prepare_durable_storage") as prepare,
            pytest.raises(BatchStorageOwnershipError, match="already in use"),
        ):
            service(tmp_path)
        prepare.assert_not_called()
    finally:
        first.shutdown()


def test_constructor_failure_releases_ownership(tmp_path: Path) -> None:
    with (
        patch.object(
            batches_module,
            "prepare_durable_storage",
            side_effect=BatchPersistenceError("private database diagnostic"),
        ),
        pytest.raises(BatchPersistenceError),
    ):
        service(tmp_path)
    recovered = service(tmp_path)
    recovered.shutdown()


def test_service_shutdown_releases_last_and_is_idempotent(tmp_path: Path) -> None:
    first = service(tmp_path)
    with pytest.raises(BatchStorageOwnershipError):
        service(tmp_path)
    executor_shutdown = first._executor.shutdown

    def observe_executor_shutdown(*, wait: bool, cancel_futures: bool) -> None:
        with pytest.raises(BatchStorageOwnershipError):
            service(tmp_path)
        executor_shutdown(wait=wait, cancel_futures=cancel_futures)

    with patch.object(first._executor, "shutdown", side_effect=observe_executor_shutdown):
        first.shutdown()
    first.shutdown()
    second = service(tmp_path)
    second.shutdown()
    assert (tmp_path / LOCK_FILE_NAME).is_file()


def test_real_subprocess_contention_and_forced_exit_release(tmp_path: Path) -> None:
    child_code = """
import sys
from pathlib import Path
from docuforge.api.batches import BatchExecutionService
from docuforge.converters.office import LibreOfficeEngine
service = BatchExecutionService(
    office_engine_factory=LibreOfficeEngine,
    max_workers=1,
    storage_directory=Path(sys.argv[1]),
)
print("READY", flush=True)
sys.stdin.readline()
"""
    environment = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[2] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_root, environment.get("PYTHONPATH", "")) if part
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "READY"
        with pytest.raises(BatchStorageOwnershipError, match="already in use"):
            service(tmp_path)
        lock_path = tmp_path / LOCK_FILE_NAME
        identity = lock_path.stat().st_dev, lock_path.stat().st_ino
        child.kill()
        assert child.wait(timeout=10) != 0
        owner = service(tmp_path)
        owner.shutdown()
        assert (lock_path.stat().st_dev, lock_path.stat().st_ino) == identity
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)

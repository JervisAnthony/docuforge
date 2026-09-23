"""Process-lifetime ownership for one durable batch-storage root."""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from pathlib import Path

from docuforge.api.batch_persistence import BatchPersistenceError

LOCK_FILE_NAME = "batch-storage.lock"
_LOCK_CONTENT = b"0"


class BatchStorageOwnershipError(BatchPersistenceError):
    """Safe failure to establish exclusive durable-storage ownership."""


class BatchStorageOwnerLock:
    """An exclusive non-blocking OS lock held on a stable file descriptor."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor: int | None = descriptor

    @classmethod
    def acquire(cls, storage_root: Path) -> BatchStorageOwnerLock:
        root = _prepare_storage_root(storage_root)
        lock_path = root / LOCK_FILE_NAME
        descriptor = _open_lock_file(lock_path)
        try:
            _acquire_os_lock(descriptor)
        except OSError:
            os.close(descriptor)
            raise BatchStorageOwnershipError(
                "Durable batch storage is already in use by another process."
            ) from None
        return cls(descriptor)

    @property
    def descriptor(self) -> int:
        """Return the live descriptor for narrow diagnostics and tests."""
        if self._descriptor is None:
            raise BatchStorageOwnershipError("Durable batch storage ownership is not active.")
        return self._descriptor

    def release(self) -> None:
        """Release ownership without unlinking the stable lock file."""
        descriptor = self._descriptor
        if descriptor is None:
            return
        self._descriptor = None
        try:
            _release_os_lock(descriptor)
        except OSError:
            pass
        finally:
            with suppress(OSError):
                os.close(descriptor)


def _prepare_storage_root(storage_root: Path) -> Path:
    root = Path(storage_root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        node = root.lstat()
        if stat.S_ISLNK(node.st_mode) or not stat.S_ISDIR(node.st_mode):
            raise OSError
    except OSError:
        raise BatchStorageOwnershipError(
            "Durable batch storage ownership could not be established."
        ) from None
    return root


def _open_lock_file(lock_path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        if lock_path.exists() or lock_path.is_symlink():
            node = lock_path.lstat()
            if stat.S_ISLNK(node.st_mode) or not stat.S_ISREG(node.st_mode):
                raise OSError
        descriptor = os.open(lock_path, flags, 0o600)
        os.set_inheritable(descriptor, False)
        opened = os.fstat(descriptor)
        current = lock_path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise OSError
        if opened.st_size == 0:
            os.write(descriptor, _LOCK_CONTENT)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor
    except OSError:
        if "descriptor" in locals():
            with suppress(OSError):
                os.close(descriptor)
        raise BatchStorageOwnershipError(
            "Durable batch storage ownership could not be established."
        ) from None


if os.name == "nt":

    def _acquire_os_lock(descriptor: int) -> None:
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)

    def _release_os_lock(descriptor: int) -> None:
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)

else:

    def _acquire_os_lock(descriptor: int) -> None:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release_os_lock(descriptor: int) -> None:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)

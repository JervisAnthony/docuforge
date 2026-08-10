"""Request-scoped temporary workspace lifecycle management."""

import shutil
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Self

from starlette.background import BackgroundTask


class RequestWorkspace:
    """Own a unique temporary directory until cleanup is run or transferred."""

    def __init__(self) -> None:
        self._path = Path(tempfile.mkdtemp(prefix="docuforge-"))
        self._cleanup_transferred = False
        self._cleaned = False

    @property
    def path(self) -> Path:
        """Return the internal workspace path."""
        return self._path

    @property
    def cleanup_transferred(self) -> bool:
        """Report whether response-lifetime cleanup owns this workspace."""
        return self._cleanup_transferred

    def cleanup(self) -> None:
        """Recursively remove the workspace; repeated calls are safe."""
        if self._cleaned:
            return
        try:
            shutil.rmtree(self._path)
        except FileNotFoundError:
            pass
        self._cleaned = True

    def transfer_cleanup(self) -> BackgroundTask:
        """Transfer cleanup ownership to a response background task."""
        if self._cleaned:
            raise RuntimeError("cannot transfer cleanup for a cleaned workspace")
        if self._cleanup_transferred:
            raise RuntimeError("workspace cleanup has already been transferred")
        background_task = BackgroundTask(self.cleanup)
        self._cleanup_transferred = True
        return background_task

    def __enter__(self) -> Self:
        if self._cleaned:
            raise RuntimeError("cannot enter a cleaned workspace")
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if not self._cleanup_transferred:
            self.cleanup()

"""Framework-independent cooperative controls for sequential batch execution."""

from collections.abc import Callable
from threading import Event

from docuforge.batch.models import Batch

BatchProgressCallback = Callable[[Batch], None]


class BatchCancellationToken:
    """Thread-safe one-shot cooperative cancellation signal."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = Event()

    @property
    def cancellation_requested(self) -> bool:
        """Report whether cancellation has been requested."""
        return self._event.is_set()

    def request_cancellation(self) -> None:
        """Request cancellation idempotently."""
        self._event.set()

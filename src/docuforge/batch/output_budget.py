"""Internal accounting for trusted, successfully published batch files."""

import stat
from pathlib import Path

from docuforge.batch.exceptions import InvalidBatchDefinitionError
from docuforge.batch.models import BatchItemFailure

OUTPUT_LIMIT_FAILURE = BatchItemFailure(
    "batch_output_limit_exceeded", "The batch output limit was exceeded."
)


class PublishedOutputBudget:
    """Measure actual files; charge candidates only after atomic publication."""

    def __init__(self, max_bytes: int | None) -> None:
        if max_bytes is not None and (type(max_bytes) is not int or max_bytes <= 0):
            raise InvalidBatchDefinitionError(
                "max_published_output_bytes must be a positive integer or None."
            )
        self._max_bytes = max_bytes
        self._published_bytes = 0

    def candidate_size(self, path: Path) -> int:
        node = path.lstat()
        if not stat.S_ISREG(node.st_mode) or node.st_size <= 0:
            raise OSError("Published output must be a nonempty regular file.")
        return node.st_size

    def track_existing(self, path: Path) -> None:
        # A lowered deployment limit must never discard trusted preserved files.
        self.commit(self.candidate_size(path))

    def can_publish(self, candidate_bytes: int) -> bool:
        return self._max_bytes is None or (
            self._published_bytes + candidate_bytes <= self._max_bytes
        )

    def commit(self, candidate_bytes: int) -> None:
        self._published_bytes += candidate_bytes

# Batch retention

Terminal sessions expire at the configured TTL boundary. Downloads do not refresh
updated_at or extend TTL. Expired sessions become logically DELETING and disappear
from new access immediately. Physical cleanup waits for already accepted streams
and completes when their final download pin releases. Pinned tombstones are safe
for sweeper retries. See [download lifecycle](mvp3-batch-download-lifecycle.md).

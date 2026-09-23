# Batch admission control

## Purpose

`ThreadPoolExecutor` limits simultaneous workers but accepts an effectively unbounded submission
backlog. DocuForge adds bounded process-local admission so request bursts cannot accumulate
unlimited preparing workspaces, queued tasks, and active batch execution.

## Capacity model

One admission slot is occupied while a batch is preparing, QUEUED, PROCESSING, CANCELLING, or
PACKAGING. READY, ERROR, and DELETING sessions consume no execution admission. Terminal sessions
may remain available for download and recovery until deletion or TTL expiry.

## Default

The default service uses 2 workers and permits 8 inflight sessions. The inflight limit must be a
positive integer at least as large as the worker count. It is configured with
`DOCUFORGE_BATCH_MAX_INFLIGHT_SESSIONS`.

## Creation

The service reserves admission before it returns a DocuForge batch workspace for upload storage.
The reservation moves with the same BatchId from preparation into the registered QUEUED session.
Preparation, persistence, and task-submission failures release the reservation and clean the
unaccepted workspace. FastAPI may already have parsed multipart data into `UploadFile` spools before
the route runs; the boundary prevents further DocuForge workspace population and task submission.

## Recovery

Recovery reacquires admission before changing the attempt, phase, result, archive state, or durable
metadata. If capacity is exhausted, the retained terminal session and its capability remain
unchanged. Persistence or submission failure after reacquisition rolls back the attempt and releases
the slot.

## Backpressure

When all slots are occupied, creation and recovery fail immediately with HTTP 503,
`batch_capacity_exceeded`, and the message: `The batch service is temporarily at capacity. Try again
later.` The service does not wait, estimate completion time, or return a `Retry-After` value.

## Restart

Admission state is process-local and is never persisted. Durable sessions interrupted in an active
phase restore as ERROR without consuming a slot. An explicit recovery request must acquire fresh
admission before work can resume.

## Boundary

Admission bounds concurrently preparing, queued, and active execution. It is not rate limiting,
per-user quotas, aggregate retained-storage quota enforcement, distributed queueing, autoscaling, or
worker leasing. Terminal data can still consume storage until deletion or TTL expiry.

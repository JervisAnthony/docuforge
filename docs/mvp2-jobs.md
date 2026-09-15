# MVP2 job-processing foundation

## Purpose

MVP1 processes each request synchronously. MVP2 capabilities may require longer-running or
multi-step work, so DocuForge now has a framework-independent job contract before individual
features or execution infrastructure are introduced.

## Lifecycle

Jobs use immutable snapshots and explicit transitions:

```text
PENDING -> RUNNING -> COMPLETED
    |          |
    +----------+----> FAILED
```

`PENDING -> FAILED` supports validation failures found before execution. `COMPLETED` and `FAILED`
are terminal. Every job has a timezone-aware UTC creation timestamp; starting sets `started_at`,
and either terminal transition sets `finished_at`. Successful jobs carry a minimal result
descriptor, while failed jobs carry a safe error code and user-safe message rather than a raw
traceback.

## Separation of concerns

- The domain defines job identity, operation identity, request intent, result and failure values,
  lifecycle state, and transition rules without importing FastAPI or converter code.
- `JobManager` creates, retrieves, and advances jobs through a `JobRepository` contract.
- `InMemoryJobRepository` provides deterministic process-local storage for the current foundation.
- Converters remain independent of job storage and execution concerns.

The in-memory repository is instance-scoped and loses all state when its process exits. It does not
provide cross-process coordination, durable recovery, or distributed locking.

## Deliberate exclusions

This foundation adds no HTTP job endpoints, frontend job workflows, authentication or user accounts,
worker or queue infrastructure, persistent storage, scheduling, or cancellation. Commit 51 adds a
separate framework-independent [batch item model](mvp2-batch.md) for ordered multi-item state. Its
`BatchRequest` reuses `OperationKey`, but it does not yet integrate automatically with `JobManager`
or `JobRepository`, execute batch files, or add workers, queues, or persistence. Durable repositories
and worker integrations can implement the same job contracts when those capabilities are required.

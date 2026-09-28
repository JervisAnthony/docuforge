# Published batch output budget

## Purpose

Conversion can expand inputs, and individually valid outputs can accumulate within a batch.
API batch execution bounds cumulative retained published output bytes in both ephemeral and durable
storage modes. This policy applies to image conversion, resizing, compression, and Office-to-PDF.

## Configuration

`DOCUFORGE_BATCH_MAX_PUBLISHED_OUTPUT_BYTES` defaults to `209715200` (200 MiB).
It uses the existing strict positive-integer environment parser: blank, whitespace-only, zero,
negative, float, boolean words, unit suffixes, and malformed values fail startup.
`ApiSettings.batch_max_published_output_bytes` and the service constructor's
`max_published_output_bytes` require a positive exact integer; booleans are rejected.
The policy is independent of upload limits and the free-space reserve.

Direct Python batch functions accept keyword-only `max_published_output_bytes=None` by default,
preserving unlimited library behavior. Callers can opt into a positive exact integer budget.

## Exact guarantee

After staged-artifact validation, actual trusted regular-file size is measured using `lstat().st_size`.
A candidate is atomically published only when preserved/published bytes plus its size are `<=` the
limit. Equality succeeds; one byte above fails. Bytes are charged only after successful `os.replace`.
Invalid artifacts, rejected candidates, and failed publication consume no budget.

## Item behavior

An item that exceeds remaining capacity becomes `FAILED` with code `batch_output_limit_exceeded`
and message `The batch output limit was exceeded.` Its artifact stays in the owned temporary
workspace and disappears through normal cleanup. Other items continue; later smaller outputs may fit.
This is an ordinary item failure: execution reaches `READY` with no session error or new HTTP error.
A partial batch ZIP contains successes only. If all items fail, no archive is produced.

## Recovery

Completed outputs are preserved without reconversion. Their trusted actual file sizes count against
new attempts; serialized byte totals are not used. Failed items can be retried with the same capability.
A changed deployment limit takes effect on subsequent attempts, without changing persisted intent.
Raising the budget can allow recovery to succeed; the same limit can reproduce the item failure.

Reducing the limit never deletes or invalidates existing trusted outputs or prevents otherwise valid
packaging/download. Preserved bytes may already exceed the new limit; additional outputs then cannot
be published. Item failures persist and recover normally under schema v2, without storing budgets,
output sizes, or byte totals.

## Boundary

Only successfully published converted output files count. Inputs, temporary converter staging,
Office/image temporary artifacts, `result.zip`, SQLite metadata, and locks do not count.
The budget bounds retained published files, not temporary staging. It is not a complete workspace
quota, hard staging limit, or archive quota. ZIP size does not cause output-budget rejection.

## Relationship to storage pressure

The [durable filesystem headroom guard](mvp3-storage-pressure.md) protects backing filesystem
headroom at controlled boundaries, including staging and packaging pressure. The published output
budget controls retained output growth using an exact publication decision. These protections are
complementary; staging may temporarily grow between headroom checks.

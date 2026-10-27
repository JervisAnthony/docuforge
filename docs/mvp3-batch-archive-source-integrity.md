# Safe ZIP source pinning

## Problem

Preliminary path validation followed by `ZipFile.write()` leaves a gap: the ZIP
writer reopens the pathname and can consume a different node. Packaging now reads
only a descriptor whose identity matches the preliminary output snapshot.

## Descriptor-based packaging

`_validate_outputs(result)` still checks completed item identity, position,
descriptor, regular-file type, containment, and safe unique member basenames.
It retains ephemeral source and directory metadata for this packaging attempt.
`_open_verified_archive_source` rechecks the path, opens the source, and compares
`fstat` with that snapshot before reading. No API or session imports are required.

## Filesystem trust

Paths must be lexically inside the output root, without parent traversal. Valid
nested output directories remain supported. Every directory component, including
the output root and its ancestors, must be a real directory with its captured
device/inode/mode identity. Symlinks and recognized reparse points are rejected.
The source must be a regular file; FIFOs, sockets, devices, directories, missing
nodes, and replacements fail closed. Containment uses path relationships rather
than a string prefix. A replaced output root cannot silently become the new root.

## Bounded streaming

`ZipFile.open(ZipInfo(...), "w")` consumes fixed reads of at most 1 MiB from the
verified binary stream. Neither `ZipFile.write` nor `ZipInfo.from_file` reads or
stats converted sources. Successful outputs retain their existing order and exact
basenames, including Unicode names; failed/cancelled items add no ZIP members.
Members use DEFLATED compression. Metadata comes from the validated descriptor
snapshot: file mode, known byte size, and local modification time. DOS dates outside
1980–2107 are clamped to the nearest supported endpoint; DOS two-second precision
is unchanged. Known sizes select ZIP64 with the standard library's 5% sizing margin;
small files do not force ZIP64. No whole-file memory allocation is introduced.

## Mutation detection

Device/inode, mode, size, and nanosecond modification time must agree before opening,
after opening, and after streaming. POSIX change time is also compared. Windows
path and descriptor change/creation timestamps can differ, so ctime is excluded
there. Copied bytes must equal the original size; excess bytes reject immediately.
Each source's path and ancestry are checked after copying. After every member and
staged ZIP CRC validation have finished, **all** original source snapshots are
checked again immediately before publication. Earlier-member replacement while a
later member is processed therefore fails. Descriptors close after each member;
only bounded metadata references survive for final validation.

## Atomic publication

Packaging writes a temporary archive, verifies exact member order, uniqueness,
structure and CRC, rechecks sources, then uses `os.replace` to publish. Expected
filesystem and ZIP I/O failures become `BatchProcessingError("Unable to package
the batch outputs.")`, preserving exception chaining. Public errors contain no
source paths, contents or OS diagnostics. Unexpected programming exceptions and
interruptions retain their existing propagation behavior. Handles and staging
directories are cleaned on success and failure; a failed attempt before publication
leaves any previous destination bytes unchanged.

The execution service retains its existing recoverable `batch_packaging_failed`
ERROR state and durable publication ordering. Stable retained results permit
packaging-only recovery without rerunning conversion or reading original uploads.

## Relationship to existing integrity controls

- [Input fingerprints](mvp3-batch-input-integrity.md) compare original accepted
  upload bytes using SHA-256 before conversion; packaging does not rehash them.
- [Retained output integrity](mvp3-batch-output-integrity.md) checks image/PDF
  structure before reuse and restart.
- Source pinning validates the actual descriptor and observable stability while
  copying converted outputs into a new ZIP.
- [Archive integrity](mvp3-batch-archive-integrity.md) checks the retained ZIP's
  structure and CRC before downloads. Downloads do not rescan converted sources.

Changes to sources after successful publication do not retroactively invalidate
the committed ZIP. Download pins, cancellation, retention, deletion, budgets,
admission, schema v3 and HTTP contracts remain unchanged. There are no new
dependencies, durable fields, persistent descriptors or output digests.

## Platform boundaries

On POSIX systems supporting directory-relative operations, each ancestry component
is opened relative to its verified predecessor with `O_DIRECTORY | O_NOFOLLOW`.
The source uses `O_RDONLY | O_NOFOLLOW`, with `O_NONBLOCK` and `O_CLOEXEC` where
available. Directory and source descriptors must match captured identities.

Windows and platforms without these directory-relative/no-follow facilities use
repeated `lstat` ancestry/node checks and `lstat`/`fstat` identity comparison, binary
opening where available, and recognized reparse-point rejection. Ordinary Windows
packaging is supported without pywin32. This fallback is **not** a kernel-enforced
equivalent of POSIX no-follow traversal. It cannot exclude every transient link or
directory swap; its identity checks reject observable replacements before reading
and before publication. Windows may itself deny replacement of an open source.

## Limitations

These checks detect observable changes, not arbitrary hostile filesystem tampering.
They do not provide cryptographic output authenticity, a distributed filesystem
transaction, or atomicity against every concurrent in-place write. An adversary
able to preserve/restore metadata or act after the last check remains outside the
guarantee. CRC is structural integrity, not authentication. Source pinning adds no
archive-size quota and does not eliminate staging-space exhaustion risk.

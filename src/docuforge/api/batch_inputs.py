"""Private accepted-byte fingerprints and bounded original-upload verification."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from docuforge.batch import BatchItemId

INPUT_HASH_CHUNK_BYTES = 1024 * 1024


class BatchInputIntegrityError(RuntimeError):
    """An original upload cannot be safely read or compared."""


@dataclass(frozen=True, slots=True)
class BatchInputFingerprint:
    """One ordered item's accepted byte count and SHA-256; never public metadata."""

    item_id: BatchItemId
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", BatchItemId(self.item_id))
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("Invalid input fingerprint size.")
        if not isinstance(self.sha256, str) or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("Invalid input fingerprint digest.")


def _unsafe_link(node: os.stat_result) -> bool:
    return stat.S_ISLNK(node.st_mode) or bool(
        getattr(node, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _stream_digest(stream) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(INPUT_HASH_CHUNK_BYTES):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _snapshot(node: os.stat_result) -> tuple[int, int, int, int, int]:
    # Windows path and descriptor ctime can report different creation/change
    # timestamps. Identity, size and mtime remain comparable on both platforms.
    return (
        node.st_dev,
        node.st_ino,
        node.st_size,
        node.st_mtime_ns,
        (node.st_ctime_ns if os.name != "nt" else 0),
    )


def _inspect_input(path: Path, inputs_directory: Path, *, hash_content: bool):
    """Check ancestry/node/descriptor before reading; never intentionally follow a link."""
    try:
        if ".." in path.parts:
            raise ValueError
        root = inputs_directory.absolute()
        path = path.absolute()
        relative = path.relative_to(root)
        if not relative.parts:
            raise ValueError
        # Check every fixed parent before resolving/opening the requested file.
        for directory in (
            root.parent,
            root,
            *[root.joinpath(*relative.parts[:i]) for i in range(1, len(relative.parts))],
        ):
            node = directory.lstat()
            if _unsafe_link(node) or not stat.S_ISDIR(node.st_mode):
                raise ValueError
        before = path.lstat()
        if _unsafe_link(before) or not stat.S_ISREG(before.st_mode):
            raise ValueError
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        try:
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = None  # fdopen now owns descriptor cleanup.
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or _snapshot(before) != _snapshot(opened):
                    raise ValueError
                fingerprint = _stream_digest(stream) if hash_content else None
                after = os.fstat(stream.fileno())
                if _snapshot(opened) != _snapshot(after) or _snapshot(after) != _snapshot(
                    path.lstat()
                ):
                    raise ValueError
                if fingerprint is not None and fingerprint[0] != after.st_size:
                    raise ValueError
                return fingerprint
        finally:
            if descriptor is not None:
                os.close(descriptor)
    except (OSError, ValueError, RuntimeError) as error:
        raise BatchInputIntegrityError("Original batch inputs could not be verified.") from error


def capture_input_manifest(request, inputs_directory: Path) -> tuple[BatchInputFingerprint, ...]:
    return tuple(
        BatchInputFingerprint(
            item.id, *_inspect_input(item.input_path, inputs_directory, hash_content=True)
        )
        for item in request.items
    )


def validate_input_manifest(request, manifest: tuple[BatchInputFingerprint, ...]) -> None:
    if (
        not isinstance(manifest, tuple)
        or any(not isinstance(item, BatchInputFingerprint) for item in manifest)
        or tuple(item.item_id for item in manifest) != tuple(item.id for item in request.items)
        or len({item.item_id for item in manifest}) != len(manifest)
    ):
        raise ValueError("Input manifest does not match the request.")


def inputs_are_valid(request, manifest, inputs_directory: Path) -> bool:
    try:
        if manifest is not None:
            validate_input_manifest(request, manifest)
        for position, item in enumerate(request.items):
            actual = _inspect_input(
                item.input_path, inputs_directory, hash_content=manifest is not None
            )
            if manifest is not None and actual != (
                manifest[position].size_bytes,
                manifest[position].sha256,
            ):
                return False
        return True
    except (BatchInputIntegrityError, ValueError):
        return False


def manifest_payload(request, manifest) -> dict:
    validate_input_manifest(request, manifest)
    return {
        "version": 1,
        "algorithm": "sha256",
        "items": [
            {"item_id": str(item.item_id), "size_bytes": item.size_bytes, "sha256": item.sha256}
            for item in manifest
        ],
    }


def decode_manifest_payload(request, payload) -> tuple[BatchInputFingerprint, ...]:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "algorithm", "items"}
        or type(payload["version"]) is not int
        or payload["version"] != 1
        or payload["algorithm"] != "sha256"
        or not isinstance(payload["items"], list)
    ):
        raise ValueError("Invalid input manifest metadata.")
    values = []
    for item in payload["items"]:
        if not isinstance(item, dict) or set(item) != {"item_id", "size_bytes", "sha256"}:
            raise ValueError("Invalid input manifest metadata.")
        values.append(BatchInputFingerprint(item["item_id"], item["size_bytes"], item["sha256"]))
    manifest = tuple(values)
    validate_input_manifest(request, manifest)
    return manifest

"""Deliberate build metadata shared by packaging, the API and operations tools.

This module uses only the standard library so setuptools can run it in isolation.
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path

RESOURCE = "_build_identity.json"
FIELDS = {"schema_version", "service", "version", "revision"}


def revision(value: object) -> str:
    """Validate a complete ASCII Git SHA, without trimming supplied input."""
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[a-fA-F0-9]{40}", value) is None
        or value == "0" * 40
    ):
        raise ValueError("revision must be a full forty-character hexadecimal Git SHA")
    return value.lower()


def resolve_revision(explicit: str | None, provider: str | None) -> str | None:
    """Missing sources are unknown; supplied invalid or conflicting sources fail."""
    values = [revision(value) for value in (explicit, provider) if value is not None]
    if len(set(values)) > 1:
        raise ValueError("conflicting build revision sources")
    return values[0] if values else None


def validate_version(value: object) -> str:
    """Accept a bounded component version safe for diagnostics and HTML."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value) is None:
        raise ValueError("invalid component version")
    if len(value) > 64:
        raise ValueError("invalid component version")
    return value


def identity(version: str, source_revision: str | None, *, service: str = "docuforge") -> dict:
    """Construct the versioned, public contract, never copying an environment."""
    return {
        "schema_version": 1,
        "service": service,
        "version": validate_version(version),
        "revision": revision(source_revision) if source_revision is not None else None,
    }


def validate_identity(payload: object, *, service: str) -> dict:
    """Reject corrupt/incompatible stamps and return only deliberate fields."""
    if not isinstance(payload, dict) or set(payload) != FIELDS:
        raise ValueError("invalid build identity fields")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported build identity schema")
    if payload["service"] != service:
        raise ValueError("unexpected build identity service")
    return identity(payload["version"], payload["revision"], service=service)


def parse_identity(data: bytes, *, service: str) -> dict:
    """Parse JSON without ambiguous duplicate keys or unbounded stamp sizes."""

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate build identity field")
            result[key] = value
        return result

    if len(data) > 4096:
        raise ValueError("build identity exceeds size limit")
    try:
        payload = json.loads(data, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid build identity JSON") from error
    return validate_identity(payload, service=service)


def write_stamp(destination: Path, *, version: str, explicit=None, provider=None) -> None:
    """Always overwrite the artifact stamp, including an unstamped later build."""
    stamp = identity(version, resolve_revision(explicit, provider))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(stamp, sort_keys=True) + "\n", encoding="utf-8")


def read_identity() -> dict:
    """Read the installed resource; runtime environment and Git are irrelevant."""
    from docuforge.version import package_version

    resource = files("docuforge").joinpath(RESOURCE)
    try:
        with resource.open("rb") as stream:
            data = stream.read(4097)
    except FileNotFoundError:
        return identity(package_version(), None)
    stamp = parse_identity(data, service="docuforge")
    if stamp["version"] != package_version():
        raise ValueError("packaged build identity version mismatch")
    return stamp

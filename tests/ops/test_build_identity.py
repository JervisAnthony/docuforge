import json

import pytest

from docuforge import build_identity as builds

SHA = "a1" * 20


@pytest.mark.parametrize(
    "explicit,provider,expected",
    [
        (None, None, None),
        (SHA, None, SHA),
        (None, SHA.upper(), SHA),
        (SHA.upper(), SHA, SHA),
    ],
)
def test_revision_sources(explicit, provider, expected):
    assert builds.resolve_revision(explicit, provider) == expected


@pytest.mark.parametrize(
    "value",
    ["", " ", "abc123", "main", "unknown", "g" * 40, SHA + "\n", "\t" + SHA, "０" * 40, 1, True],
)
def test_invalid_revision_never_becomes_unknown(value):
    with pytest.raises(ValueError):
        builds.resolve_revision(value, None)
    with pytest.raises(ValueError):
        builds.resolve_revision(SHA, value)


def test_conflicting_sources():
    with pytest.raises(ValueError, match="conflicting"):
        builds.resolve_revision(SHA, "b" * 40)


def test_git_null_object_placeholder_is_not_a_revision():
    with pytest.raises(ValueError):
        builds.resolve_revision("0" * 40, None)


def test_present_version_mismatch_cannot_fall_back(monkeypatch, tmp_path):
    monkeypatch.setattr(builds, "files", lambda package: tmp_path)
    builds.write_stamp(tmp_path / builds.RESOURCE, version="0.0.9", explicit=SHA)
    with pytest.raises(ValueError, match="version mismatch"):
        builds.read_identity()


def test_stamp_is_deterministic_and_later_unknown_build_overwrites(tmp_path):
    target = tmp_path / builds.RESOURCE
    builds.write_stamp(target, version="0.1.0", explicit=SHA.upper())
    first = target.read_bytes()
    builds.write_stamp(target, version="0.1.0", explicit=SHA)
    assert target.read_bytes() == first
    builds.write_stamp(target, version="0.1.0")
    assert json.loads(target.read_bytes()) == builds.identity("0.1.0", None)


def test_reader_ignores_runtime_variables_and_no_git(monkeypatch, tmp_path):
    monkeypatch.setattr(builds, "files", lambda package: tmp_path)
    monkeypatch.setenv("DOCUFORGE_BUILD_REVISION", "private-invalid-input")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "b" * 40)
    monkeypatch.chdir(tmp_path)
    assert builds.read_identity() == builds.identity("0.1.0", None)
    builds.write_stamp(tmp_path / builds.RESOURCE, version="0.1.0", explicit=SHA)
    assert builds.read_identity() == builds.identity("0.1.0", SHA)


@pytest.mark.parametrize(
    "data",
    [b"", b"null", b"[]", b"not-json", b"x" * 4097, b'{"schema_version":1,"schema_version":1}'],
)
def test_present_corrupt_stamp_cannot_fall_back(monkeypatch, tmp_path, data):
    monkeypatch.setattr(builds, "files", lambda package: tmp_path)
    (tmp_path / builds.RESOURCE).write_bytes(data)
    with pytest.raises(ValueError):
        builds.read_identity()


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("schema_version", 2),
        ("schema_version", "1"),
        ("service", "other"),
        ("version", "private\nversion"),
        ("revision", False),
        ("revision", ""),
        ("revision", "abc"),
    ],
)
def test_contract_types_and_fields(field, value):
    payload = builds.identity("0.1.0", SHA)
    payload[field] = value
    with pytest.raises(ValueError):
        builds.validate_identity(payload, service="docuforge")


def test_unknown_and_unexpected_fields():
    payload = builds.identity("0.1.0", None)
    assert builds.validate_identity(payload, service="docuforge") == payload
    payload["secret"] = "private"
    with pytest.raises(ValueError):
        builds.validate_identity(payload, service="docuforge")

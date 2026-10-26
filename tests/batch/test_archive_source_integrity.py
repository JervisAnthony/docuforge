"""Deterministic source races at the validation/open/stream/publication boundaries."""

import os
import stat
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from docuforge.batch import BatchProcessingError, package_batch_outputs
from docuforge.batch import archive as module
from tests.batch.test_archive import assert_no_workspace, image_result


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / "outputs"
    root.mkdir()
    result = image_result(root, ("0001-résumé.pdf", "0002-雪 image.png"))
    destination = tmp_path / "result.zip"
    package_batch_outputs(result, destination)
    return result, destination, destination.read_bytes()


def rejected(result, destination, previous):
    with pytest.raises(BatchProcessingError) as caught:
        package_batch_outputs(result, destination)
    assert str(caught.value) == "Unable to package the batch outputs."
    assert destination.read_bytes() == previous
    assert_no_workspace(destination.parent)


def symlink(path, target, *, directory=False):
    try:
        path.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("symlink creation unavailable")


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink", "fifo", "outside"])
def test_wrong_nodes_rejected_before_packaging(fixture, tmp_path, kind):
    result, destination, previous = fixture
    path = result.outputs[0].output_path
    sentinel = tmp_path / path.name
    sentinel.write_bytes(b"EXTERNAL SENTINEL")
    if kind == "outside":
        result = replace(result, outputs=(
            replace(result.outputs[0], output_path=sentinel), *result.outputs[1:],
        ))
    else:
        path.unlink()
        if kind == "directory":
            path.mkdir()
        elif kind == "symlink":
            symlink(path, sentinel)
        elif kind == "fifo":
            if not hasattr(os, "mkfifo"):
                pytest.skip("FIFO creation unavailable")
            os.mkfifo(path)
    rejected(result, destination, previous)
    assert sentinel.read_bytes() == b"EXTERNAL SENTINEL"


@pytest.mark.parametrize("kind", ["regular", "symlink", "directory", "root", "root-symlink"])
def test_replacement_after_preliminary_validation(fixture, tmp_path, monkeypatch, kind):
    result, destination, previous = fixture
    path = result.outputs[0].output_path
    sentinel = tmp_path / "external"
    sentinel.write_bytes(b"EXTERNAL SENTINEL")
    validate = module._validate_outputs

    def replace_after_validation(value):
        sources = validate(value)
        if kind.startswith("root"):
            root = result.output_directory
            root.rename(tmp_path / "original-outputs")
            if kind == "root-symlink":
                symlink(root, tmp_path / "original-outputs", directory=True)
            else:
                root.mkdir()
                for output in result.outputs:
                    output.output_path.write_bytes(b"REPLACEMENT")
        else:
            path.rename(tmp_path / "original")
            if kind == "regular":
                path.write_bytes(b"CHANGED")  # Same byte count as image-0; different inode.
            elif kind == "symlink":
                symlink(path, sentinel)
            else:
                path.mkdir()
        return sources

    monkeypatch.setattr(module, "_validate_outputs", replace_after_validation)
    rejected(result, destination, previous)
    assert sentinel.read_bytes() == b"EXTERNAL SENTINEL"
    with ZipFile(destination) as archive:
        assert b"EXTERNAL SENTINEL" not in [archive.read(n) for n in archive.namelist()]


@pytest.mark.parametrize("kind", ["regular", "symlink", "fifo"])
def test_replacement_between_lstat_and_open(fixture, tmp_path, monkeypatch, kind):
    result, destination, previous = fixture
    path = result.outputs[0].output_path
    real_open = os.open
    replaced = False

    def opening(name, flags, *args, **kwargs):
        nonlocal replaced
        if Path(name).name == path.name and not replaced:
            replaced = True
            path.rename(tmp_path / "original")
            if kind == "symlink":
                sentinel = tmp_path / "sentinel"
                sentinel.write_bytes(b"EXTERNAL SENTINEL")
                symlink(path, sentinel)
            elif kind == "fifo":
                if not hasattr(os, "mkfifo"):
                    pytest.skip("FIFO creation unavailable")
                assert flags & os.O_NONBLOCK
                os.mkfifo(path)
            else:
                path.write_bytes(b"CHANGED")
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", opening)
    rejected(result, destination, previous)
    assert replaced


@pytest.mark.parametrize("kind", ["regular", "symlink"])
def test_path_replacement_after_open_never_reads_replacement(fixture, tmp_path, monkeypatch, kind):
    result, destination, previous = fixture
    path = result.outputs[0].output_path
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"EXTERNAL SENTINEL")
    opening = module._open_verified_archive_source
    consumed = []

    @contextmanager
    def replace_after_open(source):
        with opening(source) as stream:
            if source.path == path:
                try:
                    path.rename(tmp_path / "original")
                except PermissionError:
                    # Windows can deny deletion of an open file. Simulate the
                    # changed path identity, while still reading the real pinned fd.
                    real_lstat = Path.lstat
                    replacement_node = sentinel.lstat()
                    monkeypatch.setattr(Path, "lstat", lambda p, *a, **k: (
                        replacement_node if p == path else real_lstat(p, *a, **k)
                    ))
                else:
                    if kind == "symlink":
                        symlink(path, sentinel)
                    else:
                        path.write_bytes(b"REPLACEMENT")

                class Reader:
                    def read(self, size):
                        data = stream.read(size)
                        consumed.append(data)
                        return data

                yield Reader()
            else:
                yield stream

    monkeypatch.setattr(module, "_open_verified_archive_source", replace_after_open)
    rejected(result, destination, previous)
    assert b"".join(consumed) == b"image-0"
    assert sentinel.read_bytes() == b"EXTERNAL SENTINEL"


@pytest.mark.parametrize("kind", ["truncate", "append", "in-place"])
def test_mutation_during_bounded_copy(fixture, monkeypatch, kind):
    result, destination, previous = fixture
    path = result.outputs[0].output_path
    path.write_bytes(b"a" * (module.ARCHIVE_CHUNK_BYTES * 2 + 19))
    opening = module._open_verified_archive_source
    reads = []

    @contextmanager
    def changing(source):
        with opening(source) as stream:
            class Reader:
                def read(self, size):
                    assert 0 < size <= module.ARCHIVE_CHUNK_BYTES
                    data = stream.read(size)
                    if source.path == path and not reads:
                        if kind == "truncate":
                            with path.open("r+b") as writer:
                                writer.truncate(1)
                        elif kind == "append":
                            with path.open("ab") as writer:
                                writer.write(b"appended")
                        else:
                            with path.open("r+b") as writer:
                                writer.write(b"changed")
                            node = path.stat()
                            os.utime(path, ns=(node.st_atime_ns, node.st_mtime_ns + 2_000_000_000))
                    reads.append(size)
                    return data
            yield Reader()

    monkeypatch.setattr(module, "_open_verified_archive_source", changing)
    rejected(result, destination, previous)
    assert reads


@pytest.mark.parametrize("boundary", ["later-member", "staged-validation"])
def test_final_revalidation_of_earlier_source(fixture, tmp_path, monkeypatch, boundary):
    result, destination, previous = fixture
    first = result.outputs[0].output_path

    def replace_first():
        first.rename(tmp_path / "original")
        first.write_bytes(b"CHANGED")

    if boundary == "later-member":
        streaming = module._stream_archive_member

        def stream(archive, source, name):
            if source.path == result.outputs[1].output_path:
                replace_first()
            streaming(archive, source, name)
        monkeypatch.setattr(module, "_stream_archive_member", stream)
    else:
        validating = module._valid_staged_archive

        def validate(*args, **kwargs):
            valid = validating(*args, **kwargs)
            replace_first()
            return valid
        monkeypatch.setattr(module, "_valid_staged_archive", validate)
    rejected(result, destination, previous)


@pytest.mark.parametrize("failure", ["fstat", "read", "write", "post-read", "validate", "publish"])
def test_descriptor_and_staging_cleanup_on_failure(fixture, monkeypatch, failure):
    result, destination, previous = fixture
    opened = []
    streams = []
    real_open, real_fdopen, real_fstat = os.open, os.fdopen, os.fstat

    def opening(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def fdopen(*args, **kwargs):
        stream = real_fdopen(*args, **kwargs)
        streams.append(stream)
        return stream

    monkeypatch.setattr(module.os, "open", opening)
    monkeypatch.setattr(module.os, "fdopen", fdopen)
    if failure == "fstat":
        def fstat(descriptor):
            node = real_fstat(descriptor)
            if stat.S_ISREG(node.st_mode):
                raise OSError("private diagnostic")
            return node
        monkeypatch.setattr(module.os, "fstat", fstat)
    elif failure == "write":
        monkeypatch.setattr("zipfile._ZipWriteFile.write", lambda *a: (_ for _ in ()).throw(
            OSError("private diagnostic")
        ))
    elif failure == "validate":
        monkeypatch.setattr(module, "_valid_staged_archive", lambda *a, **k: False)
    elif failure == "publish":
        monkeypatch.setattr(module.os, "replace", lambda *a: (_ for _ in ()).throw(OSError()))
    else:
        opening_source = module._open_verified_archive_source

        @contextmanager
        def failing(source):
            with opening_source(source) as stream:
                if failure == "read":
                    class Reader:
                        def read(self, size):
                            raise OSError("private diagnostic")
                    yield Reader()
                else:
                    yield stream
                    raise OSError("private diagnostic")
        monkeypatch.setattr(module, "_open_verified_archive_source", failing)
    rejected(result, destination, previous)
    assert opened
    assert all(stream.closed for stream in streams)
    for descriptor in opened:
        with pytest.raises(OSError):
            real_fstat(descriptor)


def test_streaming_metadata_unicode_crc_and_no_path_reopen(fixture, monkeypatch):
    result, destination, _ = fixture
    path = result.outputs[0].output_path
    os.utime(path, (0, 0))  # Deliberately normalized DOS date.
    monkeypatch.setattr(ZipFile, "write", lambda *a, **k: pytest.fail("path reopen"))
    monkeypatch.setattr("zipfile.ZipInfo.from_file", lambda *a, **k: pytest.fail("path stat"))
    package_batch_outputs(result, destination)
    with ZipFile(destination) as archive:
        assert archive.namelist() == [output.output_path.name for output in result.outputs]
        assert [archive.read(n) for n in archive.namelist()] == [b"image-0", b"image-1"]
        assert all(info.compress_type == ZIP_DEFLATED for info in archive.infolist())
        assert archive.infolist()[0].date_time == (1980, 1, 1, 0, 0, 0)
        assert archive.infolist()[0].external_attr >> 16 == path.stat().st_mode & 0xFFFF
        assert archive.testzip() is None
    assert_no_workspace(destination.parent)


def test_valid_nested_paths_and_parent_traversal(fixture, monkeypatch):
    result, destination, previous = fixture
    first = result.outputs[0]
    nested = result.output_directory / "nested"
    nested.mkdir()
    moved = nested / first.output_path.name
    first.output_path.rename(moved)
    result = replace(result, outputs=(replace(first, output_path=moved), *result.outputs[1:]))
    package_batch_outputs(result, destination)
    previous = destination.read_bytes()
    traversing = nested / ".." / "nested" / moved.name
    result = replace(result, outputs=(replace(first, output_path=traversing), *result.outputs[1:]))
    rejected(result, destination, previous)


def test_rejects_symlinked_nested_directory(fixture):
    result, destination, previous = fixture
    nested = result.output_directory / "nested"
    symlink(nested, result.output_directory, directory=True)
    output = result.outputs[0]
    result = replace(result, outputs=(
        replace(output, output_path=nested / output.output_path.name), *result.outputs[1:],
    ))
    rejected(result, destination, previous)


@pytest.mark.parametrize("large", [False, True])
def test_zip64_size_seam(fixture, monkeypatch, large):
    result, destination, _ = fixture
    # Exercise real ZipFile.open with a reduced ZIP64 threshold, not a huge file.
    threshold = 5 if large else 2**31 - 1
    monkeypatch.setattr(module, "ZIP64_LIMIT", threshold)
    monkeypatch.setattr("zipfile.ZIP64_LIMIT", threshold)
    opening = ZipFile.open
    forced = []

    def member(self, name, mode="r", *args, **kwargs):
        if mode == "w":
            forced.append(kwargs.get("force_zip64"))
        return opening(self, name, mode, *args, **kwargs)

    monkeypatch.setattr(ZipFile, "open", member)
    package_batch_outputs(result, destination)
    assert forced == [large, large]
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert archive.read(result.outputs[0].output_path.name) == b"image-0"
        assert (archive.infolist()[0].extract_version >= 45) is large


@pytest.mark.parametrize("node_type", [stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFDIR])
def test_descriptor_must_be_regular(fixture, monkeypatch, node_type):
    result, destination, previous = fixture
    real_fstat = os.fstat

    def fstat(fd):
        node = real_fstat(fd)
        if stat.S_ISREG(node.st_mode):
            return SimpleNamespace(st_mode=node_type)
        return node

    monkeypatch.setattr(module.os, "fstat", fstat)
    rejected(result, destination, previous)


def test_recognized_reparse_point_is_unsafe():
    node = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
    with patch.object(module.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400, create=True):
        assert module._unsafe_link(node)


def test_sources_changing_after_success_do_not_change_committed_zip(fixture):
    result, destination, previous = fixture
    result.outputs[0].output_path.write_bytes(b"later mutation")
    assert destination.read_bytes() == previous
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert archive.read(result.outputs[0].output_path.name) == b"image-0"


def test_root_replaced_after_members_are_copied(fixture, tmp_path, monkeypatch):
    result, destination, previous = fixture
    validate = module._valid_staged_archive

    def replaced_root(*args, **kwargs):
        valid = validate(*args, **kwargs)
        result.output_directory.rename(tmp_path / "original-outputs")
        result.output_directory.mkdir()
        for output in result.outputs:
            output.output_path.write_bytes(b"replacement")
        return valid

    monkeypatch.setattr(module, "_valid_staged_archive", replaced_root)
    rejected(result, destination, previous)


def test_fallback_and_open_flags_close_successful_streams(fixture, monkeypatch):
    result, destination, _ = fixture
    monkeypatch.setattr(module, "_DIRECTORY_RELATIVE_OPEN", False)
    opening, fdopen = os.open, os.fdopen
    flags_seen, streams = [], []

    def open_source(path, flags, *args, **kwargs):
        if Path(path).name in {output.output_path.name for output in result.outputs}:
            flags_seen.append(flags)
        return opening(path, flags, *args, **kwargs)

    def stream(*args, **kwargs):
        result = fdopen(*args, **kwargs)
        streams.append(result)
        return result

    monkeypatch.setattr(module.os, "open", open_source)
    monkeypatch.setattr(module.os, "fdopen", stream)
    package_batch_outputs(result, destination)
    assert len(flags_seen) == len(result.outputs)
    for flags in flags_seen:
        for flag in ("O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC", "O_BINARY"):
            value = getattr(os, flag, 0)
            assert flags & value == value
    assert streams and all(stream.closed for stream in streams)
    with ZipFile(destination) as archive:
        assert archive.testzip() is None


def test_unexpected_descriptor_metadata_is_rejected(fixture, monkeypatch):
    result, destination, previous = fixture
    real_fstat = os.fstat

    def fstat(fd):
        node = real_fstat(fd)
        if stat.S_ISREG(node.st_mode):
            return SimpleNamespace(**{
                key: getattr(node, key) for key in (
                    "st_mode", "st_dev", "st_ino", "st_mtime_ns", "st_ctime_ns",
                )
            }, st_size=node.st_size + 1)
        return node

    monkeypatch.setattr(module.os, "fstat", fstat)
    rejected(result, destination, previous)

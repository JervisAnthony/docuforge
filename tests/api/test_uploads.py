import asyncio
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from docuforge.api import ApiSettings
from docuforge.api.errors import ApiError
from docuforge.api.uploads import StoredUpload, UploadPolicy, store_uploads
from docuforge.api.workspace import RequestWorkspace


def _upload(filename: str | None, content: bytes, content_type: str = "application/octet-stream") -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def _policy(
    *,
    max_files: int = 5,
    max_file_bytes: int = 20,
    max_request_bytes: int = 50,
    chunk_bytes: int = 4,
    allowed_extensions: frozenset[str] | None = None,
) -> UploadPolicy:
    return UploadPolicy(
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_request_bytes=max_request_bytes,
        chunk_bytes=chunk_bytes,
        allowed_extensions=allowed_extensions,
    )


@pytest.mark.parametrize(
    ("filename", "expected_name"),
    [
        ("simple.pdf", "simple.pdf"),
        ("REPORT.PDF", "REPORT.PDF"),
        ("../../secret.pdf", "secret.pdf"),
        ("..\\..\\secret.pdf", "secret.pdf"),
        ("C:\\Users\\someone\\secret.pdf", "secret.pdf"),
        ("/tmp/secret.pdf", "secret.pdf"),
    ],
)
def test_client_filenames_are_reduced_to_safe_basenames(
    filename: str,
    expected_name: str,
) -> None:
    with RequestWorkspace() as workspace:
        stored = asyncio.run(
            store_uploads(
                [_upload(filename, b"pdf")],
                workspace=workspace,
                policy=_policy(allowed_extensions=frozenset({".pdf"})),
            )
        )[0]

        assert stored.original_name == expected_name
        assert stored.stored_path.parent == workspace.path
        assert stored.stored_path.name != expected_name
        assert stored.stored_path.suffix == ".pdf"
        assert stored.stored_path.read_bytes() == b"pdf"
        assert stored.content_type == "application/octet-stream"


def test_duplicate_client_names_get_unique_internal_paths() -> None:
    with RequestWorkspace() as workspace:
        stored = asyncio.run(
            store_uploads(
                [_upload("same.pdf", b"first"), _upload("same.pdf", b"second")],
                workspace=workspace,
                policy=_policy(),
            )
        )

        assert stored[0].stored_path != stored[1].stored_path
        assert stored[0].stored_path.read_bytes() == b"first"
        assert stored[1].stored_path.read_bytes() == b"second"


@pytest.mark.parametrize(
    "filename",
    [None, "", "   ", ".", "..", "bad\x00name.pdf", "bad\nname.pdf", f"{'x' * 252}.pdf"],
)
def test_invalid_client_filenames_are_rejected(filename: str | None) -> None:
    with RequestWorkspace() as workspace:
        workspace_path = workspace.path
        with pytest.raises(ApiError) as captured:
            asyncio.run(
                store_uploads(
                    [_upload(filename, b"data")],
                    workspace=workspace,
                    policy=_policy(),
                )
            )

        assert captured.value.status_code == 400
        assert captured.value.code == "invalid_filename"

    assert not workspace_path.exists()


@pytest.mark.parametrize("filename", ["file.pdf", "file.PDF", "file.Pdf"])
def test_extension_policy_is_case_insensitive(filename: str) -> None:
    with RequestWorkspace() as workspace:
        stored = asyncio.run(
            store_uploads(
                [_upload(filename, b"data")],
                workspace=workspace,
                policy=_policy(allowed_extensions=frozenset({".PDF"})),
            )
        )

        assert stored[0].stored_path.suffix == ".pdf"


@pytest.mark.parametrize("filename", ["file.txt", "README"])
def test_unsupported_or_missing_extension_is_rejected(filename: str) -> None:
    with RequestWorkspace() as workspace:
        with pytest.raises(ApiError) as captured:
            asyncio.run(
                store_uploads(
                    [_upload(filename, b"data")],
                    workspace=workspace,
                    policy=_policy(allowed_extensions=frozenset({".pdf"})),
                )
            )

        assert captured.value.status_code == 415
        assert captured.value.code == "unsupported_file_extension"


def test_no_extension_is_allowed_when_policy_has_no_restriction() -> None:
    with RequestWorkspace() as workspace:
        stored = asyncio.run(
            store_uploads(
                [_upload("README", b"data")],
                workspace=workspace,
                policy=_policy(),
            )
        )

        assert stored[0].size_bytes == 4
        assert stored[0].stored_path.suffix == ""


@pytest.mark.parametrize("size", [4, 5])
def test_file_size_limit_accepts_exact_limit_and_rejects_one_byte_over(size: int) -> None:
    workspace_path = None
    with RequestWorkspace() as workspace:
        workspace_path = workspace.path
        if size == 4:
            stored = asyncio.run(
                store_uploads(
                    [_upload("file.bin", b"x" * size)],
                    workspace=workspace,
                    policy=_policy(max_file_bytes=4, max_request_bytes=8),
                )
            )
            assert stored[0].size_bytes == 4
        else:
            with pytest.raises(ApiError) as captured:
                asyncio.run(
                    store_uploads(
                        [_upload("file.bin", b"x" * size)],
                        workspace=workspace,
                        policy=_policy(max_file_bytes=4, max_request_bytes=8),
                    )
                )
            assert captured.value.code == "upload_too_large"

    assert workspace_path is not None
    assert not workspace_path.exists()


@pytest.mark.parametrize("second_size", [3, 4])
def test_aggregate_limit_accepts_exact_limit_and_rejects_one_byte_over(
    second_size: int,
) -> None:
    with RequestWorkspace() as workspace:
        workspace_path = workspace.path
        uploads = [_upload("first.bin", b"a" * 3), _upload("second.bin", b"b" * second_size)]
        if second_size == 3:
            stored = asyncio.run(
                store_uploads(
                    uploads,
                    workspace=workspace,
                    policy=_policy(max_file_bytes=6, max_request_bytes=6),
                )
            )
            assert sum(item.size_bytes for item in stored) == 6
        else:
            with pytest.raises(ApiError) as captured:
                asyncio.run(
                    store_uploads(
                        uploads,
                        workspace=workspace,
                        policy=_policy(max_file_bytes=6, max_request_bytes=6),
                    )
                )
            assert captured.value.code == "upload_request_too_large"

    assert not workspace_path.exists()


class RecordingUpload:
    def __init__(self, content: bytes, filename: str = "recording.bin") -> None:
        self.filename = filename
        self.content_type = "application/octet-stream"
        self._file = BytesIO(content)
        self.requested_sizes: list[int] = []
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        return self._file.read(size)

    async def close(self) -> None:
        self.closed = True
        self._file.close()


def test_uploads_are_read_only_with_bounded_chunk_sizes() -> None:
    recording = RecordingUpload(b"0123456789")

    with RequestWorkspace() as workspace:
        stored = asyncio.run(
            store_uploads(
                [cast(UploadFile, recording)],
                workspace=workspace,
                policy=_policy(chunk_bytes=3),
            )
        )

        assert stored[0].size_bytes == 10
        assert recording.requested_sizes == [3, 3, 3, 3, 3]
        assert recording.closed is True


def test_too_many_files_are_rejected_before_any_reads() -> None:
    first = RecordingUpload(b"first")
    second = RecordingUpload(b"second")

    with RequestWorkspace() as workspace:
        with pytest.raises(ApiError) as captured:
            asyncio.run(
                store_uploads(
                    [cast(UploadFile, first), cast(UploadFile, second)],
                    workspace=workspace,
                    policy=_policy(max_files=1),
                )
            )

        assert captured.value.status_code == 413
        assert captured.value.code == "too_many_files"
        assert first.requested_sizes == []
        assert second.requested_sizes == []
        assert first.closed is True
        assert second.closed is True


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("max_files", 0),
        ("max_file_bytes", -1),
        ("max_request_bytes", True),
        ("chunk_bytes", 0),
    ],
)
def test_upload_policy_rejects_invalid_limits(field_name: str, value: object) -> None:
    arguments = {
        "max_files": 1,
        "max_file_bytes": 2,
        "max_request_bytes": 3,
        "chunk_bytes": 1,
        field_name: value,
    }

    with pytest.raises(ValueError, match="positive integer"):
        UploadPolicy(**arguments)  # type: ignore[arg-type]


def test_upload_policy_rejects_file_limit_above_total_limit() -> None:
    with pytest.raises(ValueError, match="must not exceed"):
        _policy(max_file_bytes=6, max_request_bytes=5)


def test_upload_policy_can_be_built_from_api_settings() -> None:
    settings = ApiSettings(
        max_upload_files=2,
        max_upload_file_bytes=10,
        max_upload_request_bytes=20,
        upload_chunk_bytes=3,
    )

    policy = UploadPolicy.from_settings(settings, allowed_extensions={".PDF"})

    assert policy == UploadPolicy(
        max_files=2,
        max_file_bytes=10,
        max_request_bytes=20,
        chunk_bytes=3,
        allowed_extensions=frozenset({".pdf"}),
    )


@pytest.mark.parametrize("extension", ["pdf", ".", " .pdf", ".pdf ", "../pdf"])
def test_upload_policy_rejects_invalid_allowed_extensions(extension: str) -> None:
    with pytest.raises(ValueError, match="allowed extensions"):
        _policy(allowed_extensions=frozenset({extension}))


def test_stored_upload_is_immutable() -> None:
    stored = StoredUpload(
        original_name="file.bin",
        stored_path=Path("stored.bin"),
        size_bytes=1,
        content_type=None,
    )

    with pytest.raises((AttributeError, TypeError)):
        stored.size_bytes = 2  # type: ignore[misc]

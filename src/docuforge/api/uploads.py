"""Secure streaming upload storage for the DocuForge API adapter."""

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from docuforge.api.config import ApiSettings
from docuforge.api.errors import ApiError
from docuforge.api.workspace import RequestWorkspace

MAX_CLIENT_FILENAME_CHARS = 255


@dataclass(frozen=True, slots=True)
class StoredUpload:
    """Internal metadata for one upload saved inside a request workspace."""

    original_name: str
    stored_path: Path
    size_bytes: int
    content_type: str | None


@dataclass(frozen=True, slots=True)
class UploadPolicy:
    """Limits and optional extension restrictions for one upload workflow."""

    max_files: int
    max_file_bytes: int
    max_request_bytes: int
    chunk_bytes: int
    allowed_extensions: frozenset[str] | None = None

    def __post_init__(self) -> None:
        for field_name in ("max_files", "max_file_bytes", "max_request_bytes", "chunk_bytes"):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.max_file_bytes > self.max_request_bytes:
            raise ValueError("max_file_bytes must not exceed max_request_bytes")

        if self.allowed_extensions is None:
            return

        normalized_extensions = frozenset(
            _normalize_allowed_extension(extension) for extension in self.allowed_extensions
        )
        object.__setattr__(self, "allowed_extensions", normalized_extensions)

    @classmethod
    def from_settings(
        cls,
        settings: ApiSettings,
        *,
        allowed_extensions: AbstractSet[str] | None = None,
    ) -> "UploadPolicy":
        """Build an upload policy from immutable API defaults."""
        return cls(
            max_files=settings.max_upload_files,
            max_file_bytes=settings.max_upload_file_bytes,
            max_request_bytes=settings.max_upload_request_bytes,
            chunk_bytes=settings.upload_chunk_bytes,
            allowed_extensions=(
                None if allowed_extensions is None else frozenset(allowed_extensions)
            ),
        )


def normalize_client_filename(filename: str | None) -> str:
    """Return a safe basename from an untrusted cross-platform client filename."""
    if not isinstance(filename, str) or "\x00" in filename:
        raise _invalid_filename_error()

    basename = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    if (
        basename in {"", ".", ".."}
        or not basename.strip()
        or len(basename) > MAX_CLIENT_FILENAME_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in basename)
    ):
        raise _invalid_filename_error()
    return basename


async def store_uploads(
    uploads: Sequence[UploadFile],
    *,
    workspace: RequestWorkspace,
    policy: UploadPolicy,
) -> tuple[StoredUpload, ...]:
    """Stream uploads into unique workspace files while enforcing policy limits."""
    try:
        if len(uploads) > policy.max_files:
            raise ApiError(
                status_code=413,
                code="too_many_files",
                message="Too many uploaded files.",
            )

        stored_uploads: list[StoredUpload] = []
        request_size = 0
        for upload in uploads:
            original_name = normalize_client_filename(upload.filename)
            suffix = Path(original_name).suffix.lower()
            if policy.allowed_extensions is not None and suffix not in policy.allowed_extensions:
                raise ApiError(
                    status_code=415,
                    code="unsupported_file_extension",
                    message="File extension is not supported.",
                )

            stored_path = workspace.path / f"{uuid4().hex}{suffix}"
            file_size = 0
            try:
                with stored_path.open("xb") as destination:
                    while chunk := await upload.read(policy.chunk_bytes):
                        file_size += len(chunk)
                        if file_size > policy.max_file_bytes:
                            raise ApiError(
                                status_code=413,
                                code="upload_too_large",
                                message="An uploaded file exceeds the allowed size.",
                            )
                        if request_size + len(chunk) > policy.max_request_bytes:
                            raise ApiError(
                                status_code=413,
                                code="upload_request_too_large",
                                message="The combined upload size exceeds the allowed size.",
                            )
                        destination.write(chunk)
                        request_size += len(chunk)
            except BaseException:
                stored_path.unlink(missing_ok=True)
                raise

            stored_uploads.append(
                StoredUpload(
                    original_name=original_name,
                    stored_path=stored_path,
                    size_bytes=file_size,
                    content_type=upload.content_type,
                )
            )

        return tuple(stored_uploads)
    finally:
        for upload in uploads:
            await upload.close()


def _normalize_allowed_extension(extension: str) -> str:
    if (
        not isinstance(extension, str)
        or extension != extension.strip()
        or not extension.startswith(".")
        or len(extension) < 2
        or "/" in extension
        or "\\" in extension
        or "\x00" in extension
    ):
        raise ValueError("allowed extensions must be non-empty suffixes beginning with '.'")
    return extension.lower()


def _invalid_filename_error() -> ApiError:
    return ApiError(
        status_code=400,
        code="invalid_filename",
        message="Upload filename is invalid.",
    )

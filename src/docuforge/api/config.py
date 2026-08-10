"""Configuration for constructing a DocuForge API application."""

from dataclasses import dataclass

from docuforge.version import package_version


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Immutable settings used to build one API application instance."""

    application_name: str = "DocuForge API"
    version: str = package_version()
    environment: str = "local"
    api_prefix: str = "/api/v1"
    docs_enabled: bool = True
    max_upload_files: int = 20
    max_upload_file_bytes: int = 50 * 1024 * 1024
    max_upload_request_bytes: int = 200 * 1024 * 1024
    upload_chunk_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        for field_name in ("application_name", "version", "environment"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must not be blank")

        if not isinstance(self.api_prefix, str) or not self.api_prefix.startswith("/"):
            raise ValueError("api_prefix must begin with '/'")
        if any(character.isspace() for character in self.api_prefix):
            raise ValueError("api_prefix must not contain whitespace")
        if self.api_prefix != "/" and self.api_prefix.endswith("/"):
            raise ValueError("api_prefix must not end with '/' unless it is the root prefix")

        upload_limit_fields = (
            "max_upload_files",
            "max_upload_file_bytes",
            "max_upload_request_bytes",
            "upload_chunk_bytes",
        )
        for field_name in upload_limit_fields:
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")

        if self.max_upload_file_bytes > self.max_upload_request_bytes:
            raise ValueError("max_upload_file_bytes must not exceed max_upload_request_bytes")

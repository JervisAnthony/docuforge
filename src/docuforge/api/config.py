"""Configuration for constructing a DocuForge API application."""

import os
from dataclasses import dataclass

from docuforge.version import package_version


def _environment_bool(name: str, *, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _environment_origins(name: str) -> tuple[str, ...]:
    raw_value = os.getenv(name, "")
    return tuple(origin.strip().rstrip("/") for origin in raw_value.split(",") if origin.strip())


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Immutable settings used to build one API application instance."""

    application_name: str = "DocuForge API"
    version: str = package_version()
    environment: str = "local"
    api_prefix: str = "/api/v1"
    docs_enabled: bool = True
    cors_allowed_origins: tuple[str, ...] = ()
    max_upload_files: int = 20
    max_upload_file_bytes: int = 50 * 1024 * 1024
    max_upload_request_bytes: int = 200 * 1024 * 1024
    upload_chunk_bytes: int = 1024 * 1024
    max_pdf_render_pages: int = 100
    max_pdf_render_pixels_per_page: int = 40_000_000

    @classmethod
    def from_environment(cls) -> "ApiSettings":
        """Build runtime settings from deployment-safe environment variables."""
        return cls(
            environment=os.getenv("DOCUFORGE_ENVIRONMENT", "local").strip() or "local",
            docs_enabled=_environment_bool("DOCUFORGE_DOCS_ENABLED", default=True),
            cors_allowed_origins=_environment_origins("DOCUFORGE_CORS_ALLOWED_ORIGINS"),
        )

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

        if not isinstance(self.cors_allowed_origins, tuple) or any(
            not isinstance(origin, str) or not origin.strip()
            for origin in self.cors_allowed_origins
        ):
            raise ValueError("cors_allowed_origins must contain non-blank strings")
        if any(not origin.startswith(("http://", "https://")) for origin in self.cors_allowed_origins):
            raise ValueError("cors_allowed_origins must contain http(s) origins")

        upload_limit_fields = (
            "max_upload_files",
            "max_upload_file_bytes",
            "max_upload_request_bytes",
            "upload_chunk_bytes",
            "max_pdf_render_pages",
            "max_pdf_render_pixels_per_page",
        )
        for field_name in upload_limit_fields:
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")

        if self.max_upload_file_bytes > self.max_upload_request_bytes:
            raise ValueError("max_upload_file_bytes must not exceed max_upload_request_bytes")

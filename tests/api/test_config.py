from dataclasses import FrozenInstanceError

import pytest

from docuforge.api import ApiSettings
from docuforge.version import package_version


def test_settings_defaults() -> None:
    settings = ApiSettings()

    assert settings.application_name == "DocuForge API"
    assert settings.version == package_version()
    assert settings.environment == "local"
    assert settings.api_prefix == "/api/v1"
    assert settings.docs_enabled is True
    assert settings.max_upload_files == 20
    assert settings.max_upload_file_bytes == 50 * 1024 * 1024
    assert settings.max_upload_request_bytes == 200 * 1024 * 1024
    assert settings.upload_chunk_bytes == 1024 * 1024


def test_settings_accept_custom_values() -> None:
    settings = ApiSettings(
        application_name="Custom API",
        version="2.0.0",
        environment="test",
        api_prefix="/custom/v2",
        docs_enabled=False,
        max_upload_files=3,
        max_upload_file_bytes=100,
        max_upload_request_bytes=250,
        upload_chunk_bytes=10,
    )

    assert settings == ApiSettings(
        application_name="Custom API",
        version="2.0.0",
        environment="test",
        api_prefix="/custom/v2",
        docs_enabled=False,
        max_upload_files=3,
        max_upload_file_bytes=100,
        max_upload_request_bytes=250,
        upload_chunk_bytes=10,
    )


@pytest.mark.parametrize("field_name", ["application_name", "version", "environment"])
@pytest.mark.parametrize("value", ["", "   "])
def test_settings_reject_blank_required_text(field_name: str, value: str) -> None:
    with pytest.raises(ValueError, match=f"{field_name} must not be blank"):
        ApiSettings(**{field_name: value})


@pytest.mark.parametrize(
    ("prefix", "message"),
    [
        ("", "must begin"),
        ("api/v1", "must begin"),
        ("/api /v1", "must not contain whitespace"),
        ("/api/v1/", "must not end"),
    ],
)
def test_settings_reject_invalid_prefix(prefix: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ApiSettings(api_prefix=prefix)


def test_settings_support_root_prefix() -> None:
    assert ApiSettings(api_prefix="/").api_prefix == "/"


def test_settings_are_immutable() -> None:
    settings = ApiSettings()

    with pytest.raises(FrozenInstanceError):
        settings.environment = "production"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field_name",
    [
        "max_upload_files",
        "max_upload_file_bytes",
        "max_upload_request_bytes",
        "upload_chunk_bytes",
    ],
)
@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "1"])
def test_settings_reject_invalid_upload_limits(field_name: str, value: object) -> None:
    with pytest.raises(ValueError, match=f"{field_name} must be a positive integer"):
        ApiSettings(**{field_name: value})  # type: ignore[arg-type]


def test_settings_reject_file_limit_above_request_limit() -> None:
    with pytest.raises(ValueError, match="must not exceed"):
        ApiSettings(max_upload_file_bytes=11, max_upload_request_bytes=10)

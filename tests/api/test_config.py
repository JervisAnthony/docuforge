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


def test_settings_accept_custom_values() -> None:
    settings = ApiSettings(
        application_name="Custom API",
        version="2.0.0",
        environment="test",
        api_prefix="/custom/v2",
        docs_enabled=False,
    )

    assert settings == ApiSettings(
        application_name="Custom API",
        version="2.0.0",
        environment="test",
        api_prefix="/custom/v2",
        docs_enabled=False,
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

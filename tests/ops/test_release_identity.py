import json

import pytest

from docuforge.ops.deployment_smoke import DeploymentSmokeError, HttpResponse
from docuforge.ops.release_identity import verify_release_identity


def _response(version: str) -> HttpResponse:
    payload = {"status": "ready", "service": "docuforge", "version": version}
    return HttpResponse(200, {"content-type": "application/json"}, json.dumps(payload).encode())


def test_release_identity_matches_expected_version() -> None:
    def requester(method, url, *, headers=None, body=None, timeout):
        return _response("0.1.0")

    assert verify_release_identity(
        "https://docuforge.invalid",
        expected_version="0.1.0",
        requester=requester,
    ) == "0.1.0"


def test_release_identity_rejects_version_mismatch() -> None:
    def requester(method, url, *, headers=None, body=None, timeout):
        return _response("0.0.9")

    with pytest.raises(DeploymentSmokeError, match="does not match expected release"):
        verify_release_identity(
            "https://docuforge.invalid",
            expected_version="0.1.0",
            requester=requester,
        )


def test_release_identity_rejects_bad_readiness_state() -> None:
    def requester(method, url, *, headers=None, body=None, timeout):
        payload = {"status": "starting", "service": "docuforge", "version": "0.1.0"}
        return HttpResponse(200, {}, json.dumps(payload).encode())

    with pytest.raises(DeploymentSmokeError, match="unexpected service state"):
        verify_release_identity(
            "https://docuforge.invalid",
            expected_version="0.1.0",
            requester=requester,
        )

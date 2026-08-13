"""Verify that a public DocuForge API is serving the expected release."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlsplit

from docuforge.ops.deployment_smoke import (
    DeploymentSmokeError,
    Requester,
    request_http,
)
from docuforge.version import package_version


def _normalize_api_origin(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parts = urlsplit(candidate)
    if parts.scheme.lower() != "https":
        raise DeploymentSmokeError("API URL must use https")
    if not parts.hostname:
        raise DeploymentSmokeError("API URL must include a hostname")
    if parts.username is not None or parts.password is not None:
        raise DeploymentSmokeError("API URL must not include credentials")
    if parts.query or parts.fragment:
        raise DeploymentSmokeError("API URL must not include a query string or fragment")
    if parts.path not in {"", "/"}:
        raise DeploymentSmokeError("API URL must be an origin without a path")
    return f"https://{parts.netloc}"


def verify_release_identity(
    api_url: str,
    *,
    expected_version: str,
    timeout: float = 15.0,
    requester: Requester = request_http,
) -> str:
    """Return the deployed version when readiness matches the expected release."""
    expected = expected_version.strip()
    if not expected:
        raise DeploymentSmokeError("expected version must not be blank")
    if timeout <= 0:
        raise DeploymentSmokeError("timeout must be greater than zero")

    origin = _normalize_api_origin(api_url)
    response = requester(
        "GET",
        f"{origin}/api/v1/ready",
        headers=None,
        body=None,
        timeout=timeout,
    )
    if response.status_code != 200:
        raise DeploymentSmokeError(
            f"readiness endpoint returned HTTP {response.status_code}, expected 200"
        )

    try:
        payload = json.loads(response.body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise DeploymentSmokeError("readiness endpoint did not return valid JSON") from error
    if not isinstance(payload, dict):
        raise DeploymentSmokeError("readiness endpoint did not return a JSON object")
    if payload.get("status") != "ready" or payload.get("service") != "docuforge":
        raise DeploymentSmokeError("readiness endpoint reported an unexpected service state")

    observed = payload.get("version")
    if not isinstance(observed, str) or not observed:
        raise DeploymentSmokeError("readiness endpoint did not report a version")
    if observed != expected:
        raise DeploymentSmokeError(
            f"deployed version {observed!r} does not match expected release {expected!r}"
        )
    return observed


def build_parser() -> argparse.ArgumentParser:
    """Build the release identity command-line parser."""
    parser = argparse.ArgumentParser(
        description="Verify that the public DocuForge API serves this release.",
    )
    parser.add_argument("--api-url", required=True, help="Public Railway API origin")
    parser.add_argument(
        "--expected-version",
        default=package_version(),
        help="Release version expected from the deployed readiness endpoint",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="Request timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Verify release identity from the command line."""
    arguments = build_parser().parse_args(argv)
    try:
        observed = verify_release_identity(
            arguments.api_url,
            expected_version=arguments.expected_version,
            timeout=arguments.timeout,
        )
    except DeploymentSmokeError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1

    print(f"PASS release-identity version={observed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

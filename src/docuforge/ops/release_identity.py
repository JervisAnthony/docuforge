"""Verify that a public DocuForge API is serving the expected release."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from html.parser import HTMLParser
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from docuforge.build_identity import parse_identity, revision, validate_version
from docuforge.ops.deployment_smoke import (
    DeploymentSmokeError,
    Requester,
    request_http,
)
from docuforge.version import package_version


def _normalize_api_origin(value: str) -> str:
    return normalize_origin(value, label="API")


def normalize_origin(value: str, *, label: str) -> str:
    """Validate before urlsplit can strip control characters or ambiguous input."""
    if not isinstance(value, str) or re.search(r"[^\x21-\x7e]", value):
        raise DeploymentSmokeError(f"{label} URL contains invalid characters")
    try:
        parts = urlsplit(value)
        port = parts.port
        hostname = parts.hostname
    except ValueError:
        raise DeploymentSmokeError(f"{label} URL is invalid") from None
    if parts.scheme.lower() != "https":
        raise DeploymentSmokeError(f"{label} URL must use https")
    if not hostname or len(hostname) > 253:
        raise DeploymentSmokeError(f"{label} URL must include a valid hostname")
    if ":" in hostname:
        try:
            ip_address(hostname)
        except ValueError:
            raise DeploymentSmokeError(f"{label} URL must include a valid hostname") from None
    elif not all(
        re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", part)
        for part in hostname.rstrip(".").split(".")
    ):
        raise DeploymentSmokeError(f"{label} URL must include a valid hostname")
    if port == 0 or parts.netloc.endswith(":"):
        raise DeploymentSmokeError(f"{label} URL has an invalid port")
    if parts.username is not None or parts.password is not None:
        raise DeploymentSmokeError(f"{label} URL must not include credentials")
    if "?" in value or "#" in value:
        raise DeploymentSmokeError(f"{label} URL must not include a query string or fragment")
    if parts.path not in {"", "/"}:
        raise DeploymentSmokeError(f"{label} URL must be an origin without a path")
    return f"https://{parts.netloc}"


class BuildVerificationError(DeploymentSmokeError):
    """A safe diagnostic together with partial, validated identity evidence."""

    def __init__(self, message: str, report: dict):
        super().__init__(message)
        report["diagnostic"] = message
        self.report = report


class _IdentityHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values: dict[str, list[str | None]] = {}
        self.in_head = False

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        if tag != "meta":
            return
        names = [value for key, value in attrs if key == "name"]
        if not any(name in {"docuforge-version", "docuforge-revision"} for name in names):
            return
        if not self.in_head or len(dict(attrs)) != len(attrs):
            raise ValueError("invalid identity meta tag")
        attributes = dict(attrs)
        self.values.setdefault(attributes["name"], []).append(attributes.get("content"))

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


def validate_frontend_html(body: bytes, manifest: dict) -> None:
    """Require exactly one matching version/revision tag in the document head."""
    parser = _IdentityHTML()
    try:
        parser.feed(body.decode("utf-8"))
        parser.close()
        expected = {
            "docuforge-version": [manifest["version"]],
            "docuforge-revision": [manifest["revision"] or "unknown"],
        }
        if parser.values != expected:
            raise ValueError("missing, duplicate or inconsistent identity tags")
    except (ValueError, UnicodeError, RecursionError):
        raise DeploymentSmokeError(
            "frontend HTML identity tags are missing or inconsistent"
        ) from None


def verify_deployed_builds(
    api_url: str,
    *,
    frontend_url: str,
    expected_api_revision: str,
    expected_frontend_revision: str,
    expected_version: str,
    timeout: float = 15.0,
    requester: Requester = request_http,
) -> dict:
    """Verify independently chosen API/frontend revisions and HTML consistency.

    On failure, the exception carries the same report schema with validated partial
    evidence. Invalid configuration never initiates network requests.
    """
    report = {"schema_version": 1, "mode": "strict", "result": "FAIL", "components": {}}
    field = "expected version"
    try:
        version = validate_version(expected_version)
        field = "API origin"
        api_origin = normalize_origin(api_url, label="API")
        field = "frontend origin"
        frontend_origin = normalize_origin(frontend_url, label="frontend")
        field = "API expected revision"
        api_revision = revision(expected_api_revision)
        field = "frontend expected revision"
        frontend_revision = revision(expected_frontend_revision)
        field = "timeout"
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("invalid timeout")
    except (ValueError, DeploymentSmokeError, TypeError):
        raise BuildVerificationError(
            f"{field}: invalid strict identity configuration", report
        ) from None
    report["expected_version"] = version
    for name, origin, expected in (
        ("api", api_origin, api_revision),
        ("frontend", frontend_origin, frontend_revision),
    ):
        report["components"][name] = {
            "origin": origin,
            "expected_revision": expected,
            "outcome": "FAIL",
        }

    def fetch(url: str, *, html=False):
        try:
            response = requester(
                "GET",
                url,
                headers={
                    "Cache-Control": "no-cache, no-store",
                    "Pragma": "no-cache",
                    "Accept": "text/html" if html else "application/json",
                },
                body=None,
                timeout=timeout,
            )
        except (DeploymentSmokeError, OSError, ValueError):
            raise DeploymentSmokeError("identity endpoint unavailable") from None
        if response.status_code != 200:
            raise DeploymentSmokeError("identity endpoint did not return HTTP 200")
        media_type = (
            next(
                (value for key, value in response.headers.items() if key.lower() == "content-type"),
                "",
            )
            .split(";", 1)[0]
            .strip()
            .lower()
        )
        if media_type != ("text/html" if html else "application/json"):
            raise DeploymentSmokeError("identity endpoint returned an unexpected media type")
        if len(response.body) > (1024 * 1024 if html else 4096):
            raise DeploymentSmokeError("identity endpoint response exceeds size limit")
        return response.body

    for name, path, service in (
        ("api", "/api/v1/build", "docuforge"),
        ("frontend", "/build-info.json", "docuforge-frontend"),
    ):
        component = report["components"][name]
        try:
            if name == "api":
                try:
                    ready = json.loads(fetch(api_origin + "/api/v1/ready"))
                except (ValueError, UnicodeError, RecursionError):
                    raise DeploymentSmokeError("readiness returned invalid JSON") from None
                if (
                    not isinstance(ready, dict)
                    or ready.get("status") != "ready"
                    or ready.get("service") != "docuforge"
                    or ready.get("version") != version
                ):
                    raise DeploymentSmokeError("readiness service/version verification failed")
            data = fetch(component["origin"] + path)
            try:
                stamp = parse_identity(data, service=service)
            except ValueError:
                raise DeploymentSmokeError("invalid build identity contract") from None
            component["observed_version"] = stamp["version"]
            component["observed_revision"] = stamp["revision"]
            if stamp["version"] != version:
                raise DeploymentSmokeError("build version does not match expected release")
            if stamp["revision"] is None:
                raise DeploymentSmokeError("build revision is unknown")
            if stamp["revision"] != component["expected_revision"]:
                raise DeploymentSmokeError("build revision does not match expected revision")
            if name == "frontend":
                validate_frontend_html(fetch(frontend_origin + "/", html=True), stamp)
            component["outcome"] = "PASS"
        except DeploymentSmokeError as error:
            component["diagnostic"] = str(error)
    failures = [name for name, item in report["components"].items() if item["outcome"] != "PASS"]
    if failures:
        diagnostics = "; ".join(
            f"{name}: {report['components'][name]['diagnostic']}" for name in failures
        )
        raise BuildVerificationError(diagnostics, report)
    report["result"] = "PASS"
    return report


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
    try:
        validate_version(expected)
    except ValueError:
        raise DeploymentSmokeError("expected version is invalid") from None
    if not math.isfinite(timeout) or timeout <= 0:
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
    try:
        validate_version(observed)
    except ValueError:
        raise DeploymentSmokeError("readiness endpoint did not report a valid version") from None
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
    parser.add_argument("--frontend-url", help="Public Vercel frontend origin")
    parser.add_argument("--expected-api-revision", help="Independently expected full API Git SHA")
    parser.add_argument(
        "--expected-frontend-revision", help="Independently expected full frontend Git SHA"
    )
    parser.add_argument(
        "--report-json", type=Path, help="Write safe identity evidence on success or failure"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Verify release identity from the command line."""
    arguments = build_parser().parse_args(argv)
    strict = any(
        value is not None
        for value in (
            arguments.expected_api_revision,
            arguments.expected_frontend_revision,
            arguments.frontend_url,
        )
    )
    report = {
        "schema_version": 1,
        "mode": "strict" if strict else "semantic-only",
        "result": "FAIL",
    }
    try:
        if strict:
            if any(
                value is None
                for value in (
                    arguments.expected_api_revision,
                    arguments.expected_frontend_revision,
                    arguments.frontend_url,
                )
            ):
                raise DeploymentSmokeError(
                    "strict mode requires both revisions and frontend origin"
                )
            report = verify_deployed_builds(
                arguments.api_url,
                frontend_url=arguments.frontend_url,
                expected_api_revision=arguments.expected_api_revision,
                expected_frontend_revision=arguments.expected_frontend_revision,
                expected_version=arguments.expected_version,
                timeout=arguments.timeout,
            )
        else:
            observed = verify_release_identity(
                arguments.api_url,
                expected_version=arguments.expected_version,
                timeout=arguments.timeout,
            )
            report.update(result="PASS", observed_version=validate_version(observed))
    except DeploymentSmokeError as error:
        if isinstance(error, BuildVerificationError):
            report = error.report
        print(f"FAIL {error}", file=sys.stderr)
    except ValueError:
        print("FAIL invalid version metadata", file=sys.stderr)
    finally:
        if arguments.report_json:
            arguments.report_json.write_text(
                json.dumps(report, sort_keys=True) + "\n", encoding="utf-8"
            )
    if report["result"] != "PASS":
        return 1
    print(
        "PASS deployed-build-identity"
        if strict
        else f"PASS semantic-version-only version={observed}; revisions NOT verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

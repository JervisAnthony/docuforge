"""Verify a public DocuForge deployment with synthetic, non-sensitive fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from PIL import Image
from pypdf import PdfReader, PdfWriter


class DeploymentSmokeError(RuntimeError):
    """Raised when a production deployment smoke check fails."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Minimal HTTP response used by the deployment verifier."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes


class Requester(Protocol):
    """Transport contract used by the deployment verifier."""

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float,
    ) -> HttpResponse: ...


def request_http(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout: float,
) -> HttpResponse:
    """Perform one smoke-test HTTP request with the Python standard library."""
    request = Request(url, data=body, headers=dict(headers or {}), method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status_code=response.status,
                headers={name.lower(): value for name, value in response.headers.items()},
                body=response.read(),
            )
    except HTTPError as error:
        return HttpResponse(
            status_code=error.code,
            headers={name.lower(): value for name, value in error.headers.items()},
            body=error.read(),
        )
    except URLError as error:
        raise DeploymentSmokeError(f"request to {url} failed: {error.reason}") from error


def _normalize_public_url(value: str, *, label: str) -> str:
    candidate = value.strip().rstrip("/")
    parts = urlsplit(candidate)
    if parts.scheme.lower() != "https":
        raise DeploymentSmokeError(f"{label} must use https")
    if not parts.hostname:
        raise DeploymentSmokeError(f"{label} must include a hostname")
    if parts.username is not None or parts.password is not None:
        raise DeploymentSmokeError(f"{label} must not include credentials")
    if parts.query or parts.fragment:
        raise DeploymentSmokeError(f"{label} must not include a query string or fragment")
    if parts.path not in {"", "/"}:
        raise DeploymentSmokeError(f"{label} must be an origin without a path")
    return f"https://{parts.netloc}"


def _header(response: HttpResponse, name: str) -> str | None:
    expected = name.lower()
    for header_name, value in response.headers.items():
        if header_name.lower() == expected:
            return value
    return None


def _require_status(response: HttpResponse, *, label: str) -> None:
    if response.status_code != 200:
        raise DeploymentSmokeError(f"{label} returned HTTP {response.status_code}, expected 200")


def _json_object(response: HttpResponse, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(response.body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise DeploymentSmokeError(f"{label} did not return valid JSON") from error
    if not isinstance(payload, dict):
        raise DeploymentSmokeError(f"{label} did not return a JSON object")
    return payload


def _make_pdf(*widths: int) -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=120)
    writer.write(buffer)
    return buffer.getvalue()


def _make_png() -> bytes:
    buffer = BytesIO()
    image = Image.new("RGB", (96, 64), (42, 106, 174))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _multipart_body(
    *,
    fields: tuple[tuple[str, str], ...] = (),
    files: tuple[tuple[str, str, bytes, str], ...] = (),
) -> tuple[bytes, str]:
    boundary = f"docuforge-{uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in fields:
        chunks.extend(
            (
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            )
        )

    for name, filename, payload, content_type in files:
        chunks.extend(
            (
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                payload,
                b"\r\n",
            )
        )

    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class ProductionSmokeRunner:
    """Run the public MVP1 deployment verification contract."""

    def __init__(
        self,
        *,
        frontend_url: str,
        api_url: str,
        timeout: float = 15.0,
        requester: Requester = request_http,
    ) -> None:
        if timeout <= 0:
            raise DeploymentSmokeError("timeout must be greater than zero")
        self.frontend_url = _normalize_public_url(frontend_url, label="frontend URL")
        self.api_url = _normalize_public_url(api_url, label="API URL")
        self.timeout = timeout
        self._requester = requester

    def run(self) -> tuple[str, ...]:
        """Run all production checks and return their stable names on success."""
        checks = (
            ("frontend", self._check_frontend),
            ("readiness", self._check_readiness),
            ("liveness-and-headers", self._check_liveness_and_headers),
            ("cors", self._check_cors),
            ("pdf-merge", self._check_pdf_merge),
            ("image-compression", self._check_image_compression),
        )
        passed: list[str] = []
        for name, check in checks:
            check()
            passed.append(name)
        return tuple(passed)

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResponse:
        return self._requester(
            method,
            url,
            headers=headers,
            body=body,
            timeout=self.timeout,
        )

    def _api_endpoint(self, path: str) -> str:
        return f"{self.api_url}{path}"

    def _check_frontend(self) -> None:
        response = self._request("GET", self.frontend_url)
        _require_status(response, label="frontend")
        content_type = _header(response, "Content-Type") or ""
        if "text/html" not in content_type.lower():
            raise DeploymentSmokeError("frontend did not return HTML")
        if b"DocuForge" not in response.body:
            raise DeploymentSmokeError("frontend HTML did not identify DocuForge")

    def _check_readiness(self) -> None:
        response = self._request("GET", self._api_endpoint("/api/v1/ready"))
        _require_status(response, label="readiness endpoint")
        payload = _json_object(response, label="readiness endpoint")
        if payload.get("status") != "ready" or payload.get("service") != "docuforge":
            raise DeploymentSmokeError("readiness endpoint reported an unexpected service state")
        if not isinstance(payload.get("version"), str) or not payload["version"]:
            raise DeploymentSmokeError("readiness endpoint did not report a version")

    def _check_liveness_and_headers(self) -> None:
        response = self._request(
            "GET",
            self._api_endpoint("/api/v1/health"),
            headers={"Origin": self.frontend_url},
        )
        _require_status(response, label="liveness endpoint")
        payload = _json_object(response, label="liveness endpoint")
        if payload.get("status") != "ok" or payload.get("service") != "docuforge":
            raise DeploymentSmokeError("liveness endpoint reported an unexpected service state")

        expected_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Strict-Transport-Security": "max-age=31536000",
        }
        for name, expected_value in expected_headers.items():
            if _header(response, name) != expected_value:
                raise DeploymentSmokeError(f"liveness response has an invalid {name} header")

        if not _header(response, "X-Request-ID"):
            raise DeploymentSmokeError("liveness response did not include X-Request-ID")
        if _header(response, "Access-Control-Allow-Origin") != self.frontend_url:
            raise DeploymentSmokeError("frontend origin was not allowed by API CORS")
        exposed = _header(response, "Access-Control-Expose-Headers") or ""
        if "x-request-id" not in {part.strip().lower() for part in exposed.split(",")}:
            raise DeploymentSmokeError("API CORS did not expose X-Request-ID")

    def _check_cors(self) -> None:
        response = self._request(
            "OPTIONS",
            self._api_endpoint("/api/v1/health"),
            headers={
                "Origin": self.frontend_url,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Request-ID",
            },
        )
        _require_status(response, label="CORS preflight")
        if _header(response, "Access-Control-Allow-Origin") != self.frontend_url:
            raise DeploymentSmokeError("CORS preflight did not allow the frontend origin")
        allowed_headers = _header(response, "Access-Control-Allow-Headers") or ""
        if "x-request-id" not in {
            part.strip().lower() for part in allowed_headers.split(",")
        }:
            raise DeploymentSmokeError("CORS preflight did not allow X-Request-ID")

    def _check_pdf_merge(self) -> None:
        body, content_type = _multipart_body(
            files=(
                ("files", "one.pdf", _make_pdf(100), "application/pdf"),
                ("files", "two.pdf", _make_pdf(200), "application/pdf"),
            )
        )
        response = self._request(
            "POST",
            self._api_endpoint("/api/v1/pdf/merge"),
            headers={"Content-Type": content_type},
            body=body,
        )
        _require_status(response, label="PDF merge workflow")
        try:
            reader = PdfReader(BytesIO(response.body), strict=True)
            widths = [round(float(page.mediabox.width)) for page in reader.pages]
        except Exception as error:
            raise DeploymentSmokeError("PDF merge workflow returned an invalid PDF") from error
        if widths != [100, 200]:
            raise DeploymentSmokeError("PDF merge workflow did not preserve fixture page order")

    def _check_image_compression(self) -> None:
        body, content_type = _multipart_body(
            fields=(("format", "jpeg"), ("quality", "55")),
            files=(("file", "source.png", _make_png(), "image/png"),),
        )
        response = self._request(
            "POST",
            self._api_endpoint("/api/v1/images/compress"),
            headers={"Content-Type": content_type},
            body=body,
        )
        _require_status(response, label="image compression workflow")
        try:
            with Image.open(BytesIO(response.body)) as image:
                image.load()
                image_format = image.format
                image_size = image.size
        except Exception as error:
            raise DeploymentSmokeError(
                "image compression workflow returned an invalid image"
            ) from error
        if image_format != "JPEG" or image_size != (96, 64):
            raise DeploymentSmokeError(
                "image compression workflow returned unexpected output semantics"
            )


def build_parser() -> argparse.ArgumentParser:
    """Build the production smoke command-line parser."""
    parser = argparse.ArgumentParser(
        description="Verify a public DocuForge Vercel + Railway deployment.",
    )
    parser.add_argument("--frontend-url", required=True, help="Public Vercel frontend origin")
    parser.add_argument("--api-url", required=True, help="Public Railway API origin")
    parser.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run production deployment verification from the command line."""
    arguments = build_parser().parse_args(argv)
    try:
        checks = ProductionSmokeRunner(
            frontend_url=arguments.frontend_url,
            api_url=arguments.api_url,
            timeout=arguments.timeout,
        ).run()
    except DeploymentSmokeError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1

    for check in checks:
        print(f"PASS {check}")
    print(f"Production smoke passed: {len(checks)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

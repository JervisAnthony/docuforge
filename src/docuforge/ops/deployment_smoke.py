"""Verify a public DocuForge deployment with synthetic, non-sensitive fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4
from zipfile import ZipFile

from PIL import Image
from pypdf import PdfReader, PdfWriter

from docuforge.ops.runtime_smoke import make_synthetic_docx, make_synthetic_ocr_png

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 2 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 6 * 1024 * 1024

SMOKE_CHECKS = (
    "frontend",
    "readiness",
    "runtime-capabilities",
    "liveness-and-headers",
    "cors",
    "pdf-merge",
    "pdf-split",
    "pdf-rotate",
    "pdf-remove-pages",
    "pdf-extract-pages",
    "pdf-to-images",
    "image-convert",
    "image-resize",
    "image-compression",
    "images-to-pdf",
    "office-docx-to-pdf",
    "ocr-image-to-text",
)


def _bounded_response_read(response) -> bytes:
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise DeploymentSmokeError("response exceeds smoke size limit")
    return body


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
                body=_bounded_response_read(response),
            )
    except HTTPError as error:
        with error:
            return HttpResponse(
                status_code=error.code,
                headers={name.lower(): value for name, value in error.headers.items()},
                body=_bounded_response_read(error),
            )
    except URLError as error:
        raise DeploymentSmokeError("HTTP transport failed") from error


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


def _make_png(size: tuple[int, int] = (96, 64)) -> bytes:
    buffer = BytesIO()
    image = Image.new("RGB", size, (42, 106, 174))
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
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                payload,
                b"\r\n",
            )
        )

    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _download(response: HttpResponse, media_type: str) -> None:
    _require_status(response, label="download")
    if (_header(response, "Content-Type") or "").split(";")[0].strip().lower() != media_type:
        raise DeploymentSmokeError(f"incorrect media type; expected {media_type}")
    # Check naming when supplied; some proxies may omit Content-Disposition.
    disposition = _header(response, "Content-Disposition")
    if disposition is not None:
        from email.message import Message

        message = Message()
        message["Content-Disposition"] = disposition
        name = message.get_filename()
        if message.get_content_disposition() != "attachment" or not name or not _safe_name(name):
            raise DeploymentSmokeError("unsafe download filename")


def _safe_name(name: str) -> bool:
    return (
        bool(name)
        and not any(c in name for c in "/\\:")
        and name not in {".", ".."}
        and all(ord(c) >= 32 and ord(c) != 127 for c in name)
    )


def _pdf_pages(payload: bytes):
    try:
        reader = PdfReader(BytesIO(payload), strict=True)
        if reader.is_encrypted or not reader.pages:
            raise ValueError
        return list(reader.pages)
    except Exception as error:
        raise DeploymentSmokeError("invalid PDF") from error


def _pdf_order(payload: bytes, expected: tuple[int, ...], rotations=None) -> None:
    pages = _pdf_pages(payload)
    if [float(page.mediabox.width) for page in pages] != list(expected):
        raise DeploymentSmokeError("unexpected page order")
    if rotations is not None and [page.rotation for page in pages] != list(rotations):
        raise DeploymentSmokeError("incorrect page rotations")


def _image(payload: bytes, expected_format: str, size: tuple[int, int]) -> None:
    try:
        with Image.open(BytesIO(payload)) as image:
            if image.format != expected_format:
                raise DeploymentSmokeError("incorrect image format")
            if image.size != size:
                raise DeploymentSmokeError("incorrect output dimensions")
            image.load()
    except DeploymentSmokeError:
        raise
    except Exception as error:
        raise DeploymentSmokeError("invalid image") from error


def _zip_members(payload: bytes, expected: tuple[str, ...]) -> tuple[bytes, ...]:
    try:
        with ZipFile(BytesIO(payload)) as archive:
            members = archive.infolist()
            if any(
                not _safe_name(member.filename) or member.is_dir() or member.flag_bits & 1
                for member in members
            ):
                raise DeploymentSmokeError("unsafe ZIP member")
            if tuple(member.filename for member in members) != expected:
                raise DeploymentSmokeError("unexpected ZIP member order")
            if any(member.file_size > MAX_ZIP_MEMBER_BYTES for member in members):
                raise DeploymentSmokeError("ZIP member exceeds smoke size limit")
            if sum(member.file_size for member in members) > MAX_ZIP_TOTAL_BYTES:
                raise DeploymentSmokeError("ZIP total exceeds smoke size limit")
            contents = []
            for member in members:
                with archive.open(member) as stream:
                    data = stream.read(MAX_ZIP_MEMBER_BYTES + 1)
                    if len(data) > MAX_ZIP_MEMBER_BYTES or len(data) != member.file_size:
                        raise DeploymentSmokeError("ZIP member exceeds smoke size limit")
                    # Reading through EOF verifies CRC without an unbounded testzip() pass.
                    if stream.read(1):
                        raise DeploymentSmokeError("ZIP member exceeds smoke size limit")
                    contents.append(data)
            return tuple(contents)
    except DeploymentSmokeError:
        raise
    except Exception as error:
        raise DeploymentSmokeError("invalid ZIP or CRC") from error


class ProductionSmokeRunner:
    """Run the public MVP1 deployment verification contract."""

    def __init__(
        self,
        *,
        frontend_url: str,
        api_url: str,
        timeout: float = 45.0,
        requester: Requester = request_http,
    ) -> None:
        if timeout <= 0:
            raise DeploymentSmokeError("timeout must be greater than zero")
        self.frontend_url = _normalize_public_url(frontend_url, label="frontend URL")
        self.api_url = _normalize_public_url(api_url, label="API URL")
        self.timeout = timeout
        self._requester = requester
        self.passed_checks: list[str] = []

    def run(self) -> tuple[str, ...]:
        """Run all production checks and return their stable names on success."""
        self.passed_checks.clear()
        for name in SMOKE_CHECKS:
            try:
                getattr(self, f"_check_{name.replace('-', '_')}")()
            except DeploymentSmokeError as error:
                raise DeploymentSmokeError(f"{name}: {error}") from error
            except Exception as error:
                raise DeploymentSmokeError(
                    f"{name}: invalid response or transport failure"
                ) from error
            self.passed_checks.append(name)
        return tuple(self.passed_checks)

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResponse:
        response = self._requester(
            method,
            url,
            headers=headers,
            body=body,
            timeout=self.timeout,
        )
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise DeploymentSmokeError("response exceeds smoke size limit")
        return response

    def _post(self, path: str, *, fields=(), files=()) -> HttpResponse:
        body, content_type = _multipart_body(fields=fields, files=files)
        return self._request(
            "POST",
            self._api_endpoint(path),
            headers={"Content-Type": content_type},
            body=body,
        )

    def _pdf_operation(self, operation: str, *, fields=(), media_type="application/pdf"):
        response = self._post(
            f"/api/v1/pdf/{operation}",
            fields=fields,
            files=(("file", "report.pdf", _make_pdf(100, 200, 300), "application/pdf"),),
        )
        _download(response, media_type)
        return response.body

    def _check_pdf_split(self) -> None:
        payload = self._pdf_operation("split", media_type="application/zip")
        names = tuple(f"report-page-{number:04d}.pdf" for number in range(1, 4))
        for member, width in zip(_zip_members(payload, names), (100, 200, 300), strict=True):
            _pdf_order(member, (width,))

    def _check_pdf_rotate(self) -> None:
        payload = self._pdf_operation("rotate", fields=(("rotate", "1:90"), ("rotate", "2:180")))
        _pdf_order(payload, (100, 200, 300), (90, 180, 0))

    def _check_pdf_remove_pages(self) -> None:
        payload = self._pdf_operation("remove-pages", fields=(("page", "2"),))
        _pdf_order(payload, (100, 300))

    def _check_pdf_extract_pages(self) -> None:
        payload = self._pdf_operation("extract-pages", fields=(("page", "3"), ("page", "1")))
        _pdf_order(payload, (300, 100))

    def _check_pdf_to_images(self) -> None:
        payload = self._pdf_operation(
            "to-images",
            fields=(("format", "png"), ("dpi", "72")),
            media_type="application/zip",
        )
        names = tuple(f"report-page-{number:04d}.png" for number in range(1, 4))
        for member, width in zip(_zip_members(payload, names), (100, 200, 300), strict=True):
            _image(member, "PNG", (width, 120))

    def _check_image_convert(self) -> None:
        response = self._post(
            "/api/v1/images/convert",
            fields=(("format", "jpeg"),),
            files=(("file", "source.png", _make_png(), "image/png"),),
        )
        _download(response, "image/jpeg")
        _image(response.body, "JPEG", (96, 64))

    def _check_image_resize(self) -> None:
        response = self._post(
            "/api/v1/images/resize",
            fields=(("format", "png"), ("max_width", "48")),
            files=(("file", "source.png", _make_png(), "image/png"),),
        )
        _download(response, "image/png")
        _image(response.body, "PNG", (48, 32))

    def _check_images_to_pdf(self) -> None:
        response = self._post(
            "/api/v1/images/to-pdf",
            files=(
                ("files", "landscape.png", _make_png(), "image/png"),
                ("files", "portrait.png", _make_png((40, 80)), "image/png"),
            ),
        )
        _download(response, "application/pdf")
        pages = _pdf_pages(response.body)
        if len(pages) != 2 or not (
            pages[0].mediabox.width > pages[0].mediabox.height
            and pages[1].mediabox.width < pages[1].mediabox.height
        ):
            raise DeploymentSmokeError("incorrect page orientation or order")

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

    def _check_runtime_capabilities(self) -> None:
        response = self._request("GET", self._api_endpoint("/api/v1/capabilities"))
        _require_status(response, label="runtime capabilities endpoint")
        payload = _json_object(response, label="runtime capabilities endpoint")
        for name in ("office_to_pdf", "ocr"):
            capability = payload.get(name)
            if not isinstance(capability, dict) or capability.get("available") is not True:
                raise DeploymentSmokeError(f"runtime capability {name} is unavailable")

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
        if "x-request-id" not in {part.strip().lower() for part in allowed_headers.split(",")}:
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
        _download(response, "application/pdf")
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
        _download(response, "image/jpeg")
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

    def _check_office_docx_to_pdf(self) -> None:
        body, content_type = _multipart_body(
            files=(
                (
                    "file",
                    "runtime-smoke.docx",
                    make_synthetic_docx(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            )
        )
        response = self._request(
            "POST",
            self._api_endpoint("/api/v1/office/docx-to-pdf"),
            headers={"Content-Type": content_type},
            body=body,
        )
        _require_status(response, label="Office DOCX-to-PDF workflow")
        _download(response, "application/pdf")
        if "application/pdf" not in (_header(response, "Content-Type") or "").lower():
            raise DeploymentSmokeError("Office workflow did not return application/pdf")
        if not response.body.startswith(b"%PDF-"):
            raise DeploymentSmokeError("Office workflow returned an invalid PDF")
        try:
            reader = PdfReader(BytesIO(response.body), strict=True)
            if not reader.pages:
                raise ValueError
        except Exception as error:
            raise DeploymentSmokeError("Office workflow returned an invalid PDF") from error

    def _check_ocr_image_to_text(self) -> None:
        body, content_type = _multipart_body(
            files=(("file", "runtime-smoke.png", make_synthetic_ocr_png(), "image/png"),)
        )
        response = self._request(
            "POST",
            self._api_endpoint("/api/v1/ocr/image-to-text"),
            headers={"Content-Type": content_type},
            body=body,
        )
        _require_status(response, label="OCR image-to-text workflow")
        _download(response, "text/plain")
        if "text/plain" not in (_header(response, "Content-Type") or "").lower():
            raise DeploymentSmokeError("OCR workflow did not return text/plain")
        try:
            response.body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DeploymentSmokeError("OCR workflow did not return valid UTF-8") from error


def build_parser() -> argparse.ArgumentParser:
    """Build the production smoke command-line parser."""
    parser = argparse.ArgumentParser(
        description="Verify a public DocuForge Vercel + Railway deployment.",
    )
    parser.add_argument("--frontend-url", required=True, help="Public Vercel frontend origin")
    parser.add_argument("--api-url", required=True, help="Public Railway API origin")
    parser.add_argument(
        "--timeout", type=float, default=45.0, help="Per-request timeout in seconds"
    )
    parser.add_argument(
        "--report-json", type=Path, help="Write safe check evidence for a job summary"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run production deployment verification from the command line."""
    arguments = build_parser().parse_args(argv)
    runner = None
    failure = None
    success = False
    try:
        runner = ProductionSmokeRunner(
            frontend_url=arguments.frontend_url,
            api_url=arguments.api_url,
            timeout=arguments.timeout,
        )
        checks = runner.run()
        success = checks == SMOKE_CHECKS
    except DeploymentSmokeError as error:
        failure = str(error)
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    finally:
        if arguments.report_json:
            passed = runner.passed_checks if runner else []
            arguments.report_json.write_text(
                json.dumps(
                    {
                        "result": "PASS" if success else "FAIL",
                        "passed_checks": passed,
                        "checks_executed": len(passed) + (1 if failure and runner else 0),
                        "expected_count": len(SMOKE_CHECKS),
                    }
                ),
                encoding="utf-8",
            )

    for check in checks:
        print(f"PASS {check}")
    print(f"Production smoke passed: {len(checks)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

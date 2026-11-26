"""Four sequential synthetic batch lifecycles, with owned-session cleanup.

The public CLI verifies independently supplied deployment identity before mutation.
The injected lifecycle core makes no claim about public frontend identity.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import math
import re
import sys
import time
from dataclasses import dataclass
from functools import cache
from io import BytesIO
from pathlib import Path
from uuid import UUID

from PIL import Image, ImageDraw

from docuforge.build_identity import revision, validate_version
from docuforge.ops.batch_transport import request_batch_http
from docuforge.ops.deployment_smoke import (
    MAX_RESPONSE_BYTES,
    _download,
    _header,
    _image,
    _multipart_body,
    _page_text,
    _pdf_pages,
    _require_marker,
    _zip_members,
)
from docuforge.ops.release_identity import normalize_origin, verify_deployed_builds
from docuforge.ops.runtime_smoke import make_synthetic_docx
from docuforge.ops.smoke_fixtures import (
    PPTX_MARKER,
    XLSX_MARKER,
    make_synthetic_pptx,
    make_synthetic_xlsx,
)

BATCH_CHECKS = (
    "batch-image-convert",
    "batch-image-resize",
    "batch-image-compress",
    "batch-office-to-pdf",
)
TOKEN_HEADER = "X-DocuForge-Batch-Token"
PREFIX = "/api/v1/batches/"
CREATION_PATHS = {
    PREFIX + route
    for route in ("images/convert", "images/resize", "images/compress", "office/to-pdf")
}
STAGES = {
    "skipped",
    "configuration",
    "identity",
    "acceptance",
    "access",
    "polling",
    "download",
    "cleanup",
    "complete",
}
CODES = {
    "none",
    "configuration_invalid",
    "identity_failed",
    "transport_failed",
    "redirect_refused",
    "response_too_large",
    "deadline_exceeded",
    "poll_limit",
    "acceptance_invalid",
    "creation_uncertain",
    "snapshot_invalid",
    "access_invalid",
    "output_invalid",
    "execution_failed",
    "capacity_unavailable",
    "storage_unavailable",
    "engine_unavailable",
    "http_failed",
    "cleanup_failed",
    "unexpected_failure",
}


class Failure(Exception):
    """Only fixed, nonprivate failure codes cross the reporting boundary."""

    def __init__(self, code):
        super().__init__(code if code in CODES else "unexpected_failure")


def require(condition, code):
    if not condition:
        raise Failure(code)


@dataclass(frozen=True)
class Timing:
    timeout: float = 20
    case_seconds: float = 120
    suite_seconds: float = 600
    cleanup_seconds: float = 60
    poll_interval: float = 0.5
    max_polls: int = 240

    def validate(self):
        for value, minimum, maximum in (
            (self.timeout, 0, 60),
            (self.case_seconds, 0, 300),
            (self.suite_seconds, 0, 1200),
            (self.cleanup_seconds, 0, 120),
            (self.poll_interval, 0.009, 5),
        ):
            require(
                type(value) in {int, float} and math.isfinite(value) and minimum < value <= maximum,
                "configuration_invalid",
            )
        require(
            type(self.max_polls) is int and 1 <= self.max_polls <= 1000, "configuration_invalid"
        )


DEFAULT_TIMING = Timing()


@contextlib.contextmanager
def quiet_validation():
    """Third-party parsers may otherwise print bytes from untrusted documents."""
    previous = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with contextlib.redirect_stdout(BytesSink()), contextlib.redirect_stderr(BytesSink()):
            yield
    finally:
        logging.disable(previous)


class BytesSink:
    def write(self, text):
        return len(text)

    def flush(self):
        pass


@dataclass(frozen=True)
class Case:
    name: str
    route: str
    operation: str
    fields: tuple
    files: tuple
    outputs: tuple
    dimensions: tuple = ()
    markers: tuple = ()


@cache
def cases():
    """Share immutable fixtures, including the DOCX builder's timestamped bytes."""
    files = []
    for name, size, color in (("alpha.png", (96, 64), "navy"), ("bravo.png", (24, 40), "gold")):
        with Image.new("RGB", size, color) as image:
            ImageDraw.Draw(image).rectangle((2, 2, 12, 15), fill="white")
            buffer = BytesIO()
            image.save(buffer, format="PNG")
        files.append(("file", name, buffer.getvalue(), "image/png"))
    output_jpg = ("0001-alpha.jpg", "0002-bravo.jpg")
    return (
        Case(
            BATCH_CHECKS[0],
            "images/convert",
            "image.convert",
            (("format", "jpeg"),),
            tuple(files),
            output_jpg,
            ((96, 64), (24, 40)),
        ),
        Case(
            BATCH_CHECKS[1],
            "images/resize",
            "image.resize",
            (
                ("format", "png"),
                ("max_width", "48"),
                ("max_height", "48"),
                ("allow_upscale", "false"),
            ),
            tuple(files),
            ("0001-alpha.png", "0002-bravo.png"),
            ((48, 32), (24, 40)),
        ),
        Case(
            BATCH_CHECKS[2],
            "images/compress",
            "image.compress",
            (("format", "jpeg"), ("quality", "70")),
            tuple(files),
            output_jpg,
            ((96, 64), (24, 40)),
        ),
        Case(
            BATCH_CHECKS[3],
            "office/to-pdf",
            "office.to_pdf",
            (),
            tuple(
                ("file", name, payload, "application/octet-stream")
                for name, payload in (
                    ("alpha.docx", make_synthetic_docx()),
                    ("bravo.pptx", make_synthetic_pptx()),
                    ("charlie.xlsx", make_synthetic_xlsx()),
                )
            ),
            ("0001-alpha.pdf", "0002-bravo.pdf", "0003-charlie.pdf"),
            markers=("DocuForge runtime smoke", PPTX_MARKER, XLSX_MARKER),
        ),
    )


def uuid(value):
    try:
        return value if isinstance(value, str) and str(UUID(value)) == value else None
    except ValueError:
        return None


def location_id(value):
    if isinstance(value, str) and value.startswith(PREFIX):
        return uuid(value[len(PREFIX) :])
    return None


def json_object(response, *, require_media=True):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        if require_media:
            require(
                (_header(response, "content-type") or "").split(";")[0].strip().lower()
                == "application/json",
                "snapshot_invalid",
            )
        value = json.loads(response.body, object_pairs_hook=unique)
        require(isinstance(value, dict), "snapshot_invalid")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise Failure("snapshot_invalid") from None


def private(response):
    require(
        "no-store"
        in [part.strip().lower() for part in (_header(response, "cache-control") or "").split(",")],
        "access_invalid",
    )


def absent(response):
    private(response)
    payload = json_object(response)
    require(
        response.status_code == 404
        and payload == {"code": "batch_not_found", "message": "The batch session was not found."},
        "access_invalid",
    )


@dataclass(repr=False)
class Owned:
    identity: str
    token: str
    verified: bool = False
    item_ids: tuple | None = None
    # No capabilities or identities in repr, reports or diagnostic exceptions.

    @property
    def path(self):
        return PREFIX + self.identity


def snapshot(payload, owned, case):
    try:
        return _snapshot(payload, owned, case)
    except (KeyError, TypeError, ValueError):
        raise Failure("snapshot_invalid") from None


def _snapshot(payload, owned, case):
    """Validate only the existing snapshot contract used by these fixtures."""
    code = "snapshot_invalid"
    require(
        payload.get("id") == owned.identity and payload.get("operation") == case.operation, code
    )
    require(type(payload.get("attempt")) is int and payload["attempt"] == 1, code)
    require(
        payload.get("phase")
        in {"queued", "processing", "cancelling", "packaging", "ready", "error"},
        code,
    )
    for key in ("cancellation_requested", "can_cancel", "can_recover", "can_download"):
        require(type(payload.get(key)) is bool, code)
    require("session_error" in payload, code)
    if payload["session_error"] is not None:
        error = payload["session_error"]
        require(
            isinstance(error, dict)
            and all(isinstance(error.get(k), str) for k in ("code", "message")),
            code,
        )
    items = payload.get("items")
    require(isinstance(items, list) and len(items) == len(case.files), code)
    counts = dict.fromkeys(("pending", "running", "completed", "failed", "cancelled"), 0)
    identities = []
    for index, item in enumerate(items):
        require(isinstance(item, dict), code)
        identity = uuid(item.get("id"))
        require(identity is not None and identity not in identities, code)
        identities.append(identity)
        require(
            type(item.get("position")) is int
            and item["position"] == index
            and item.get("descriptor") == case.files[index][1],
            code,
        )
        status = item.get("status")
        require(isinstance(status, str) and status in counts, code)
        counts[status] += 1
        require("result_descriptor" in item and "failure" in item, code)
        require(
            item["result_descriptor"] == (case.outputs[index] if status == "completed" else None),
            code,
        )
        failure = item["failure"]
        if status == "failed":
            require(
                isinstance(failure, dict)
                and all(isinstance(failure.get(k), str) for k in ("code", "message")),
                code,
            )
        else:
            require(failure is None, code)
    require(owned.item_ids is None or owned.item_ids == tuple(identities), code)
    owned.item_ids = tuple(identities)
    total = len(items)
    processed = counts["completed"] + counts["failed"] + counts["cancelled"]
    expected = dict(counts, total=total, processed=processed, remaining=total - processed)
    summary = payload.get("summary")
    require(
        isinstance(summary, dict)
        and all(type(summary.get(k)) is int and summary[k] == v for k, v in expected.items()),
        code,
    )
    require(
        type(payload.get("progress_percent")) is int
        and payload["progress_percent"] == processed * 100 // total,
        code,
    )
    status = next(
        (s for s in ("pending", "completed", "failed", "cancelled") if counts[s] == total),
        "partial" if processed == total else "running",
    )
    require(payload.get("status") == status, code)
    if (
        counts["failed"]
        or counts["cancelled"]
        or payload["cancellation_requested"]
        or payload["session_error"] is not None
        or payload["phase"] == "error"
    ):
        raise Failure("execution_failed")
    if payload["phase"] == "ready":
        require(
            status == "completed"
            and payload["progress_percent"] == 100
            and payload["can_download"]
            and not payload["can_cancel"]
            and not payload["can_recover"],
            code,
        )
        return True
    return False


def new_report(mode="lifecycle"):
    return {
        "schema_version": 1,
        "mode": mode,
        "result": "FAIL",
        "identity": "NOT_RUN",
        "attempted": 0,
        "passed": 0,
        "code": "none",
        "checks": [
            {
                "name": name,
                "outcome": "SKIPPED",
                "stage": "skipped",
                "code": "none",
                "ownership": "NONE",
                "cleanup": "NOT_NEEDED",
                "cleanup_code": "none",
            }
            for name in BATCH_CHECKS
        ],
    }


class Lifecycle:
    def __init__(
        self,
        api_url,
        *,
        timing=DEFAULT_TIMING,
        requester=request_batch_http,
        clock=time.monotonic,
        sleeper=time.sleep,
    ):
        timing.validate()
        self.origin = normalize_origin(api_url, label="API")
        self.timing, self.requester = timing, requester
        self.clock, self.sleeper = clock, sleeper

    def request(self, method, path, deadline, *, token=None, body=None, headers=None):
        remaining = deadline - self.clock()
        require(remaining > 0, "deadline_exceeded")
        values = dict(headers or {})
        if token is not None:
            values[TOKEN_HEADER] = token
        try:
            response = self.requester(
                method,
                self.origin + path,
                headers=values,
                body=body,
                timeout=min(self.timing.timeout, remaining),
            )
        except Exception:  # noqa: BLE001 - injected transports can contain private diagnostics
            raise Failure("transport_failed") from None
        # Acceptance ownership must be registered before checking its body/metadata/budget.
        if method == "POST" and path in CREATION_PATHS:
            return response
        self.response(response, deadline)
        return response

    def response(self, response, deadline):
        if getattr(response, "body_error", None):
            raise Failure(response.body_error)
        require(self.clock() < deadline, "deadline_exceeded")
        require(len(response.body) <= MAX_RESPONSE_BYTES, "response_too_large")
        require(not 300 <= response.status_code < 400, "redirect_refused")

    def pause(self, deadline):
        remaining = deadline - self.clock()
        require(remaining > 0, "deadline_exceeded")
        self.sleeper(min(self.timing.poll_interval, remaining))

    def status(self, owned, deadline):
        response = self.request("GET", owned.path, deadline, token=owned.token)
        private(response)
        if response.status_code == 404:
            absent(response)
            return None
        self.http_ok(response, 200)
        value = json_object(response)
        require(value.get("id") == owned.identity, "snapshot_invalid")
        owned.verified = True
        return value

    @staticmethod
    def http_ok(response, expected):
        if response.status_code != expected:
            code = {
                429: "capacity_unavailable",
                507: "storage_unavailable",
            }.get(response.status_code, "http_failed")
            # Translate only fixed known codes; never expose server diagnostics.
            try:
                code = {
                    "office_engine_unavailable": "engine_unavailable",
                    "batch_capacity_exceeded": "capacity_unavailable",
                    "batch_storage_pressure": "storage_unavailable",
                    "batch_storage_unavailable": "storage_unavailable",
                }.get(json_object(response).get("code"), code)
            except (Failure, TypeError):
                pass
            raise Failure(code)

    def cleanup(self, owned):
        deadline = self.clock() + self.timing.cleanup_seconds

        def phase(value):
            # Cleanup must tolerate failed item results, but still requires a
            # matching, typed snapshot before using cancellation availability.
            require(value.get("id") == owned.identity, "snapshot_invalid")
            require(type(value.get("can_cancel")) is bool, "snapshot_invalid")
            current = value.get("phase")
            require(
                isinstance(current, str)
                and current
                in {"queued", "processing", "cancelling", "packaging", "ready", "error"},
                "snapshot_invalid",
            )
            return current

        value = self.status(owned, deadline)
        cancellation_attempted = False
        polls = 0
        while value is not None and phase(value) not in {"ready", "error"}:
            require(polls < self.timing.max_polls, "poll_limit")
            if value["can_cancel"] and not cancellation_attempted:
                cancellation_attempted = True
                response = self.request("POST", owned.path + "/cancel", deadline, token=owned.token)
                private(response)
                if response.status_code == 409:
                    require(
                        json_object(response)
                        == {
                            "code": "batch_not_cancellable",
                            "message": "The batch can no longer be cancelled.",
                        },
                        "cleanup_failed",
                    )
                else:
                    self.http_ok(response, 202)
                    phase(json_object(response))
                # Re-read authorized status after either acceptance or the exact
                # documented completion race; never resend cancellation.
            else:
                self.pause(deadline)
            value = self.status(owned, deadline)
            polls += 1
        if value is None:
            require(owned.verified, "cleanup_failed")
        else:
            response = self.request("DELETE", owned.path, deadline, token=owned.token)
            if response.status_code == 404:
                absent(response)
                require(owned.verified, "cleanup_failed")
            else:
                self.http_ok(response, 204)
                require(response.body == b"", "cleanup_failed")
        # Prove both routes inaccessible with the original authorized capability.
        for suffix in ("", "/download"):
            absent(self.request("GET", owned.path + suffix, deadline, token=owned.token))

    def run(self, *, report=None, deadline=None):
        report = new_report() if report is None else report
        deadline = self.clock() + self.timing.suite_seconds if deadline is None else deadline
        for case, evidence in zip(cases(), report["checks"], strict=True):
            owned = []
            case_deadline = min(deadline, self.clock() + self.timing.case_seconds)
            evidence.update(outcome="FAIL", stage="acceptance")
            report["attempted"] += 1
            try:
                body, content_type = _multipart_body(fields=case.fields, files=case.files)
                require(self.clock() < case_deadline, "deadline_exceeded")
                evidence.update(ownership="UNCERTAIN", cleanup="UNCONFIRMED")
                try:
                    response = self.request(
                        "POST",
                        PREFIX + case.route,
                        case_deadline,
                        body=body,
                        headers={"Content-Type": content_type},
                    )
                except Failure as error:
                    if str(error) == "transport_failed":
                        raise Failure("creation_uncertain") from None
                    raise
                if response.status_code != 202:
                    self.response(response, case_deadline)
                    try:
                        private(response)
                        rejection = json_object(response)
                        if rejection.get("code") in {
                            "batch_capacity_exceeded",
                            "batch_storage_pressure",
                            "batch_storage_unavailable",
                            "office_engine_unavailable",
                            "invalid_batch_request",
                            "invalid_image_format",
                            "invalid_resize_request",
                            "invalid_compression_request",
                        }:
                            evidence.update(ownership="NONE", cleanup="NOT_NEEDED")
                    except (Failure, TypeError):
                        pass
                    # Unknown 5xx/proxy/ambiguous replies may conceal an acceptance.
                    if evidence["ownership"] == "UNCERTAIN":
                        raise Failure("creation_uncertain")
                    self.http_ok(response, 202)
                token = _header(response, TOKEN_HEADER)
                safe_token = isinstance(token, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,256}", token)
                from_location = location_id(_header(response, "location"))
                if safe_token and from_location:
                    owned.append(Owned(from_location, token))
                value = None
                if len(response.body) <= MAX_RESPONSE_BYTES:
                    try:
                        value = json_object(response, require_media=False)
                    except Failure:
                        pass
                from_json = uuid(value.get("id")) if value is not None else None
                # Keep every distinct canonical candidate, never server-supplied URLs.
                # Authenticated status must establish ownership before absence is trusted.
                if safe_token and from_json and from_json != from_location:
                    owned.append(Owned(from_json, token))
                if owned:
                    evidence["ownership"] = "OWNED"
                self.response(response, case_deadline)
                require(bool(owned), "creation_uncertain")
                require(
                    from_location is not None and from_location == from_json and value is not None,
                    "acceptance_invalid",
                )
                json_object(response)  # media type is still mandatory for acceptance
                private(response)
                current = owned[0]
                # A grant establishes a cleanup candidate; only authenticated status
                # can prove this capability works before an existing 404 means absence.
                snapshot(value, current, case)
                evidence["stage"] = "access"
                wrong = "incorrect-smoke-capability"
                if wrong == current.token:
                    wrong += "-different"
                for token_value in (None, wrong):
                    for suffix in ("", "/download"):
                        absent(
                            self.request(
                                "GET", current.path + suffix, case_deadline, token=token_value
                            )
                        )
                evidence["stage"] = "polling"
                # Correct authorization must succeed after all four denial probes.
                for _ in range(self.timing.max_polls):
                    value = self.status(current, case_deadline)
                    require(value is not None, "snapshot_invalid")
                    ready = snapshot(value, current, case)
                    if ready:
                        break
                    self.pause(case_deadline)
                else:
                    raise Failure("poll_limit")
                evidence["stage"] = "download"
                response = self.request(
                    "GET", current.path + "/download", case_deadline, token=current.token
                )
                self.http_ok(response, 200)
                private(response)
                try:
                    _download(response, "application/zip")
                    with quiet_validation():
                        outputs = _zip_members(response.body, case.outputs)
                        for index, output in enumerate(outputs):
                            if case.markers:
                                pages = _pdf_pages(output)
                                _require_marker(
                                    " ".join(_page_text(page) for page in pages),
                                    case.markers[index],
                                )
                            else:
                                _image(
                                    output,
                                    "PNG" if case.route == "images/resize" else "JPEG",
                                    case.dimensions[index],
                                )
                except Exception:  # noqa: BLE001 - private parser diagnostics
                    raise Failure("output_invalid") from None
                require(self.clock() < case_deadline, "deadline_exceeded")
                evidence.update(outcome="PASS", stage="complete")
            except Exception as error:  # noqa: BLE001 - retain safe partial evidence and clean up
                evidence["code"] = (
                    str(error) if isinstance(error, Failure) else "unexpected_failure"
                )
            finally:
                if owned:
                    cleanup_codes = []
                    for session in owned:
                        try:
                            self.cleanup(session)
                        except Exception as error:  # noqa: BLE001 - continue every owned cleanup
                            cleanup_codes.append(
                                str(error) if isinstance(error, Failure) else "cleanup_failed"
                            )
                    evidence["cleanup"] = "UNCONFIRMED" if cleanup_codes else "CONFIRMED"
                    evidence["cleanup_code"] = cleanup_codes[0] if cleanup_codes else "none"
                if evidence["cleanup"] == "UNCONFIRMED":
                    if evidence["outcome"] == "PASS":
                        evidence.update(stage="cleanup", code="cleanup_failed")
                    evidence["outcome"] = "FAIL"
            if evidence["outcome"] != "PASS":
                report["code"] = evidence["code"]
                break
            report["passed"] += 1
        if report["passed"] == len(BATCH_CHECKS):
            report["result"] = "PASS"
        return report


def run_public(
    *,
    api_url,
    frontend_url,
    expected_api_revision,
    expected_frontend_revision,
    expected_version,
    timing=DEFAULT_TIMING,
    requester=request_batch_http,
    clock=time.monotonic,
    sleeper=time.sleep,
):
    report = new_report("public")
    try:
        timing.validate()
        api = normalize_origin(api_url, label="API")
        frontend = normalize_origin(frontend_url, label="frontend")
        expected_api = revision(expected_api_revision)
        expected_frontend = revision(expected_frontend_revision)
        version = validate_version(expected_version)
        report["deployment"] = {
            "api_origin": api,
            "frontend_origin": frontend,
            "api_revision": expected_api,
            "frontend_revision": expected_frontend,
            "version": version,
        }
    except Exception:  # noqa: BLE001 - configuration boundary must not echo arbitrary values
        report["code"] = "configuration_invalid"
        return report
    deadline = clock() + timing.suite_seconds
    runner = Lifecycle(api, timing=timing, requester=requester, clock=clock, sleeper=sleeper)

    def identity_request(method, url, *, headers=None, body=None, timeout):
        remaining = deadline - clock()
        require(remaining > 0, "deadline_exceeded")
        response = requester(
            method, url, headers=headers, body=body, timeout=min(timeout, remaining)
        )
        runner.response(response, deadline)
        return response

    try:
        verify_deployed_builds(
            api,
            frontend_url=frontend,
            expected_api_revision=expected_api,
            expected_frontend_revision=expected_frontend,
            expected_version=version,
            timeout=timing.timeout,
            requester=identity_request,
        )
    except Exception:  # noqa: BLE001 - identity/parser/transport diagnostics stay private
        report.update(identity="FAIL", code="identity_failed")
        return report
    report["identity"] = "PASS"
    return runner.run(report=report, deadline=deadline)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify strict public identity, then CREATE and DELETE four synthetic batch sessions."
    )
    for name in (
        "api-url",
        "frontend-url",
        "expected-api-revision",
        "expected-frontend-revision",
        "expected-version",
    ):
        parser.add_argument("--" + name, required=True)
    for name, default in (
        ("timeout", 20),
        ("case-seconds", 120),
        ("suite-seconds", 600),
        ("cleanup-seconds", 60),
        ("poll-interval", 0.5),
    ):
        parser.add_argument("--" + name, type=float, default=default)
    parser.add_argument("--max-polls", type=int, default=240)
    parser.add_argument("--report-json", type=Path)
    args = vars(parser.parse_args(argv))
    path = args.pop("report_json")
    timing = Timing(**{key: args.pop(key) for key in Timing.__dataclass_fields__})
    try:
        if path:
            # Check evidence destination before any network or session creation.
            initial = new_report("public")
            initial["code"] = "configuration_invalid"
            path.write_text(json.dumps(initial) + "\n", encoding="utf-8")
        report = run_public(**args, timing=timing)
        if path:
            path.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 - safe CLI and evidence write boundary
        print("Batch lifecycle FAIL: evidence_unavailable", file=sys.stderr)
        return 1
    print(f"Batch lifecycle {report['result']}: {report['passed']}/4; {report['code']}")
    return int(report["result"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())

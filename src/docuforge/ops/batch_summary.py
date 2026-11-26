"""Validate the version-one batch evidence contract; render fixed safe fields only."""

from __future__ import annotations

import os
from pathlib import Path

from docuforge.build_identity import revision, validate_version
from docuforge.ops.batch_smoke import BATCH_CHECKS, CODES, STAGES
from docuforge.ops.production_summary import _report
from docuforge.ops.release_identity import normalize_origin

ROW_KEYS = {"name", "outcome", "stage", "code", "ownership", "cleanup", "cleanup_code"}
REPORT_KEYS = {
    "schema_version",
    "mode",
    "result",
    "identity",
    "attempted",
    "passed",
    "code",
    "checks",
}


def valid_report(value):
    """Reject missing fields, extra private material and contradictory partial evidence."""
    try:
        if not isinstance(value, dict) or set(value) not in (
            REPORT_KEYS,
            REPORT_KEYS | {"deployment"},
        ):
            return False
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["mode"] not in {"public", "lifecycle"}
            or value["identity"] not in {"PASS", "FAIL", "NOT_RUN"}
            or value["result"] not in {"PASS", "FAIL"}
            or value["code"] not in CODES
        ):
            return False
        if "deployment" in value:
            deployment = value["deployment"]
            if set(deployment) != {
                "api_origin",
                "frontend_origin",
                "api_revision",
                "frontend_revision",
                "version",
            }:
                return False
            for component in ("api", "frontend"):
                origin = deployment[component + "_origin"]
                if normalize_origin(origin, label=component) != origin:
                    return False
                if (
                    revision(deployment[component + "_revision"])
                    != deployment[component + "_revision"]
                ):
                    return False
            validate_version(deployment["version"])
        rows = value["checks"]
        if not isinstance(rows, list) or len(rows) != 4:
            return False
        attempted = passed = 0
        stopped = False
        for name, row in zip(BATCH_CHECKS, rows, strict=True):
            if (
                not isinstance(row, dict)
                or set(row) != ROW_KEYS
                or row["name"] != name
                or row["outcome"] not in {"PASS", "FAIL", "SKIPPED"}
                or row["stage"] not in STAGES
                or row["code"] not in CODES
                or row["ownership"] not in {"NONE", "OWNED", "UNCERTAIN"}
                or row["cleanup"] not in {"CONFIRMED", "UNCONFIRMED", "NOT_NEEDED"}
                or row["cleanup_code"] not in CODES
            ):
                return False
            if row["outcome"] == "SKIPPED":
                if row != {
                    "name": name,
                    "outcome": "SKIPPED",
                    "stage": "skipped",
                    "code": "none",
                    "ownership": "NONE",
                    "cleanup": "NOT_NEEDED",
                    "cleanup_code": "none",
                }:
                    return False
                stopped = True
            else:
                if stopped or row["stage"] == "skipped":
                    return False
                attempted += 1
                if row["outcome"] == "PASS":
                    if row != {
                        "name": name,
                        "outcome": "PASS",
                        "stage": "complete",
                        "code": "none",
                        "ownership": "OWNED",
                        "cleanup": "CONFIRMED",
                        "cleanup_code": "none",
                    }:
                        return False
                    passed += 1
                else:
                    if row["code"] == "none":
                        return False
                    stopped = True
        if (
            type(value["attempted"]) is not int
            or value["attempted"] != attempted
            or type(value["passed"]) is not int
            or value["passed"] != passed
        ):
            return False
        if value["mode"] == "public":
            if attempted and value["identity"] != "PASS":
                return False
            if value["identity"] == "PASS" and "deployment" not in value:
                return False
        elif value["identity"] != "NOT_RUN" or "deployment" in value:
            return False
        if value["result"] == "PASS":
            return passed == attempted == 4 and value["code"] == "none"
        return passed < 4 and value["code"] != "none"
    except (KeyError, TypeError, ValueError, RuntimeError):
        return False


def render_summary(environment, *, directory=Path(".")):
    report = _report(directory / "batch-smoke.json")
    valid = valid_report(report)
    deployment_ok = False
    if valid and report["mode"] == "public":
        try:
            expected = {"version": validate_version(environment["DOCUFORGE_EXPECTED_VERSION"])}
            for component in ("api", "frontend"):
                upper = component.upper()
                expected[component + "_origin"] = normalize_origin(
                    environment[f"DOCUFORGE_{upper}_URL"], label=component
                )
                expected[component + "_revision"] = revision(
                    environment[f"DOCUFORGE_EXPECTED_{upper}_REVISION"]
                )
            deployment_ok = report.get("deployment") == expected
        except (KeyError, ValueError, RuntimeError):
            pass
    success = (
        valid
        and deployment_ok
        and report["identity"] == "PASS"
        and report["result"] == "PASS"
        and environment.get("BATCH_OUTCOME") == "success"
    )
    lines = [
        "## Public Batch Lifecycle Verification",
        f"Overall: {'PASS' if success else 'FAIL'}",
        f"Strict identity: {'PASS' if valid and deployment_ok and report['identity'] == 'PASS' else 'FAIL / incomplete'}",
        f"Attempted: {report['attempted'] if valid else 0} / 4",
        f"Passed with confirmed cleanup: {report['passed'] if valid else 0} / 4",
    ]
    for index, name in enumerate(BATCH_CHECKS):
        if valid:
            row = report["checks"][index]
            lines.append(
                f"{name}: {row['outcome']}; stage={row['stage']}; code={row['code']}; "
                f"cleanup={row['cleanup']}; cleanup_code={row['cleanup_code']}"
            )
        else:
            lines.append(f"{name}: evidence missing or invalid; cleanup unconfirmed")
    lines.append(
        "Separate batch-readiness evidence; no change to the 21 semantic checks, "
        "18 runtime/durable markers or four Office/OCR integration checks."
    )
    return "\n\n".join(lines) + "\n"


def main():
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
        stream.write(render_summary(os.environ))


if __name__ == "__main__":
    main()

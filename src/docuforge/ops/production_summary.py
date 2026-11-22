"""Fail-closed summary of the separate identity and semantic smoke gates."""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

from docuforge.build_identity import revision, validate_version
from docuforge.ops.deployment_smoke import SMOKE_CHECKS, DeploymentSmokeError
from docuforge.ops.release_identity import normalize_origin
from docuforge.version import package_version


def _report(path: Path) -> dict:
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate report field")
            value[key] = item
        return value

    try:
        with path.open("rb") as stream:
            data = stream.read(32769)
        if len(data) > 32768:
            return {}
        value = json.loads(data, object_pairs_hook=unique_object)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError, RecursionError):
        return {}


def render_summary(environment, *, directory: Path = Path(".")) -> str:
    """Render only validated evidence; step outcomes alone never imply a PASS."""
    identity = _report(directory / "release-identity.json")
    smoke = _report(directory / "production-smoke.json")
    expected_version = package_version()
    lines = ["## Public Production Smoke"]
    components = identity.get("components")
    components = components if isinstance(components, dict) else {}
    identity_ok = (
        type(identity.get("schema_version")) is int
        and identity["schema_version"] == 1
        and identity.get("mode") == "strict"
        and identity.get("result") == "PASS"
        and identity.get("expected_version") == expected_version
        and environment.get("IDENTITY_OUTCOME") == "success"
    )
    for name, label in (("api", "API"), ("frontend", "Frontend")):
        try:
            origin = normalize_origin(environment[f"DOCUFORGE_{name.upper()}_URL"], label=label)
            expected = revision(environment[f"DOCUFORGE_EXPECTED_{name.upper()}_REVISION"])
        except (KeyError, ValueError, DeploymentSmokeError):
            lines.append(f"{label}: invalid origin or expected revision (omitted)")
            identity_ok = False
            continue
        lines.extend(
            [f"{label} origin: {html.escape(origin)}", f"{label} expected revision: {expected}"]
        )
        component = components.get(name)
        component = component if isinstance(component, dict) else {}
        try:
            observed = revision(component.get("observed_revision"))
            observed_version = validate_version(component.get("observed_version"))
            evidence_ok = (
                component.get("origin") == origin
                and component.get("expected_revision") == expected
                and observed == expected
                and observed_version == expected_version
                and component.get("outcome") == "PASS"
            )
            lines.append(f"{label} observed revision: {observed} (version {observed_version})")
        except ValueError:
            evidence_ok = False
            lines.append(f"{label} observed revision: unknown or invalid (omitted)")
        identity_ok = identity_ok and evidence_ok
    passed = smoke.get("passed_checks", [])
    if not isinstance(passed, list) or passed != list(SMOKE_CHECKS[: len(passed)]):
        passed = []
    count = smoke.get("checks_executed", 0)
    if type(count) is not int or not 0 <= count <= len(SMOKE_CHECKS):
        count = 0
    success = (
        identity_ok
        and environment.get("SMOKE_OUTCOME") == "success"
        and smoke.get("result") == "PASS"
        and passed == list(SMOKE_CHECKS)
        and count == len(SMOKE_CHECKS)
    )
    lines.insert(1, f"Overall: {'PASS' if success else 'FAIL'}")
    lines.extend(
        [
            f"Identity outcome: {'PASS' if identity_ok else 'FAIL / incomplete'}",
            f"Expected semantic release version: {expected_version}",
            f"Checks executed: {count} / {len(SMOKE_CHECKS)}",
            f"Passed checks: {', '.join(passed) or 'None'}",
            "Build metadata and HTML consistency are diagnostic identity, not signed provenance.",
        ]
    )
    repository = environment.get("GITHUB_REPOSITORY", "")
    run_id = environment.get("GITHUB_RUN_ID", "")
    # GitHub-owned fields still have to be safe before becoming summary markup.
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) and run_id.isdecimal():
        lines.append(f"Workflow run: https://github.com/{repository}/actions/runs/{run_id}")
    return "\n\n".join(lines) + "\n"


def main() -> None:
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
        stream.write(render_summary(os.environ))


if __name__ == "__main__":
    main()

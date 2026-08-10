import ast
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from docuforge.version import package_version


def test_create_app_returns_separate_fastapi_instances() -> None:
    first = create_app()
    second = create_app()

    assert isinstance(first, FastAPI)
    assert isinstance(second, FastAPI)
    assert first is not second
    assert first.title == "DocuForge API"
    assert first.version == package_version()
    assert TestClient(first).get("/api/v1").status_code == 200


def test_applications_keep_configuration_isolated() -> None:
    first = create_app(
        ApiSettings(application_name="First API", version="1.0.0", api_prefix="/first")
    )
    second = create_app(
        ApiSettings(application_name="Second API", version="2.0.0", api_prefix="/second")
    )

    assert TestClient(first).get("/first").json() == {
        "name": "First API",
        "version": "1.0.0",
        "status": "available",
    }
    assert TestClient(second).get("/second").json() == {
        "name": "Second API",
        "version": "2.0.0",
        "status": "available",
    }
    assert TestClient(first).get("/second").status_code == 404
    assert TestClient(second).get("/first").status_code == 404


def test_root_api_prefix_routes_metadata_and_health() -> None:
    client = TestClient(create_app(ApiSettings(api_prefix="/")))

    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200


def test_default_version_is_consistent_across_application_and_routes() -> None:
    settings = ApiSettings()
    application = create_app(settings)
    client = TestClient(application)

    assert settings.version == package_version()
    assert application.version == settings.version
    assert client.get("/api/v1").json()["version"] == settings.version
    assert client.get("/api/v1/health").json()["version"] == settings.version


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_documentation_routes_are_enabled_by_default(path: str) -> None:
    assert TestClient(create_app()).get(path).status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_documentation_routes_can_be_disabled(path: str) -> None:
    application = create_app(ApiSettings(docs_enabled=False))

    assert application.docs_url is None
    assert application.redoc_url is None
    assert application.openapi_url is None
    assert TestClient(application).get(path).status_code == 404


def test_cli_import_does_not_initialize_fastapi() -> None:
    project_root = Path(__file__).resolve().parents[2]
    script = (
        "import sys; import docuforge.__main__; "
        "assert 'fastapi' not in sys.modules; "
        "raise SystemExit(docuforge.__main__.main(['--help']))"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage: docuforge" in result.stdout
    assert result.stderr == ""


def test_api_dependencies_do_not_leak_into_sibling_packages() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src" / "docuforge"
    forbidden_roots = ("fastapi", "starlette", "docuforge.api")

    for package_name in ("core", "converters", "cli"):
        for source_path in (source_root / package_name).rglob("*.py"):
            syntax_tree = ast.parse(source_path.read_text(encoding="utf-8"))
            imported_modules = {
                alias.name
                for node in ast.walk(syntax_tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            imported_modules.update(
                node.module
                for node in ast.walk(syntax_tree)
                if isinstance(node, ast.ImportFrom) and node.module is not None
            )

            assert not any(
                module == root or module.startswith(f"{root}.")
                for module in imported_modules
                for root in forbidden_roots
            ), f"forbidden API dependency in {source_path}"

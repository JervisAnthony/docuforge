import json
import tomllib
from pathlib import Path

from docuforge.version import DEVELOPMENT_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_mvp1_versions_are_aligned() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    frontend = json.loads(
        (PROJECT_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )

    assert project["version"] == "0.1.0"
    assert DEVELOPMENT_VERSION == "0.1.0"
    assert frontend["version"] == "0.1.0"


def test_project_metadata_marks_alpha_release() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    classifiers = project["classifiers"]

    assert "Development Status :: 3 - Alpha" in classifiers
    assert "Development Status :: 2 - Pre-Alpha" not in classifiers


def test_readme_identifies_mvp1_release_candidate() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Release candidate: `0.1.0`" in readme
    assert "pre-alpha development version" not in readme

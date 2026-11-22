"""Real wheel/sdist and installed-resource checks; also run by the CI build job."""

import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile

import pytest

pytest.importorskip("build")

ROOT = Path(__file__).resolve().parents[2]
SHA = "a1" * 20


def _run(args, *, cwd, env):
    result = subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_wheel_sdist_installed_stamp_and_rebuild_without_git(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "setup.py", "README.md", "LICENSE"):
        shutil.copyfile(ROOT / name, source / name)
    shutil.copytree(
        ROOT / "src/docuforge",
        source / "src/docuforge",
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "_build_identity.json",
        ),
    )
    env = os.environ.copy()
    for name in ("DOCUFORGE_BUILD_REVISION", "RAILWAY_GIT_COMMIT_SHA", "PYTHONPATH"):
        env.pop(name, None)
    known_env = dict(env, DOCUFORGE_BUILD_REVISION=SHA.upper(), RAILWAY_GIT_COMMIT_SHA=SHA)
    for name, build_env, expected in (("known", known_env, SHA), ("unknown", env, None)):
        output = tmp_path / name
        _run(
            ["-m", "build", "--no-isolation", "--wheel", "--outdir", str(output)],
            cwd=source,
            env=build_env,
        )
        wheel = next(output.glob("*.whl"))
        with ZipFile(wheel) as archive:
            resources = [path for path in archive.namelist() if path.endswith(".json")]
            assert resources == ["docuforge/_build_identity.json"]
            assert json.loads(archive.read(resources[0])) == {
                "schema_version": 1,
                "service": "docuforge",
                "version": "0.1.0",
                "revision": expected,
            }
        installed = tmp_path / (name + "-installed")
        _run(
            [
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-compile",
                "--target",
                str(installed),
                str(wheel),
            ],
            cwd=tmp_path,
            env=env,
        )
        runtime_env = dict(
            env,
            DOCUFORGE_BUILD_REVISION="private invalid override",
            RAILWAY_GIT_COMMIT_SHA="b" * 40,
        )
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from docuforge.build_identity import read_identity; "
            "assert read_identity() == "
            + repr(
                {
                    "schema_version": 1,
                    "service": "docuforge",
                    "version": "0.1.0",
                    "revision": expected,
                }
            )
        )
        _run(["-I", "-c", script, str(installed)], cwd=tmp_path, env=runtime_env)
    assert not (source / "src/docuforge/_build_identity.json").exists()
    output = tmp_path / "source-dist"
    _run(
        ["-m", "build", "--no-isolation", "--sdist", "--outdir", str(output)],
        cwd=source,
        env=known_env,
    )
    sdist = next(output.glob("*.tar.gz"))
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
        assert any(path.endswith("/setup.py") for path in names)
        assert any(path.endswith("/src/docuforge/build_identity.py") for path in names)
        assert not any(path.endswith("/_build_identity.json") for path in names)
        # Only the freshly built source archive is extracted into this empty temporary tree.
        archive.extractall(tmp_path / "roundtrip", filter="data")
    restored = next((tmp_path / "roundtrip").iterdir())
    _run(
        ["-m", "build", "--no-isolation", "--wheel", "--outdir", str(tmp_path / "roundtrip-wheel")],
        cwd=restored,
        env=known_env,
    )
    with ZipFile(next((tmp_path / "roundtrip-wheel").glob("*.whl"))) as archive:
        assert json.loads(archive.read("docuforge/_build_identity.json"))["revision"] == SHA

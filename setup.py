"""Generate identity in each wheel, never in the working source tree."""

import os
import runpy
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    """Stamp fresh build output even when setuptools reuses a build directory."""

    def run(self):
        super().run()
        helpers = runpy.run_path(str(Path(__file__).parent / "src/docuforge/build_identity.py"))
        helpers["write_stamp"](
            Path(self.build_lib) / "docuforge" / helpers["RESOURCE"],
            version=self.distribution.get_version(),
            explicit=os.environ.get("DOCUFORGE_BUILD_REVISION"),
            provider=os.environ.get("RAILWAY_GIT_COMMIT_SHA"),
        )


setup(cmdclass={"build_py": BuildPy})

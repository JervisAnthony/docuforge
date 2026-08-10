"""Package version lookup shared by DocuForge adapters."""

from importlib.metadata import PackageNotFoundError, version

DEVELOPMENT_VERSION = "0.1.0.dev0"


def package_version() -> str:
    """Return the installed package version or the source-tree development version."""
    try:
        return version("docuforge")
    except PackageNotFoundError:
        return DEVELOPMENT_VERSION

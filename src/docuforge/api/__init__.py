"""Public interface for the DocuForge HTTP adapter."""

from docuforge.api.app import create_app
from docuforge.api.config import ApiSettings

__all__ = ["ApiSettings", "create_app"]

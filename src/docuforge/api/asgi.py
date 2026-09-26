"""Intentional deployed ASGI application instance."""

from docuforge.api.app import create_app
from docuforge.api.config import ApiSettings

app = create_app(ApiSettings.from_environment())

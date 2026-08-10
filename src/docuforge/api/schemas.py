"""HTTP response contracts for the DocuForge API."""

from typing import Literal

from pydantic import BaseModel


class ApiMetadataResponse(BaseModel):
    """Public metadata describing the running API."""

    name: str
    version: str
    status: Literal["available"]


class HealthResponse(BaseModel):
    """Liveness response for the DocuForge service."""

    status: Literal["ok"]
    service: Literal["docuforge"]
    version: str


class ApiErrorResponse(BaseModel):
    """Stable response returned for errors explicitly translated by the API."""

    code: str
    message: str

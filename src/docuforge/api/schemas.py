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


class ReadinessResponse(BaseModel):
    """Readiness response confirming the API can accept work."""

    status: Literal["ready"]
    service: Literal["docuforge"]
    version: str


class CapabilityResponse(BaseModel):
    """Safe availability state for one optional runtime feature."""

    available: bool


class RuntimeCapabilitiesResponse(BaseModel):
    """Optional runtime features available to conversion requests."""

    office_to_pdf: CapabilityResponse
    ocr: CapabilityResponse


class ApiErrorResponse(BaseModel):
    """Stable response returned for errors explicitly translated by the API."""

    code: str
    message: str


class BatchItemFailureResponse(BaseModel):
    """Safe per-item failure exposed by batch polling."""

    code: str
    message: str


class BatchItemStatusResponse(BaseModel):
    """One ordered item in a batch status response."""

    id: str
    position: int
    descriptor: str
    status: str
    result_descriptor: str | None
    failure: BatchItemFailureResponse | None


class BatchSummaryResponse(BaseModel):
    """Derived counts exposed without filesystem metadata."""

    total: int
    pending: int
    running: int
    completed: int
    failed: int
    cancelled: int
    processed: int
    remaining: int


class BatchSessionErrorResponse(BaseModel):
    """Safe session-level infrastructure failure."""

    code: str
    message: str


class BatchStatusResponse(BaseModel):
    """Pollable process-local batch execution state."""

    id: str
    operation: str
    attempt: int
    phase: str
    status: str
    progress_percent: int
    cancellation_requested: bool
    summary: BatchSummaryResponse
    items: list[BatchItemStatusResponse]
    session_error: BatchSessionErrorResponse | None
    can_cancel: bool
    can_recover: bool
    can_download: bool

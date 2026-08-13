"""Operational middleware and logging for the DocuForge API."""

import json
import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_LOGGER_NAME = "docuforge.api.requests"

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def configure_request_logging() -> None:
    """Emit request records as one JSON object per line for production runtimes."""
    logger = logging.getLogger(REQUEST_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def _resolve_request_id(scope: Scope) -> str:
    request_id = Headers(scope=scope).get(REQUEST_ID_HEADER)
    if request_id is not None and _REQUEST_ID_PATTERN.fullmatch(request_id):
        return request_id
    return uuid4().hex


class ProductionMiddleware:
    """Attach operational headers and write structured request completion logs."""

    def __init__(self, app: ASGIApp, *, environment: str) -> None:
        self.app = app
        self._is_production = environment.strip().lower() == "production"
        self._logger = logging.getLogger(REQUEST_LOGGER_NAME)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _resolve_request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        started_at = perf_counter()
        status_code = 500

        async def send_with_operational_headers(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                for name, value in _SECURITY_HEADERS.items():
                    headers[name] = value
                if self._is_production:
                    headers["Strict-Transport-Security"] = "max-age=31536000"
            await send(message)

        try:
            await self.app(scope, receive, send_with_operational_headers)
        except Exception:
            self._write_request_log(
                scope=scope,
                request_id=request_id,
                status_code=500,
                started_at=started_at,
                outcome="error",
            )
            raise

        self._write_request_log(
            scope=scope,
            request_id=request_id,
            status_code=status_code,
            started_at=started_at,
            outcome="completed",
        )

    def _write_request_log(
        self,
        *,
        scope: Scope,
        request_id: str,
        status_code: int,
        started_at: float,
        outcome: str,
    ) -> None:
        payload = {
            "duration_ms": round((perf_counter() - started_at) * 1000, 3),
            "event": "http_request",
            "method": scope.get("method", ""),
            "outcome": outcome,
            "path": scope.get("path", ""),
            "request_id": request_id,
            "status_code": status_code,
        }
        self._logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))

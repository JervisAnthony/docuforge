"""Production entry point for running the DocuForge API."""

import os

import uvicorn

from docuforge.api.observability import configure_request_logging


def main() -> None:
    """Run Uvicorn using hardened production defaults and deployment-supplied ports."""
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    configure_request_logging()
    uvicorn.run(
        "docuforge.api.app:app",
        host=host,
        port=port,
        access_log=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()

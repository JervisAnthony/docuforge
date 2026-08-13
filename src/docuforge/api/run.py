"""Production entry point for running the DocuForge API."""

import os

import uvicorn


def main() -> None:
    """Run Uvicorn using the host and port supplied by the deployment environment."""
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("docuforge.api.app:app", host=host, port=port)


if __name__ == "__main__":
    main()

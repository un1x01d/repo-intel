from __future__ import annotations

from fastapi import FastAPI

from repo_intel.api.router import api_router
from repo_intel.core.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="repo-intel", version="0.1.0")
    app.include_router(api_router)
    return app


app = create_app()

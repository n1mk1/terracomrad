"""Deployable FastAPI application entrypoint for TerraComrad."""

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.paths import FRONTEND_DIR
from app.routes import router


def _docs_enabled() -> bool:
    """Expose Swagger / ReDoc / OpenAPI only when explicitly enabled.

    Off by default so a public deployment doesn't advertise its full API surface;
    set ``ENABLE_DOCS=true`` (e.g. for local development) to turn the docs back on.
    """
    return (os.getenv("ENABLE_DOCS") or "").strip().lower() in {"1", "true", "yes", "on"}


def create_app() -> FastAPI:
    """Build and configure the FastAPI app."""
    docs = _docs_enabled()
    app = FastAPI(
        title="TerraComrad",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    app.include_router(router)

    @app.get("/")
    async def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()

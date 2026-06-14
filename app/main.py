"""Deployable FastAPI application entrypoint for TerraComrad."""

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.paths import FRONTEND_DIR
from app.routes import router


def create_app() -> FastAPI:
    """Build and configure the FastAPI app."""
    app = FastAPI(title="TerraComrad")
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    app.include_router(router)

    @app.get("/")
    async def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()


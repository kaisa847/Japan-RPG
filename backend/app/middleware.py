"""HTTP middleware setup."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import CORS_ORIGIN


async def add_cache_headers(request: Request, call_next):
    """Disable caching for the served frontend so updates are picked up."""
    response = await call_next(request)
    if request.url.path.startswith("/app/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


def setup_middleware(app: FastAPI) -> None:
    allowed_origins = [CORS_ORIGIN] if CORS_ORIGIN else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(add_cache_headers)

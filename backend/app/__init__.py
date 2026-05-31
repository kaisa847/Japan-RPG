"""Application factory for the Visual Novel backend.

``backend.main`` re-exports the ``app`` created here, so the ASGI entry point
``backend.main:app`` (used by uvicorn, gunicorn, systemd and the tests) stays
valid after the package split.
"""

from dotenv import load_dotenv

# Load .env before anything reads environment variables (e.g. config.CORS_ORIGIN).
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.config import ASSETS_DIR, FRONTEND_DIR
from backend.app.lifespan import lifespan
from backend.app.middleware import setup_middleware
from backend.app.routers import admin, auth, content, game, player, saves, tts


def create_app() -> FastAPI:
    app = FastAPI(title="Japanese Life: Tokyo Stories", lifespan=lifespan)

    setup_middleware(app)

    # Static files
    if ASSETS_DIR.exists():
        app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
    if FRONTEND_DIR.exists():
        app.mount(
            "/app",
            StaticFiles(directory=str(FRONTEND_DIR), html=True),
            name="frontend",
        )

    # Routers
    for module in (auth, admin, player, content, game, saves, tts):
        app.include_router(module.router)

    return app


app = create_app()

"""Application lifespan: startup validation and resource initialization."""

import asyncio
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.config import DATA_DIR
from backend.auth import UserManager
from backend.state_manager import StateManager

logger = logging.getLogger(__name__)


def _load_or_create_jwt_secret() -> str:
    """Return the JWT secret, creating it on first run.

    Robust to multiple worker processes (gunicorn ``--workers``) racing on the
    very first boot: the file is created exclusively with mode 0o600 (so the
    secret is never briefly world-readable), and a worker that loses the race
    falls back to reading the secret the winner just wrote.
    """
    jwt_secret_path = DATA_DIR / ".jwt_secret"
    if jwt_secret_path.exists():
        return jwt_secret_path.read_text(encoding="utf-8").strip()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(32)
    try:
        fd = os.open(
            jwt_secret_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(secret)
        return secret
    except FileExistsError:
        # Another worker created it first — read its value (retry briefly in
        # case we caught it mid-write).
        for _ in range(50):
            existing = jwt_secret_path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
            time.sleep(0.01)
        return jwt_secret_path.read_text(encoding="utf-8").strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_dir = str(DATA_DIR)
    app.state.data_dir = data_dir

    # Startup config validation (warn, don't crash — keep dev-friendly)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning(
            "ANTHROPIC_API_KEY is not set — scene generation will use the "
            "fallback error message until a key is configured."
        )
    if not os.environ.get("CORS_ORIGIN"):
        logger.warning(
            "CORS_ORIGIN is not set — cross-origin requests are blocked. "
            "Set it to your public origin in production deployments."
        )

    # JWT secret
    app.state.jwt_secret = _load_or_create_jwt_secret()

    # User manager
    app.state.user_manager = UserManager(data_dir=data_dir)
    app.state.user_state_managers: dict[str, StateManager] = {}

    # Claude handler (may fail without API key)
    try:
        from backend.claude_handler import ClaudeHandler

        app.state.claude_handler = ClaudeHandler(data_dir=data_dir)
        logger.info("Claude handler initialized")
    except Exception as e:
        logger.warning("Claude handler not available: %s", e)
        app.state.claude_handler = None

    # TTS service (edge-tts, cloud-based - no heavy model loading)
    # Semaphore limits concurrent synthesis requests.
    app.state.tts_semaphore = asyncio.Semaphore(1)

    try:
        from backend.tts_service import TTSService

        tts = TTSService()
        await tts.load()
        app.state.tts_service = tts
        logger.info("TTS service initialized (edge-tts)")
    except ImportError:
        logger.info("TTS dependencies not installed (edge-tts). Voice disabled.")
        app.state.tts_service = None
    except Exception as e:
        logger.warning("TTS initialization failed: %s", e)
        app.state.tts_service = None

    yield

    # Save all active states
    for username, sm in app.state.user_state_managers.items():
        try:
            sm.save()
        except Exception as e:
            logger.error("Failed to save state for %s: %s", username, e)

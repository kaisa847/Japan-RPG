"""Authentication endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm

from backend.app.config import CORS_ORIGIN
from backend.auth import UserManager, UserRecord, create_access_token, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/auth/login")
async def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    # CSRF protection: verify Origin/Referer matches this server
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    expected = CORS_ORIGIN or str(request.base_url).rstrip("/")
    if origin and not origin.startswith(expected):
        raise HTTPException(status_code=403, detail="Cross-origin request blocked.")

    um: UserManager = request.app.state.user_manager
    user = um.authenticate(form.username, form.password)
    client_ip = request.client.host if request.client else "unknown"
    if not user:
        logger.warning("Failed login for '%s' from %s", form.username, client_ip)
        raise HTTPException(status_code=401, detail="Falsche Zugangsdaten.")
    logger.info("User '%s' logged in from %s", user.username, client_ip)
    token = create_access_token(user.username, request.app.state.jwt_secret)
    return {"access_token": token, "token_type": "bearer", "username": user.username}


@router.get("/api/auth/me")
async def get_me(user: UserRecord = Depends(get_current_user)):
    return {
        "username": user.username,
        "is_admin": user.is_admin,
        "player_name": user.player_name,
    }

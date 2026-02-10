"""Authentication and user management."""

import json
import logging
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import bcrypt
import jwt
from pydantic import BaseModel
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

logger = logging.getLogger(__name__)


def _hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))

# --- JWT settings ---
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


# --- Models ---

class UserRecord(BaseModel):
    username: str
    hashed_password: str
    is_admin: bool = False
    created_at: str = ""
    player_name: str = ""


class UserStore(BaseModel):
    users: dict[str, UserRecord] = {}


class TokenData(BaseModel):
    username: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserInfo(BaseModel):
    username: str
    is_admin: bool
    created_at: str
    player_name: str = ""


# --- User Store (JSON file) ---

class UserManager:
    USERS_FILE = "users.json"

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._users_path = self.data_dir / self.USERS_FILE
        self.store = self._load()

    def _load(self) -> UserStore:
        if self._users_path.exists():
            try:
                raw = self._users_path.read_text(encoding="utf-8")
                data = json.loads(raw)
                return UserStore.model_validate(data)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Corrupt users file: %s", e)
        return UserStore()

    def _save(self) -> None:
        tmp = self._users_path.with_suffix(".tmp")
        try:
            tmp.write_text(
                self.store.model_dump_json(indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._users_path)
        except OSError as e:
            logger.error("Failed to save users: %s", e)
            if tmp.exists():
                tmp.unlink()

    def create_user(
        self, username: str, password: str, is_admin: bool = False,
        player_name: str = "",
    ) -> UserRecord:
        username = username.lower().strip()
        if username in self.store.users:
            raise ValueError(f"User '{username}' already exists")
        if not username or len(username) < 3 or len(username) > 20:
            raise ValueError("Username must be 3-20 characters")
        if not all(c.isalnum() or c == "_" for c in username):
            raise ValueError("Username must be alphanumeric (a-z, 0-9, _)")

        record = UserRecord(
            username=username,
            hashed_password=_hash_password(password),
            is_admin=is_admin,
            created_at=datetime.now(timezone.utc).isoformat(),
            player_name=player_name.strip(),
        )
        self.store.users[record.username] = record
        self._save()

        # Create user data directory
        user_data_dir = self.data_dir / "users" / record.username
        user_data_dir.mkdir(parents=True, exist_ok=True)

        return record

    def authenticate(
        self, username: str, password: str
    ) -> Optional[UserRecord]:
        user = self.store.users.get(username.lower().strip())
        if not user:
            return None
        if not _verify_password(password, user.hashed_password):
            return None
        return user

    def get_user(self, username: str) -> Optional[UserRecord]:
        return self.store.users.get(username.lower().strip())

    def list_users(self) -> list[UserInfo]:
        return [
            UserInfo(
                username=u.username,
                is_admin=u.is_admin,
                created_at=u.created_at,
                player_name=u.player_name,
            )
            for u in self.store.users.values()
        ]

    def update_player_name(self, username: str, player_name: str) -> bool:
        user = self.store.users.get(username.lower())
        if not user:
            return False
        user.player_name = player_name.strip()
        self._save()
        return True

    def delete_user(self, username: str) -> bool:
        if username.lower() in self.store.users:
            del self.store.users[username.lower()]
            self._save()
            return True
        return False

    def change_password(self, username: str, new_password: str) -> bool:
        user = self.store.users.get(username.lower())
        if not user:
            return False
        user.hashed_password = _hash_password(new_password)
        self._save()
        return True


# --- JWT Token helpers ---

def create_access_token(username: str, secret_key: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def decode_access_token(
    token: str, secret_key: str
) -> Optional[TokenData]:
    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            return None
        return TokenData(username=username)
    except jwt.PyJWTError:
        return None


# --- FastAPI dependency ---

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(request: Request) -> UserRecord:
    """FastAPI dependency: extract and validate JWT from Authorization header."""
    token = await oauth2_scheme(request)
    secret_key: str = request.app.state.jwt_secret
    user_manager: UserManager = request.app.state.user_manager

    token_data = decode_access_token(token, secret_key)
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = user_manager.get_user(token_data.username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

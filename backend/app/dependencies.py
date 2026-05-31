"""Shared helpers for resolving per-user runtime objects."""

from pathlib import Path

from backend.auth import UserRecord
from backend.state_manager import StateManager


def get_user_state_manager(user: UserRecord, app_state) -> StateManager:
    """Return the cached StateManager for a user, creating it on first use."""
    cache = app_state.user_state_managers
    if user.username not in cache:
        user_data_dir = str(Path(app_state.data_dir) / "users" / user.username)
        cache[user.username] = StateManager(data_dir=user_data_dir)
    return cache[user.username]

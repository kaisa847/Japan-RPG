"""Admin-only endpoints: user management and deployment restart."""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from backend.app.config import DEPLOY_DIR
from backend.auth import UserManager, UserRecord, get_current_user
from backend.validation import validate_password

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/admin/users")
async def create_user_api(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only.")
    body = await request.json()
    password = body.get("password", "")
    try:
        validate_password(password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    um: UserManager = request.app.state.user_manager
    try:
        new_user = um.create_user(
            body["username"],
            password,
            body.get("is_admin", False),
            player_name=body.get("player_name", ""),
        )
        return {
            "username": new_user.username,
            "is_admin": new_user.is_admin,
            "player_name": new_user.player_name,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/admin/users")
async def list_users_api(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only.")
    um: UserManager = request.app.state.user_manager
    return {"users": [u.model_dump(exclude={"password_hash"}) for u in um.list_users()]}


async def _run_command(*args: str, cwd: str | None = None) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


@router.post("/api/admin/restart")
async def admin_restart(
    background_tasks: BackgroundTasks,
    user: UserRecord = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only.")

    # Step 1: git pull
    rc, stdout, stderr = await _run_command(
        "git",
        "pull",
        cwd=str(DEPLOY_DIR),
    )
    git_output = (stdout + stderr).strip()
    if rc != 0:
        return {"success": False, "phase": "git pull", "output": git_output}

    # Step 2: schedule restart *after* this response is sent
    async def _do_restart():
        await asyncio.sleep(1)  # give the response time to reach the client
        await _run_command("sudo", "systemctl", "restart", "japan-rpg")

    background_tasks.add_task(_do_restart)

    return {"success": True, "phase": "done", "output": git_output}

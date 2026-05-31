"""Player profile: display name, custom scenario and start prompt."""

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.app.config import DEFAULT_SCENARIO
from backend.app.scenario import parse_scenario
from backend.auth import UserManager, UserRecord, get_current_user

router = APIRouter()


@router.get("/api/player_name")
async def get_player_name(user: UserRecord = Depends(get_current_user)):
    return {"player_name": user.player_name}


@router.put("/api/player_name")
async def update_player_name(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    body = await request.json()
    name = body.get("player_name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Spielername darf nicht leer sein.")
    if len(name) > 30:
        raise HTTPException(
            status_code=400, detail="Spielername darf maximal 30 Zeichen lang sein."
        )
    um: UserManager = request.app.state.user_manager
    um.update_player_name(user.username, name)
    return {"player_name": name}


@router.get("/api/scenario")
async def get_scenario(user: UserRecord = Depends(get_current_user)):
    return {
        "scenario": user.custom_scenario or DEFAULT_SCENARIO,
        "is_default": not user.custom_scenario,
    }


@router.put("/api/scenario")
async def update_scenario(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    body = await request.json()
    scenario = body.get("scenario", "").strip()
    if not scenario:
        raise HTTPException(status_code=400, detail="Szenario darf nicht leer sein.")
    if len(scenario) > 5000:
        raise HTTPException(status_code=400, detail="Szenario darf maximal 5000 Zeichen lang sein.")
    um: UserManager = request.app.state.user_manager
    um.update_scenario(user.username, scenario)
    return {"scenario": scenario, "is_default": False}


@router.post("/api/scenario/reset")
async def reset_scenario(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    um: UserManager = request.app.state.user_manager
    um.update_scenario(user.username, "")
    return {"scenario": DEFAULT_SCENARIO, "is_default": True}


@router.get("/api/start_prompt")
async def get_start_prompt(user: UserRecord = Depends(get_current_user)):
    player_name = user.player_name or "Spieler"
    scenario_text = user.custom_scenario or DEFAULT_SCENARIO
    _premise, start_prompt = parse_scenario(scenario_text, player_name)
    return {"prompt": start_prompt}

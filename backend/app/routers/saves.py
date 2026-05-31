"""Save slot management and scene history."""

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.app.dependencies import get_user_state_manager
from backend.app.models import GameStateResponse, SaveSlotResponse
from backend.auth import UserRecord, get_current_user

router = APIRouter()


@router.get("/api/save_slots")
async def list_save_slots(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    sm = get_user_state_manager(user, request.app.state)
    slots = sm.list_save_slots()
    return {
        "slots": [
            SaveSlotResponse(
                slot_id=s.slot_id,
                name=s.name,
                day_number=s.day_number,
                current_character=s.current_character,
                current_background=s.current_background,
                saved_at=s.saved_at,
                turn_count=s.turn_count,
            ).model_dump()
            for s in slots
        ]
    }


@router.post("/api/save_slots/{slot_id}")
async def save_to_slot(
    slot_id: int,
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    if not 1 <= slot_id <= 9:
        raise HTTPException(status_code=400, detail="Slot ID must be between 1 and 9")
    sm = get_user_state_manager(user, request.app.state)
    body = await request.json()
    name = body.get("name", "")
    meta = sm.save_to_slot(slot_id, name=name)
    return SaveSlotResponse(
        slot_id=meta.slot_id,
        name=meta.name,
        day_number=meta.day_number,
        current_character=meta.current_character,
        current_background=meta.current_background,
        saved_at=meta.saved_at,
        turn_count=meta.turn_count,
    )


@router.post("/api/save_slots/{slot_id}/load")
async def load_from_slot(
    slot_id: int,
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    sm = get_user_state_manager(user, request.app.state)
    try:
        loaded = sm.load_from_slot(slot_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Save slot not found") from e

    last_scene = None
    if loaded.last_scene:
        last_scene = {
            "character": loaded.last_scene.get("character"),
            "expression": loaded.last_scene.get("expression", "neutral"),
            "background": loaded.last_scene.get("background"),
            "dialog_jp": loaded.last_scene.get("dialog_jp", ""),
            "dialog_jp_furigana": loaded.last_scene.get("dialog_jp_furigana", ""),
            "dialog_de": loaded.last_scene.get("dialog_de", ""),
        }
    return GameStateResponse(
        day_number=loaded.time.day,
        time=loaded.time.model_dump(),
        current_location=loaded.current_location,
        current_background=loaded.current_background,
        current_character=loaded.current_character,
        has_history=len(loaded.conversation_history) > 0,
        last_scene=last_scene,
        affection=loaded.affection.to_display_dict(),
        learning=loaded.learning.model_dump(),
        player_name=user.player_name,
    )


@router.delete("/api/save_slots/{slot_id}")
async def delete_save_slot(
    slot_id: int,
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    sm = get_user_state_manager(user, request.app.state)
    if sm.delete_save_slot(slot_id):
        return {"success": True}
    raise HTTPException(status_code=404, detail="Save slot not found")


@router.get("/api/scene_history")
async def get_scene_history(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    sm = get_user_state_manager(user, request.app.state)
    return {"scenes": sm.state.scene_history}

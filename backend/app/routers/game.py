"""Game state and scene generation endpoints."""

import logging

from fastapi import APIRouter, Depends, Request

from backend.app.config import DEFAULT_SCENARIO
from backend.app.dependencies import get_user_state_manager
from backend.app.models import GameStateResponse, GenerateSceneResponse, SceneInput
from backend.app.scenario import parse_scenario
from backend.auth import UserRecord, get_current_user
from backend.response_parser import SceneData

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/game_state")
async def get_game_state(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    sm = get_user_state_manager(user, request.app.state)
    s = sm.state
    last_scene = None
    if s.last_scene:
        last_scene = {
            "character": s.last_scene.get("character"),
            "expression": s.last_scene.get("expression", "neutral"),
            "background": s.last_scene.get("background"),
            "dialog_jp": s.last_scene.get("dialog_jp", ""),
            "dialog_jp_furigana": s.last_scene.get("dialog_jp_furigana", ""),
            "dialog_de": s.last_scene.get("dialog_de", ""),
        }
    return GameStateResponse(
        day_number=s.time.day,
        time=s.time.model_dump(),
        current_location=s.current_location,
        current_background=s.current_background,
        current_character=s.current_character,
        has_history=len(s.conversation_history) > 0,
        last_scene=last_scene,
        affection=s.affection.to_display_dict(),
        learning=s.learning.model_dump(),
        player_name=user.player_name,
    )


@router.post("/game_state/reset")
async def reset_game_state(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    sm = get_user_state_manager(user, request.app.state)
    fresh = sm.reset()
    return GameStateResponse(
        day_number=fresh.time.day,
        time=fresh.time.model_dump(),
        current_location=fresh.current_location,
        current_background=fresh.current_background,
        current_character=fresh.current_character,
        has_history=False,
        last_scene=None,
        affection=fresh.affection.to_display_dict(),
        learning=fresh.learning.model_dump(),
        player_name=user.player_name,
    )


@router.post("/generate_scene")
async def generate_scene(
    body: SceneInput,
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    sm = get_user_state_manager(user, request.app.state)
    handler = request.app.state.claude_handler

    # Safety net: if a SPIELSTART prompt arrives with leftover history,
    # perform a full reset so old context never bleeds into a new game.
    if body.user_input.startswith("(SPIELSTART") and sm.state.conversation_history:
        logger.info("SPIELSTART with stale history detected — performing full state reset")
        sm.reset()

    # Get current state info for Claude
    aoi_tone = sm.state.affection.tone
    weak_points = sm.state.learning.weak_points
    player_name = user.player_name or "Spieler"
    context_summary = sm.get_context_summary(player_name=player_name)
    history = sm.state.conversation_history

    # Resolve custom scenario premise
    scenario_text = user.custom_scenario or DEFAULT_SCENARIO
    custom_premise, _start = parse_scenario(scenario_text, player_name)

    if handler:
        scene = await handler.generate_scene_safe(
            user_input=body.user_input,
            game_state_summary=context_summary,
            conversation_history=history,
            aoi_tone=aoi_tone,
            weak_points=weak_points,
            player_name=player_name,
            custom_premise=custom_premise,
        )
    else:
        scene = SceneData(
            dialog_de="[API-Schlüssel nicht konfiguriert. Bitte ANTHROPIC_API_KEY setzen.]",
            dialog_jp="[APIキーが設定されていません。]",
            parse_errors=["Claude handler not available - no API key configured"],
        )

    # Update game state from scene
    sm.update_from_scene(
        {
            "background": scene.background,
            "character": scene.character,
        }
    )

    # Process analysis data (learning + affection updates)
    if scene.analysis:
        sm.process_analysis(scene.analysis.model_dump())

    # Process time update
    time_advanced = False
    if scene.scene_status:
        time_update = scene.scene_status.time_update
        if time_update:
            sm.process_time_update(time_update)
            time_advanced = True
        elif scene.scene_status.scene_end:
            # Fallback: scene ended but Claude forgot time_update → advance 1h
            logger.warning("scene_end=true but no time_update provided, defaulting to +1h")
            sm.process_time_update("+1h")
            time_advanced = True

    if not time_advanced:
        # No explicit time advancement — use periodic fallback
        sm.maybe_advance_time_periodic()

    # Update conversation history (dialog-only, no analysis/scene_status noise)
    sm.add_conversation_turn("user", body.user_input)
    dialog_summary = (
        f"<scene>\n"
        f"  <character>{scene.character or ''}</character>\n"
        f"  <dialog_jp>{scene.dialog_jp}</dialog_jp>\n"
        f"  <dialog_de>{scene.dialog_de}</dialog_de>\n"
        f"</scene>"
    )
    sm.add_conversation_turn("assistant", dialog_summary)

    # Store last scene for restoring UI state
    scene_dict = {
        "character": scene.character,
        "expression": scene.expression,
        "background": scene.background,
        "dialog_jp": scene.dialog_jp,
        "dialog_jp_furigana": scene.dialog_jp_furigana,
        "dialog_de": scene.dialog_de,
    }
    sm.state.last_scene = scene_dict
    sm.add_scene_to_history(scene_dict)

    sm.save()

    return GenerateSceneResponse(
        character=scene.character,
        expression=scene.expression,
        background=scene.background,
        dialog_jp=scene.dialog_jp,
        dialog_jp_furigana=scene.dialog_jp_furigana,
        dialog_de=scene.dialog_de,
        parse_errors=scene.parse_errors,
        analysis=scene.analysis.model_dump() if scene.analysis else None,
        scene_status=scene.scene_status.model_dump() if scene.scene_status else None,
        aoi_affection=sm.state.affection.to_display_dict(),
        time=sm.state.time.model_dump(),
    )

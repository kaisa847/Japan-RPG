"""FastAPI server for the Visual Novel Engine."""

import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.auth import (
    UserManager, UserRecord, create_access_token, get_current_user,
)
from backend.response_parser import SceneData
from backend.state_manager import StateManager

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
ASSETS_DIR = PROJECT_ROOT / "assets"

DEFAULT_SCENARIO = """\
Der Spieler heißt {player_name} und ist auf einem Sabbatical in Shimokitazawa, Tokio.
Er hat Aoi (林あおい) online in einem Sprachaustausch-Forum kennengelernt.
Heute treffen sie sich zum ersten Mal persönlich. Aoi zeigt {player_name} die Gegend \
und hilft ihm, sein Japanisch in echten Alltagssituationen zu verbessern.

SPIELSTART:
Aoi trifft {player_name} am Südausgang des Bahnhofs Shimokitazawa. \
Es ist ein sonniger Nachmittag. \
Sie erkennt ihn sofort und ruft fröhlich nach ihm. \
Aoi begrüßt {player_name} auf Japanisch — einfaches, anfängerfreundliches Japanisch. \
Sie ist aufgeregt, ihn endlich persönlich zu treffen, nachdem sie monatelang online gechattet haben. \
Verwende character=aoi, expression=happy, background=shimokitazawa_station. \
Dies ist die ERSTE Begegnung — halte den Ton freundlich aber noch etwas formell.\
"""


def _parse_scenario(scenario_text: str, player_name: str) -> tuple[str, str]:
    """Split scenario into (premise, start_prompt) and substitute player_name.

    If the text contains a 'SPIELSTART:' marker, everything before it becomes
    the premise (PRÄMISSE) and everything after becomes the start prompt.
    Otherwise the full text is used for both.
    """
    text = scenario_text.replace("{player_name}", player_name)
    marker = "SPIELSTART:"
    idx = text.find(marker)
    if idx >= 0:
        premise = text[:idx].strip()
        start = text[idx + len(marker):].strip()
        start_prompt = f"(SPIELSTART – Regieanweisung, NICHT als Dialog anzeigen:\n{start})"
    else:
        premise = text.strip()
        start_prompt = f"(SPIELSTART – Regieanweisung, NICHT als Dialog anzeigen:\n{premise})"
    return premise, start_prompt


# --- Response Models ---

class GenerateSceneResponse(BaseModel):
    character: Optional[str] = None
    expression: str = "neutral"
    background: Optional[str] = None
    dialog_jp: str = ""
    dialog_jp_furigana: str = ""
    dialog_de: str = ""
    parse_errors: list[str] = []
    analysis: Optional[dict] = None
    scene_status: Optional[dict] = None
    aoi_affection: Optional[dict] = None
    time: Optional[dict] = None


class GameStateResponse(BaseModel):
    day_number: int = 1
    time: dict = {}
    current_location: str = ""
    current_background: str = ""
    current_character: Optional[str] = None
    has_history: bool = False
    last_scene: Optional[dict] = None
    affection: Optional[dict] = None
    learning: Optional[dict] = None
    player_name: str = ""


class SaveSlotResponse(BaseModel):
    slot_id: int
    name: str = ""
    day_number: int = 1
    current_character: Optional[str] = None
    current_background: str = ""
    saved_at: str = ""
    turn_count: int = 0


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    data_dir = str(DATA_DIR)
    app.state.data_dir = data_dir

    # JWT secret
    jwt_secret_path = DATA_DIR / ".jwt_secret"
    if jwt_secret_path.exists():
        app.state.jwt_secret = jwt_secret_path.read_text(encoding="utf-8").strip()
    else:
        app.state.jwt_secret = secrets.token_urlsafe(32)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        jwt_secret_path.write_text(app.state.jwt_secret, encoding="utf-8")
        jwt_secret_path.chmod(0o600)

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


app = FastAPI(title="Japanese Life: Tokyo Stories", lifespan=lifespan)

_cors_origin = os.getenv("CORS_ORIGIN", "")
_allowed_origins = [_cors_origin] if _cors_origin else []

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Helpers ---

def get_user_state_manager(user: UserRecord, app_state) -> StateManager:
    cache = app_state.user_state_managers
    if user.username not in cache:
        user_data_dir = str(Path(app_state.data_dir) / "users" / user.username)
        cache[user.username] = StateManager(data_dir=user_data_dir)
    return cache[user.username]


# --- Static files ---

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


# --- Auth routes ---

@app.post("/api/auth/login")
async def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    # CSRF protection: verify Origin/Referer matches this server
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    expected = _cors_origin or str(request.base_url).rstrip("/")
    if origin and not origin.startswith(expected):
        raise HTTPException(status_code=403, detail="Cross-origin request blocked.")

    um: UserManager = request.app.state.user_manager
    user = um.authenticate(form.username, form.password)
    if not user:
        raise HTTPException(status_code=401, detail="Falsche Zugangsdaten.")
    token = create_access_token(user.username, request.app.state.jwt_secret)
    return {"access_token": token, "token_type": "bearer", "username": user.username}


@app.get("/api/auth/me")
async def get_me(user: UserRecord = Depends(get_current_user)):
    return {
        "username": user.username,
        "is_admin": user.is_admin,
        "player_name": user.player_name,
    }


@app.post("/api/admin/users")
async def create_user_api(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only.")
    body = await request.json()
    password = body.get("password", "")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Passwort muss mindestens 8 Zeichen lang sein.")
    um: UserManager = request.app.state.user_manager
    try:
        new_user = um.create_user(
            body["username"], password, body.get("is_admin", False),
            player_name=body.get("player_name", ""),
        )
        return {
            "username": new_user.username,
            "is_admin": new_user.is_admin,
            "player_name": new_user.player_name,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/admin/users")
async def list_users_api(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only.")
    um: UserManager = request.app.state.user_manager
    return {"users": [u.model_dump(exclude={"password_hash"}) for u in um.list_users()]}


DEPLOY_DIR = Path("/home/jrpg/Japan-RPG")


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


@app.post("/api/admin/restart")
async def admin_restart(
    background_tasks: BackgroundTasks,
    user: UserRecord = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only.")

    # Step 1: git pull
    rc, stdout, stderr = await _run_command(
        "git", "pull", cwd=str(DEPLOY_DIR),
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


# --- Player name ---

@app.get("/api/player_name")
async def get_player_name(user: UserRecord = Depends(get_current_user)):
    return {"player_name": user.player_name}


@app.put("/api/player_name")
async def update_player_name(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    body = await request.json()
    name = body.get("player_name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Spielername darf nicht leer sein.")
    if len(name) > 30:
        raise HTTPException(status_code=400, detail="Spielername darf maximal 30 Zeichen lang sein.")
    um: UserManager = request.app.state.user_manager
    um.update_player_name(user.username, name)
    return {"player_name": name}


# --- Scenario ---

@app.get("/api/scenario")
async def get_scenario(user: UserRecord = Depends(get_current_user)):
    return {
        "scenario": user.custom_scenario or DEFAULT_SCENARIO,
        "is_default": not user.custom_scenario,
    }


@app.put("/api/scenario")
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


@app.post("/api/scenario/reset")
async def reset_scenario(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    um: UserManager = request.app.state.user_manager
    um.update_scenario(user.username, "")
    return {"scenario": DEFAULT_SCENARIO, "is_default": True}


# --- Root redirect ---

@app.get("/")
async def root():
    return RedirectResponse(url="/app/login.html")


# --- Start prompt ---

@app.get("/api/start_prompt")
async def get_start_prompt(user: UserRecord = Depends(get_current_user)):
    player_name = user.player_name or "Spieler"
    scenario_text = user.custom_scenario or DEFAULT_SCENARIO
    _premise, start_prompt = _parse_scenario(scenario_text, player_name)
    return {"prompt": start_prompt}


# --- Asset availability ---

@app.get("/api/assets/available")
async def get_available_assets():
    characters: dict[str, list[str]] = {}
    backgrounds: list[str] = []

    char_dir = ASSETS_DIR / "characters"
    if char_dir.exists():
        for char_folder in char_dir.iterdir():
            if char_folder.is_dir():
                expressions = [
                    f.stem for f in char_folder.iterdir()
                    if f.suffix.lower() in (".png", ".jpg", ".webp")
                ]
                if expressions:
                    characters[char_folder.name] = sorted(expressions)

    bg_dir = ASSETS_DIR / "backgrounds"
    if bg_dir.exists():
        backgrounds = sorted([
            f.stem for f in bg_dir.iterdir()
            if f.suffix.lower() in (".png", ".jpg", ".webp")
        ])

    return {"characters": characters, "backgrounds": backgrounds}


@app.get("/api/locations")
async def get_locations():
    loc_path = DATA_DIR / "locations.json"
    if not loc_path.exists():
        raise HTTPException(status_code=404, detail="locations.json not found")
    config = json.loads(loc_path.read_text(encoding="utf-8"))
    return config


# --- Game state ---

@app.get("/game_state")
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


@app.post("/game_state/reset")
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


# --- Scene generation ---

class SceneInput(BaseModel):
    user_input: str


@app.post("/generate_scene")
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
    custom_premise, _start = _parse_scenario(scenario_text, player_name)

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
    sm.update_from_scene({
        "background": scene.background,
        "character": scene.character,
    })

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


# --- Save slots ---

@app.get("/api/save_slots")
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


@app.post("/api/save_slots/{slot_id}")
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


@app.post("/api/save_slots/{slot_id}/load")
async def load_from_slot(
    slot_id: int,
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    sm = get_user_state_manager(user, request.app.state)
    try:
        loaded = sm.load_from_slot(slot_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Save slot not found")

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


@app.delete("/api/save_slots/{slot_id}")
async def delete_save_slot(
    slot_id: int,
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    sm = get_user_state_manager(user, request.app.state)
    if sm.delete_save_slot(slot_id):
        return {"success": True}
    raise HTTPException(status_code=404, detail="Save slot not found")


# --- Scene history ---

@app.get("/api/scene_history")
async def get_scene_history(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    sm = get_user_state_manager(user, request.app.state)
    return {"scenes": sm.state.scene_history}


# --- TTS ---

class TTSInput(BaseModel):
    text: str
    expression: str = "neutral"


@app.get("/api/tts/status")
async def tts_status(request: Request):
    tts = getattr(request.app.state, "tts_service", None)
    if tts is None:
        return {"status": "unavailable", "detail": "TTS dependencies not installed."}
    return tts.status


@app.post("/api/tts/generate")
async def tts_generate(
    body: TTSInput,
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    tts = getattr(request.app.state, "tts_service", None)
    if tts is None or not tts.is_ready:
        raise HTTPException(status_code=503, detail="TTS service not available.")

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text darf nicht leer sein.")
    if len(text) > 200:
        raise HTTPException(status_code=400, detail="Text zu lang (max 200 Zeichen).")

    semaphore: asyncio.Semaphore = request.app.state.tts_semaphore

    # Only allow one synthesis at a time; reject others immediately.
    if semaphore.locked():
        raise HTTPException(
            status_code=429,
            detail="TTS ist beschaeftigt. Bitte kurz warten.",
        )

    async with semaphore:
        try:
            audio_bytes = await asyncio.wait_for(
                tts.synthesize(text, body.expression),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            logger.error("TTS synthesis timed out for text: %.50s…", text)
            raise HTTPException(status_code=504, detail="Sprachsynthese Timeout.")
        except Exception as e:
            logger.error("TTS synthesis failed: %s", e)
            raise HTTPException(status_code=500, detail="Sprachsynthese fehlgeschlagen.")

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )


# --- Cache-busting middleware ---

@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/app/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

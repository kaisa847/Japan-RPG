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
    sanitize_profile,
)
from backend.response_parser import SceneData, SceneStatus
from backend.sprite_manifest import SpriteManifests
from backend.state_manager import StateManager
from backend.story_engine import StoryEngine

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
ASSETS_DIR = PROJECT_ROOT / "assets"

DEFAULT_SCENARIO = """\
{player_name} hat 90 Tage Auszeit genommen und wohnt für diese Zeit in einem kleinen \
Share House in Shimokitazawa, Tokio. Kennengelernt haben sich {player_name} und Aoi \
(林あおい) vor Monaten im Sprachaustausch-Forum "NihongoConnect". Ihr Deal: Sie sprechen \
Japanisch, dafür hilft {player_name} ihr mit {native_language} — Aoi träumt von einem \
Auslandssemester. Nach wochenlangem Chatten ist {player_name} nun wirklich in Tokio. \
Aoi zeigt {player_name} ihre Stadt — und mit jedem Tag stellt sich mehr die Frage, \
was passiert, wenn Tag 90 kommt und der Rückflug geht.

SPIELSTART:
Aoi trifft {player_name} am Südausgang des Bahnhofs Shimokitazawa — genau wie im \
Forum-Chat verabredet. Es ist ein sonniger Nachmittag, {player_name} ist heute Morgen \
gelandet. Sie erkennt {player_name} sofort und ruft fröhlich — endlich persönlich, \
nach all den Wochen im Chat! Aoi begrüßt {player_name} auf Japanisch — einfaches, \
anfängerfreundliches Japanisch. \
Verwende character=aoi, expression=happy, background=shimokitazawa_station. \
Erste ECHTE Begegnung — aufgeregt-freundlich, aber noch etwas schüchtern-formell.\
"""

PROLOGUE_START_PROMPT = """\
(SPIELSTART – PROLOG. Regieanweisung, NICHT als Dialog anzeigen:
Beginne den Forum-Chat: Aoi antwortet begeistert auf {player_name}s Beitrag im \
Sprachaustausch-Forum "NihongoConnect" (Suche: Tandem-Partner für Japanisch). \
Erste kurze Chat-Nachricht: Sie stellt sich knapp vor und stellt eine Gegenfrage. \
character=aoi, background leer lassen.)"""

# German labels for auto title cards on day changes
GERMAN_PERIODS = {
    "early_morning": "Früher Morgen",
    "morning": "Morgen",
    "midday": "Mittag",
    "afternoon": "Nachmittag",
    "evening": "Abend",
    "night": "Nacht",
    "late_night": "Tiefe Nacht",
}


def _scripted_prologue_opener() -> SceneData:
    """Hand-authored first chat message of the prologue.

    The opening beat is always the same (greeting, who Aoi is, a
    counter-question) — scripting it makes the first impression
    deterministic, instant, free of API cost, and guarantees Aoi
    assumes nothing about the player (no language, no origin).
    """
    return SceneData(
        character="aoi",
        expression="happy",
        dialog_jp="「はじめまして！タンデムの投稿、見ました！私は林あおい、東京の大学生です。あなたはどこの国の人ですか？」",
        dialog_jp_furigana=(
            "「はじめまして！タンデムの投稿[とうこう]、見[み]ました！"
            "私[わたし]は林[はやし]あおい、東京[とうきょう]の大学生[だいがくせい]です。"
            "あなたはどこの国[くに]の人[ひと]ですか？」"
        ),
        dialog_de=(
            "„Freut mich! Ich habe deinen Tandem-Beitrag gesehen! "
            "Ich bin Hayashi Aoi, Studentin aus Tokio. Aus welchem Land kommst du?“"
        ),
        scene_status=SceneStatus(
            time_update="+1h",
            new_vocab=[
                {"word": "投稿", "reading": "とうこう", "meaning_de": "Beitrag/Post"},
                {"word": "国", "reading": "くに", "meaning_de": "Land"},
            ],
        ),
    )


def _seed_level_from_profile(profile: dict) -> str:
    """Map the self-assessed language level onto a starting JLPT level."""
    lvl = (profile.get("sprachniveau") or "").lower()
    if "n3" in lvl:
        return "N3"
    if "n4" in lvl or "fortgeschritten" in lvl:
        return "N4"
    return "N5"


def _parse_scenario(
    scenario_text: str, player_name: str, native_language: str = "Deutsch",
) -> tuple[str, str]:
    """Split scenario into (premise, start_prompt) and substitute player_name.

    If the text contains a 'SPIELSTART:' marker, everything before it becomes
    the premise (PRÄMISSE) and everything after becomes the start prompt.
    Otherwise the full text is used for both.
    """
    text = scenario_text.replace("{player_name}", player_name)
    text = text.replace("{native_language}", native_language)
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
    speaker: Optional[str] = None
    expression: str = "neutral"
    pose: Optional[str] = None
    staging: list[str] = []
    background: Optional[str] = None
    dialog_jp: str = ""
    dialog_jp_furigana: str = ""
    dialog_de: str = ""
    parse_errors: list[str] = []
    analysis: Optional[dict] = None
    scene_status: Optional[dict] = None
    aoi_affection: Optional[dict] = None
    time: Optional[dict] = None
    learning: Optional[dict] = None
    story_beat: Optional[str] = None
    phase: str = "main"
    title_card: Optional[str] = None
    ending: Optional[dict] = None


class GameStateResponse(BaseModel):
    phase: str = "main"
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

    # Story engine (shared, stateless — per-user progress lives in game state)
    app.state.story_engine = StoryEngine(data_dir=data_dir)

    # Layered sprite manifests (pose/face compositing)
    app.state.sprite_manifests = SpriteManifests(assets_dir=str(ASSETS_DIR))

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


# --- Player profile ---

@app.get("/api/player_profile")
async def get_player_profile(user: UserRecord = Depends(get_current_user)):
    return {"profile": user.player_profile}


@app.put("/api/player_profile")
async def update_player_profile(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    body = await request.json()
    updates = body.get("profile", {})
    if not isinstance(updates, dict):
        raise HTTPException(status_code=400, detail="profile muss ein Objekt sein.")
    um: UserManager = request.app.state.user_manager
    profile = um.update_profile(user.username, updates)
    if profile is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")
    return {"profile": profile}


@app.post("/api/prologue/skip")
async def skip_prologue(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    """Skip the forum-chat prologue and jump straight to the main game.

    Profile data collected so far is kept; missing fields become
    in-game questions from Aoi (anti-assumption rule).
    """
    sm = get_user_state_manager(user, request.app.state)
    if sm.state.phase == "prologue":
        sm.state.phase = "main"
        sm.state.conversation_history = []
        sm.state.time.day = 1
        sm.state.time.hour = 14
        sm.state.time.period = "afternoon"
        sm.save()
    return {"phase": sm.state.phase}


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
async def get_start_prompt(
    request: Request,
    user: UserRecord = Depends(get_current_user),
):
    player_name = user.player_name or "Spieler"
    sm = get_user_state_manager(user, request.app.state)
    if sm.state.phase == "prologue":
        return {"prompt": PROLOGUE_START_PROMPT.format(player_name=player_name)}
    native_language = user.player_profile.get("muttersprache", "Deutsch")
    scenario_text = user.custom_scenario or DEFAULT_SCENARIO
    _premise, start_prompt = _parse_scenario(
        scenario_text, player_name, native_language=native_language,
    )
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

    manifests = app.state.sprite_manifests.to_api_dict()
    return {"characters": characters, "backgrounds": backgrounds, "manifests": manifests}


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
            "speaker": s.last_scene.get("speaker"),
            "expression": s.last_scene.get("expression", "neutral"),
            "pose": s.last_scene.get("pose"),
            "staging": s.last_scene.get("staging", []),
            "background": s.last_scene.get("background"),
            "dialog_jp": s.last_scene.get("dialog_jp", ""),
            "dialog_jp_furigana": s.last_scene.get("dialog_jp_furigana", ""),
            "dialog_de": s.last_scene.get("dialog_de", ""),
        }
    return GameStateResponse(
        phase=s.phase,
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
    fresh = sm.reset(
        phase="prologue",
        overall_level=_seed_level_from_profile(user.player_profile),
    )
    return GameStateResponse(
        phase=fresh.phase,
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
    is_prologue_start = (
        body.user_input.startswith("(SPIELSTART")
        and "PROLOG" in body.user_input[:40]
    )
    if body.user_input.startswith("(SPIELSTART") and sm.state.conversation_history:
        logger.info("SPIELSTART with stale history detected — performing full state reset")
        sm.reset(
            phase="prologue" if is_prologue_start else "main",
            overall_level=_seed_level_from_profile(user.player_profile),
        )

    # Get current state info for Claude
    aoi_tone = sm.state.affection.tone
    weak_points = sm.state.learning.weak_points
    player_name = user.player_name or "Spieler"
    context_summary = sm.get_context_summary(player_name=player_name)

    # One-time milestone director notes (level-up, vocab milestones)
    milestone_note = sm.pending_milestone_note(player_name)
    if milestone_note:
        context_summary += f"\n{milestone_note}"
    history = sm.state.conversation_history

    # Resolve custom scenario premise
    player_profile = dict(user.player_profile)
    native_language = player_profile.get("muttersprache", "Deutsch")
    scenario_text = user.custom_scenario or DEFAULT_SCENARIO
    custom_premise, _start = _parse_scenario(
        scenario_text, player_name, native_language=native_language,
    )

    # Long-term memory, due vocabulary, active story beat
    memories = [
        {"day": m.day, "text": m.text} for m in sm.state.memories
    ]
    due_vocab = [
        {"word": v.word, "reading": v.reading, "meaning_de": v.meaning_de}
        for v in sm.get_due_vocab()
    ]
    sprite_manifests: SpriteManifests = request.app.state.sprite_manifests
    available_poses = sprite_manifests.pose_ids("aoi") or None

    # Story beats pause during the prologue (the chat has its own script)
    active_beat = None
    story_beat_block = None
    if sm.state.phase != "prologue":
        stats = sm.learning_stats()
        story_engine: StoryEngine = request.app.state.story_engine
        active_beat = story_engine.select_beat(
            day=sm.state.time.day,
            score=sm.state.affection.weighted_score,
            flags=sm.state.flags,
            completed_beats=sm.state.story.completed_beats,
            vocab_count=stats["vocab_count"],
            topics_mastered=stats["topics_mastered"],
            level=stats["level"],
        )
        story_beat_block = (
            story_engine.build_prompt_block(active_beat, player_name)
            if active_beat else None
        )

    if is_prologue_start and sm.state.phase == "prologue":
        # The prologue opener is hand-authored: deterministic, instant,
        # and guaranteed to assume nothing about the player.
        scene = _scripted_prologue_opener()
    elif handler:
        scene = await handler.generate_scene_safe(
            user_input=body.user_input,
            game_state_summary=context_summary,
            conversation_history=history,
            aoi_tone=aoi_tone,
            weak_points=weak_points,
            player_name=player_name,
            custom_premise=custom_premise,
            jlpt_level=sm.state.learning.overall_level,
            memories=memories,
            due_vocab=due_vocab,
            story_beat_block=story_beat_block,
            available_poses=available_poses,
            player_profile=player_profile,
            phase=sm.state.phase,
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

    # Profile updates, prologue end, title card, ending
    ending_reached = None
    title_card = scene.scene_status.title_card if scene.scene_status else None
    if scene.scene_status:
        st = scene.scene_status
        if st.profile_update:
            um: UserManager = request.app.state.user_manager
            updated = um.update_profile(user.username, st.profile_update)
            if updated is not None:
                logger.info("Profile updated from prologue: %s",
                            list(st.profile_update.keys()))
        if st.prologue_end and sm.state.phase == "prologue":
            sm.state.phase = "main"
            # The main game starts fresh on day 1, afternoon of the arrival
            sm.state.time.day = 1
            sm.state.time.hour = 14
            sm.state.time.period = "afternoon"
            sm.state.turns_since_time_advance = 0
            if not title_card:
                title_card = "Drei Wochen später — Tokio"
        elif st.time_update and st.time_update.strip().lower() == "next_day" and not title_card:
            period = GERMAN_PERIODS.get(sm.state.time.period, "")
            title_card = f"Tag {sm.state.time.day} — {period}".rstrip(" —")

    # Process episodic memory, vocab, story flag, promises
    if scene.scene_status:
        st = scene.scene_status
        if st.memory:
            sm.add_memory(st.memory)
        if st.new_vocab:
            sm.process_vocab(st.new_vocab)
        if st.story_flag and active_beat and st.story_flag == active_beat.sets_flag:
            sm.complete_story_beat(active_beat.id, active_beat.sets_flag)
            logger.info("Story beat completed: %s", active_beat.id)
            if active_beat.type == "ending":
                ending_reached = {
                    "id": active_beat.id,
                    "title": active_beat.title,
                    "epilogue": active_beat.epilogue or "",
                }
                if not title_card:
                    title_card = f"Ende: {active_beat.title}"
        if st.promise:
            sm.add_promise(st.promise)
        if st.promise_resolved:
            sm.resolve_promise(st.promise_resolved)

    # Update conversation history (dialog-only, no analysis/scene_status noise)
    sm.add_conversation_turn("user", body.user_input)
    speaker_line = f"  <speaker>{scene.speaker}</speaker>\n" if scene.speaker else ""
    dialog_summary = (
        f"<scene>\n"
        f"  <character>{scene.character or ''}</character>\n"
        f"{speaker_line}"
        f"  <dialog_jp>{scene.dialog_jp}</dialog_jp>\n"
        f"  <dialog_de>{scene.dialog_de}</dialog_de>\n"
        f"</scene>"
    )
    sm.add_conversation_turn("assistant", dialog_summary)

    # Validate pose against the sprite manifest (unknown -> None,
    # frontend falls back to the character's default pose)
    pose = sprite_manifests.validate_pose(scene.character or "", scene.pose)

    # Store last scene for restoring UI state
    scene_dict = {
        "character": scene.character,
        "speaker": scene.speaker,
        "expression": scene.expression,
        "pose": pose,
        "staging": scene.staging,
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
        speaker=scene.speaker,
        expression=scene.expression,
        pose=pose,
        staging=scene.staging,
        background=scene.background,
        dialog_jp=scene.dialog_jp,
        dialog_jp_furigana=scene.dialog_jp_furigana,
        dialog_de=scene.dialog_de,
        parse_errors=scene.parse_errors,
        analysis=scene.analysis.model_dump() if scene.analysis else None,
        scene_status=scene.scene_status.model_dump() if scene.scene_status else None,
        aoi_affection=sm.state.affection.to_display_dict(),
        time=sm.state.time.model_dump(),
        learning=sm.state.learning.model_dump(),
        story_beat=active_beat.title if active_beat else None,
        phase=sm.state.phase,
        title_card=title_card,
        ending=ending_reached,
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
            "speaker": loaded.last_scene.get("speaker"),
            "expression": loaded.last_scene.get("expression", "neutral"),
            "pose": loaded.last_scene.get("pose"),
            "staging": loaded.last_scene.get("staging", []),
            "background": loaded.last_scene.get("background"),
            "dialog_jp": loaded.last_scene.get("dialog_jp", ""),
            "dialog_jp_furigana": loaded.last_scene.get("dialog_jp_furigana", ""),
            "dialog_de": loaded.last_scene.get("dialog_de", ""),
        }
    return GameStateResponse(
        phase=loaded.phase,
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

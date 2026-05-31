"""Pydantic request/response models shared across routers."""

from pydantic import BaseModel


class GenerateSceneResponse(BaseModel):
    character: str | None = None
    expression: str = "neutral"
    background: str | None = None
    dialog_jp: str = ""
    dialog_jp_furigana: str = ""
    dialog_de: str = ""
    parse_errors: list[str] = []
    analysis: dict | None = None
    scene_status: dict | None = None
    aoi_affection: dict | None = None
    time: dict | None = None


class GameStateResponse(BaseModel):
    day_number: int = 1
    time: dict = {}
    current_location: str = ""
    current_background: str = ""
    current_character: str | None = None
    has_history: bool = False
    last_scene: dict | None = None
    affection: dict | None = None
    learning: dict | None = None
    player_name: str = ""


class SaveSlotResponse(BaseModel):
    slot_id: int
    name: str = ""
    day_number: int = 1
    current_character: str | None = None
    current_background: str = ""
    saved_at: str = ""
    turn_count: int = 0


class SceneInput(BaseModel):
    user_input: str


class TTSInput(BaseModel):
    text: str
    expression: str = "neutral"

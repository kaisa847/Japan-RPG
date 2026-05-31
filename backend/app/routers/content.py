"""Static content endpoints: root redirect, asset listing, locations."""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from backend.app.config import ASSETS_DIR, DATA_DIR

router = APIRouter()


@router.get("/")
async def root():
    return RedirectResponse(url="/app/login.html")


@router.get("/api/assets/available")
async def get_available_assets():
    characters: dict[str, list[str]] = {}
    backgrounds: list[str] = []

    char_dir = ASSETS_DIR / "characters"
    if char_dir.exists():
        for char_folder in char_dir.iterdir():
            if char_folder.is_dir():
                expressions = [
                    f.stem
                    for f in char_folder.iterdir()
                    if f.suffix.lower() in (".png", ".jpg", ".webp")
                ]
                if expressions:
                    characters[char_folder.name] = sorted(expressions)

    bg_dir = ASSETS_DIR / "backgrounds"
    if bg_dir.exists():
        backgrounds = sorted(
            [f.stem for f in bg_dir.iterdir() if f.suffix.lower() in (".png", ".jpg", ".webp")]
        )

    return {"characters": characters, "backgrounds": backgrounds}


@router.get("/api/locations")
async def get_locations():
    loc_path = DATA_DIR / "locations.json"
    if not loc_path.exists():
        raise HTTPException(status_code=404, detail="locations.json not found")
    config = json.loads(loc_path.read_text(encoding="utf-8"))
    return config

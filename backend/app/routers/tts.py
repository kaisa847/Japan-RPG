"""Text-to-speech endpoints (optional edge-tts voice synthesis)."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from backend.app.models import TTSInput
from backend.auth import UserRecord, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/tts/status")
async def tts_status(request: Request):
    tts = getattr(request.app.state, "tts_service", None)
    if tts is None:
        return {"status": "unavailable", "detail": "TTS dependencies not installed."}
    return tts.status


@router.post("/api/tts/generate")
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
        except TimeoutError as e:
            logger.error("TTS synthesis timed out for text: %.50s…", text)
            raise HTTPException(status_code=504, detail="Sprachsynthese Timeout.") from e
        except Exception as e:
            logger.error("TTS synthesis failed: %s", e)
            raise HTTPException(status_code=500, detail="Sprachsynthese fehlgeschlagen.") from e

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )

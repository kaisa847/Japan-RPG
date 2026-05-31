"""Text-to-Speech service using edge-tts (Microsoft Neural TTS).

Uses ja-JP-NanamiNeural (female Japanese voice) with pitch/rate adjustments
per expression. Cloud-based - zero CPU/RAM usage on the VPS.
"""

import io
import logging

logger = logging.getLogger(__name__)

# Japanese female neural voice
VOICE = "ja-JP-NanamiNeural"

# Mapping from Aoi's 16 sprite expressions to voice adjustments.
# Each entry is (pitch_adjustment, rate_adjustment).
EXPRESSION_VOICE_MAP: dict[str, tuple[str, str]] = {
    "neutral": ("+0Hz", "+0%"),
    "happy": ("+3Hz", "+8%"),
    "excited": ("+5Hz", "+12%"),
    "curious": ("+2Hz", "+0%"),
    "talking": ("+0Hz", "+0%"),
    "laughing": ("+5Hz", "+10%"),
    "surprised": ("+6Hz", "+5%"),
    "thinking": ("-1Hz", "-5%"),
    "embarrassed": ("+1Hz", "-3%"),
    "determined": ("-2Hz", "+5%"),
    "worried": ("-1Hz", "-5%"),
    "sleepy": ("-3Hz", "-10%"),
    "angry": ("-2Hz", "+8%"),
    "disgusted": ("-2Hz", "-3%"),
    "shocked": ("+8Hz", "+5%"),
    "ahegao": ("+3Hz", "+5%"),
}

DEFAULT_VOICE_PARAMS = ("+0Hz", "+0%")

MAX_TTS_TEXT_LENGTH = 200


class TTSService:
    """Manages edge-tts speech synthesis (cloud-based, no local models)."""

    def __init__(self):
        self._ready = False
        self._error: str | None = None

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def status(self) -> dict:
        if self._ready:
            return {"status": "ready"}
        if self._error:
            return {"status": "error", "detail": self._error}
        return {"status": "not_initialized"}

    async def load(self) -> None:
        """Verify edge-tts is available."""
        try:
            import edge_tts  # noqa: F401

            self._ready = True
            logger.info("TTS service ready (edge-tts, cloud-based).")
        except ImportError:
            self._error = "edge-tts not installed"
            logger.error("edge-tts package not installed. Run: pip install edge-tts")
            raise

    async def synthesize(
        self,
        text: str,
        expression: str = "neutral",
    ) -> bytes:
        """Generate speech audio for the given Japanese text and expression.

        Args:
            text: Japanese text to speak.
            expression: One of Aoi's 16 expression names.

        Returns:
            MP3 audio data as bytes.
        """
        if not self._ready:
            raise RuntimeError("TTS service is not initialized. Call load() first.")

        import edge_tts

        # Truncate long text at a sentence boundary for natural output.
        if len(text) > MAX_TTS_TEXT_LENGTH:
            truncated = text[:MAX_TTS_TEXT_LENGTH]
            for sep in ("。", "！", "？", "!", "?", "、", ","):
                idx = truncated.rfind(sep)
                if idx > 0:
                    truncated = truncated[: idx + 1]
                    break
            text = truncated

        pitch, rate = EXPRESSION_VOICE_MAP.get(expression, DEFAULT_VOICE_PARAMS)

        communicate = edge_tts.Communicate(
            text=text,
            voice=VOICE,
            pitch=pitch,
            rate=rate,
        )

        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])

        return buf.getvalue()
